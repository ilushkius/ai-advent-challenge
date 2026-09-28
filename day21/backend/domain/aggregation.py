"""Агрегация накопленных записей в сводку (день 18) — чистые правила.

Третий инструмент планировщика (``generate_summary``) считает сводку за период по
строкам таблицы ``collected_data``. Вся арифметика — здесь: ни БД, ни сети, ни
даты «сейчас» (оба конца периода приходят аргументами), поэтому правила
проверяются тестами без стенда.

Как читается payload записи. Ответ внешнего API — произвольный JSON, и сводка
обязана работать с любой его формой: список обходится поэлементно, словарь —
рекурсивно по ключам, а листья собираются под ИМЕНЕМ СВОЕГО КЛЮЧА
(``id``, ``userId``, ``title``) без индексов — по ним и считаются метрики. Числа
дают ``count/avg/min/max``, строки — число уникальных значений и примеры.
``bool`` исключён из числовых полей: в Python он подкласс ``int`` (та же
оговорка, что в ``mcp_tool_call``).

Пустой период — не ошибка: тик состоялся, сводка сохранена, и её текст прямо
говорит, что записей не собрано. Так «тишина» в разделе «Сводки» отличается от
«задача не срабатывала».
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..core import config

#: Имя сводки, когда вызывающий его не назвал (сводка «по всем данным»).
DEFAULT_SUMMARY_NAME = "данные"

#: Строка пустого периода: по ней видно, что сводка посчитана, а данных не было.
EMPTY_PERIOD_TEXT = "За период записей не собрано."

#: Сколько символов примера значения попадает в текст сводки.
SAMPLE_MAX = 40


@dataclass(frozen=True, slots=True)
class AggregateResult:
    """Итог агрегации: период, число записей, ключевые метрики и текст сводки."""

    period_start: datetime
    period_end: datetime
    total_records: int
    key_metrics: dict[str, Any]
    summary_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Словарь результата для API, отчёта и поля ``aggregate`` шага сводки."""
        return {
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_records": self.total_records,
            "summary_text": self.summary_text,
            "key_metrics": _copy_metrics(self.key_metrics),
        }


def flatten_payload(row_name: str, payload: Any, out: dict[str, list[Any]]) -> None:
    """Раскладывает payload по полям: ``{имя ключа: [значения…]}``.

    Список обходится поэлементно, словарь — рекурсивно по ключам, а лист
    (число, строка, флаг) попадает в список СВОЕГО ключа. Верхний уровень без
    ключа (payload — просто число или строка) складывается под именем записи
    (``row_name``), чтобы значение не потерялось.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            flatten_payload(str(key), value, out)
        return
    if isinstance(payload, list):
        for item in payload:
            flatten_payload(row_name, item, out)
        return
    out.setdefault(str(row_name), []).append(payload)


def aggregate_records(
    rows: Iterable[dict[str, Any]],
    period_start: datetime,
    period_end: datetime,
    *,
    name: str = "",
    max_fields: Optional[int] = None,
    samples: Optional[int] = None,
) -> AggregateResult:
    """Считает сводку по строкам ``{"name", "payload", "collected_at"}`` за период.

    ``name`` — имя сводки для её текста; ``max_fields`` и ``samples`` ограничивают
    объём ``key_metrics`` (по умолчанию — границы дня из ``config``).
    """
    start = _as_utc(period_start)
    end = _as_utc(period_end) or start
    items = list(rows or [])
    metrics = _key_metrics(items, start, end, max_fields, samples)
    base = AggregateResult(start, end, len(items), metrics, "")
    return replace(base, summary_text=render_summary_text(name or DEFAULT_SUMMARY_NAME, base))


def render_summary_text(name: str, result: AggregateResult) -> str:
    """Текстовая сводка для ``periodic_summaries.content`` и уведомления.

    Формат — четыре строки: шапка с периодом и длительностью, число записей с
    источниками, числовые поля (среднее, минимум, максимум) и категориальные
    (сколько уникальных и примеры). Пустой период — две строки.
    """
    metrics = result.key_metrics or {}
    seconds = int((result.period_end - result.period_start).total_seconds())
    lines = [f"Сводка «{name}» за период {_period_text(result.period_start, result.period_end)} ({seconds} с)."]
    sources = metrics.get("sources") or {}
    if not result.total_records:
        lines.append("Записей собрано: 0.")
        lines.append(EMPTY_PERIOD_TEXT)
        return "\n".join(lines)
    source_text = ", ".join(f"{key} — {value}" for key, value in sources.items())
    lines.append(
        f"Записей собрано: {result.total_records}"
        + (f" (источники: {source_text})." if source_text else ".")
    )
    numeric = metrics.get("numeric") or {}
    if numeric:
        lines.append("Числовые поля: " + "; ".join(
            f"{field} — {data['count']} значений, среднее {data['avg']}, "
            f"мин {data['min']}, макс {data['max']}"
            for field, data in numeric.items()
        ) + ".")
    categorical = metrics.get("categorical") or {}
    if categorical:
        lines.append("Категориальные поля: " + "; ".join(
            _categorical_text(field, data) for field, data in categorical.items()
        ) + ".")
    return "\n".join(lines)


def _categorical_text(field: str, data: dict[str, Any]) -> str:
    """Одно категориальное поле: сколько уникальных и, если есть, примеры."""
    piece = f"{field} — {data.get('unique', 0)} уникальных"
    samples = data.get("samples") or []
    if samples:
        piece += " (например: " + ", ".join(f"«{item}»" for item in samples) + ")"
    return piece


def _key_metrics(rows: list[dict[str, Any]], start: datetime, end: datetime,
                 max_fields: Optional[int], samples: Optional[int]) -> dict[str, Any]:
    """Ключевые метрики периода: источники, типы payload и поля со статистикой."""
    fields_limit = config.AGGREGATION_MAX_FIELDS if max_fields is None else int(max_fields)
    samples_limit = config.AGGREGATION_SAMPLES if samples is None else int(samples)
    sources: dict[str, int] = {}
    payload_types = {"list": 0, "dict": 0, "scalar": 0}
    values: dict[str, list[Any]] = {}
    for row in rows:
        row_name = str(row.get("name") or DEFAULT_SUMMARY_NAME)
        sources[row_name] = sources.get(row_name, 0) + 1
        payload = row.get("payload")
        payload_types[_payload_kind(payload)] += 1
        flatten_payload(row_name, payload, values)
    numeric, categorical = _split_fields(values, fields_limit, samples_limit)
    return {
        "period_seconds": int((end - start).total_seconds()),
        "sources": sources,
        "numeric": numeric,
        "categorical": categorical,
        "payload_types": payload_types,
    }


def _split_fields(values: dict[str, list[Any]], max_fields: int,
                  samples: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Делит поля на числовые (статистика) и категориальные (уникальные значения)."""
    numeric: dict[str, Any] = {}
    categorical: dict[str, Any] = {}
    for field in sorted(values)[:max_fields]:
        items = values[field]
        numbers = [item for item in items if _is_number(item)]
        if numbers and len(numbers) == len(items):
            numeric[field] = {
                "count": len(numbers),
                "avg": round(sum(numbers) / len(numbers), 2),
                "min": min(numbers),
                "max": max(numbers),
            }
            continue
        texts = [str(item).strip() for item in items if str(item).strip()]
        if not texts:
            continue
        unique = sorted(set(texts))
        categorical[field] = {
            "unique": len(unique),
            "samples": [_clip(item) for item in unique[:samples]],
        }
    return numeric, categorical


def _payload_kind(payload: Any) -> str:
    """Вид payload записи: список, объект или скаляр."""
    if isinstance(payload, list):
        return "list"
    if isinstance(payload, dict):
        return "dict"
    return "scalar"


def _is_number(value: Any) -> bool:
    """Число ли значение (``bool`` числом не считается: он подкласс ``int``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _period_text(start: datetime, end: datetime) -> str:
    """Период одной строкой: у одного дня конец печатается только временем."""
    head = start.strftime("%Y-%m-%d %H:%M:%S")
    tail = (end.strftime("%H:%M:%S") if start.date() == end.date()
            else end.strftime("%Y-%m-%d %H:%M:%S"))
    return f"{head} — {tail}"


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Метка времени в UTC-aware (naive считаем UTC, как хранилище дня)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clip(text: str) -> str:
    """Обрезает пример значения (в сводке он иллюстрация, а не данные)."""
    return text if len(text) <= SAMPLE_MAX else text[:SAMPLE_MAX] + "…"


def _copy_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Копия метрик по секциям: правка ответа не меняет сохранённую сводку."""
    return {key: dict(value) if isinstance(value, dict) else value
            for key, value in (metrics or {}).items()}
