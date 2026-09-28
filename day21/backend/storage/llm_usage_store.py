"""Хранилище журнала расходов на LLM в SQLite (день 21): ``LLMUsageStore``.

Здесь живёт таблица ``llm_usage``: запись строки на каждый запрос к модели, чтение
свежих строк (их показывает вкладка «Расходы» сразу после хода), выборка окна
периода и агрегированная статистика для графиков и отчёта об оптимизации. Формулы
денег и скидок — в домене (``domain/llm_cost.py``), здесь их нет: хранилище только
складывает уже посчитанные значения, поэтому проверяется без сети и без модели.

Зачем окно периода считается здесь, а не в SQL: набор периодов — данные
(``config.LLM_USAGE_PERIODS``), и одна функция переводит ключ в границу времени для
всех читателей; разложенная по сервисам арифметика «сколько дней в месяце» разошлась
бы между вкладкой, отчётом и тестами.

Свежесть строк: ``recent`` идёт от новых к старым (журнал читают «что только что
случилось»), ``rows`` — от старых к новым (по ним строится график «расход по дням»,
и перестановка порядка в одном из чтений сломала бы другого потребителя).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

from ..core import config
from ..models.llm_usage import LLMUsage
from . import database
from .llm_usage_rows import llm_usage_dict

__all__ = ["LLMUsageStore"]


def _resolve_period(period: Optional[str]) -> tuple[str, int]:
    """Ключ периода и число дней его окна (``None`` — период по умолчанию).

    Неизвестный ключ — ошибка, а не пустая выборка: молчаливое «0 записей» на
    опечатку в параметре выглядело бы в интерфейсе как пустой журнал, и причину
    искали бы в базе, а не в запросе.
    """
    key = config.LLM_USAGE_PERIOD_DEFAULT if period is None else str(period)
    if key not in config.LLM_USAGE_PERIODS:
        allowed = ", ".join(sorted(config.LLM_USAGE_PERIODS))
        raise ValueError(f"неизвестный период {key!r}; допустимые: {allowed}")
    return key, int(config.LLM_USAGE_PERIODS[key])


def _cache_hit_percent(hit: int, miss: int, prompt: int) -> float:
    """Доля ввода, попавшая в кэш контекста (проценты, округление до 0.1).

    Знаменатель — размеченный ввод: попадание плюс промах. У старых и подменённых
    записей разметки нет (оба поля нули), но ``prompt_tokens`` заполнен — тогда
    считаем по нему, иначе у всех таких строк выходило бы 0.0 «неизвестно» вместо
    честного нуля процентов. Пустой ввод — 0.0: делить не на что.
    """
    denominator = hit + miss
    if denominator <= 0:
        denominator = prompt
    if denominator <= 0:
        return 0.0
    return round(hit / denominator * 100, 1)


def _group(rows: Sequence[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    """Свернуть строки по полю (модель или тип запроса) в одинаковые корзины.

    Ключи сортируются: порядок вывода не должен зависеть от порядка строк в БД,
    иначе график и отчёт «дрожали» бы между запусками при тех же данных.
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(field) or "")
        bucket = groups.setdefault(key, {
            "requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "cost_estimate": 0.0, "cache_hit_tokens": 0, "cache_miss_tokens": 0,
        })
        bucket["requests"] += 1
        bucket["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
        bucket["completion_tokens"] += int(row.get("completion_tokens") or 0)
        bucket["cache_hit_tokens"] += int(row.get("cache_hit_tokens") or 0)
        bucket["cache_miss_tokens"] += int(row.get("cache_miss_tokens") or 0)
        bucket["cost_estimate"] = round(
            bucket["cost_estimate"] + float(row.get("cost_estimate") or 0.0), 6)
    return {key: groups[key] for key in sorted(groups)}


def _daily(rows: Sequence[dict[str, Any]]) -> List[dict[str, Any]]:
    """Расход по календарным дням (UTC) по возрастанию даты — данные графика.

    Дата берётся из ISO-метки строки: окно периода уже отфильтровано по UTC, и
    повторное приведение часового пояса здесь дало бы день, не совпадающий с окном
    на границе суток.
    """
    days: dict[str, dict[str, Any]] = {}
    for row in rows:
        date = str(row.get("timestamp") or "")[:10]
        bucket = days.setdefault(date, {
            "date": date, "requests": 0, "total_tokens": 0,
            "cache_hit_tokens": 0, "cache_miss_tokens": 0, "cost_estimate": 0.0,
        })
        bucket["requests"] += 1
        bucket["total_tokens"] += (int(row.get("prompt_tokens") or 0)
                                  + int(row.get("completion_tokens") or 0))
        bucket["cache_hit_tokens"] += int(row.get("cache_hit_tokens") or 0)
        bucket["cache_miss_tokens"] += int(row.get("cache_miss_tokens") or 0)
        bucket["cost_estimate"] = round(
            bucket["cost_estimate"] + float(row.get("cost_estimate") or 0.0), 6)
    return [days[key] for key in sorted(days)]


class LLMUsageStore:
    """Строки ``llm_usage``: запись запроса и агрегаты расхода за период."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``PipelineStore``)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def add(self, *, model: str, request_type: str, prompt_tokens: int = 0,
            completion_tokens: int = 0, cache_hit_tokens: int = 0,
            cache_miss_tokens: int = 0, cost_estimate: float = 0.0,
            agent_id: Optional[str] = None,
            timestamp: Optional[datetime] = None) -> dict[str, Any]:
        """Пишет строку журнала и возвращает её как словарь.

        Метка времени по умолчанию — момент записи: подменённые вызовы в тестах не
        задают свой момент, а журнал без времени бесполезен. Момент приходит
        аргументом для восстановления истории и для проверки окон периода.

        Строка возвращается целиком (а не только номер), потому что пишущий код тут
        же показывает её в логе хода: повторное чтение той же строки было бы лишним
        запросом.
        """
        with self.session() as session:
            row = LLMUsage(
                agent_id=agent_id,
                timestamp=timestamp or datetime.now(timezone.utc),
                model=model,
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                cache_hit_tokens=int(cache_hit_tokens),
                cache_miss_tokens=int(cache_miss_tokens),
                cost_estimate=float(cost_estimate),
                request_type=request_type,
            )
            session.add(row)
            session.flush()
            record = llm_usage_dict(row)
            session.commit()
            return record

    def recent(self, agent_id: Optional[str] = None,
               limit: Optional[int] = None) -> List[dict[str, Any]]:
        """Свежие строки журнала: ``agent_id`` фильтрует, ``None`` — весь журнал.

        Период здесь не применяется намеренно: «последние запросы» — это взгляд на
        конец журнала, а не на окно статистики; иначе после смены периода вкладка
        «Расходы» теряла бы только что прошедший ход.

        Строки одного момента упорядочены по id: у запросов, записанных подряд
        (пакетная обработка), метка времени совпадает, и порядок иначе был бы
        случайным.
        """
        size = config.LLM_USAGE_LIMIT if limit is None else max(1, int(limit))
        with self.session() as session:
            query = session.query(LLMUsage)
            if agent_id is not None:
                query = query.filter(LLMUsage.agent_id == agent_id)
            rows = (query.order_by(LLMUsage.timestamp.desc(), LLMUsage.id.desc())
                    .limit(size).all())
            return [llm_usage_dict(row) for row in rows]

    def rows(self, agent_id: Optional[str] = None,
             period: Optional[str] = None) -> List[dict[str, Any]]:
        """Все строки окна периода по возрастанию времени (график «по дням»).

        ``all`` (0 дней) — без ограничения по времени: сводка «за всё время» нужна
        отчёту, чтобы сравнить день 21 с суммой прошлых дней.
        """
        key, days = _resolve_period(period)
        with self.session() as session:
            query = session.query(LLMUsage)
            if agent_id is not None:
                query = query.filter(LLMUsage.agent_id == agent_id)
            if config.LLM_USAGE_PERIODS[key] > 0:
                since = datetime.now(timezone.utc) - timedelta(days=days)
                query = query.filter(LLMUsage.timestamp >= since)
            found = (query.order_by(LLMUsage.timestamp.asc(), LLMUsage.id.asc())
                     .all())
            return [llm_usage_dict(row) for row in found]

    def stats(self, agent_id: Optional[str] = None,
              period: Optional[str] = None) -> dict[str, Any]:
        """Сводка расхода окна: суммы, доля кэша, разрезы по модели и типу, дни.

        Пустой журнал — нули, а не ошибка: вкладка «Расходы» и отчёт рисуются
        всегда, и первый запуск не должен выглядеть поломкой.
        """
        key, _ = _resolve_period(period)
        rows = self.rows(agent_id=agent_id, period=key)
        prompt = sum(int(row.get("prompt_tokens") or 0) for row in rows)
        completion = sum(int(row.get("completion_tokens") or 0) for row in rows)
        hit = sum(int(row.get("cache_hit_tokens") or 0) for row in rows)
        miss = sum(int(row.get("cache_miss_tokens") or 0) for row in rows)
        cost = round(sum(float(row.get("cost_estimate") or 0.0) for row in rows), 6)
        return {
            "period": key,
            "requests": len(rows),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cache_hit_tokens": hit,
            "cache_miss_tokens": miss,
            "cache_hit_percent": _cache_hit_percent(hit, miss, prompt),
            "cost_estimate": cost,
            "by_model": _group(rows, "model"),
            "by_type": _group(rows, "request_type"),
            "daily": _daily(rows),
        }

    def agents(self) -> List[str]:
        """Имена агентов, встречающиеся в журнале (для фильтра вкладки «Расходы»).

        Пустой ``agent_id`` в список не попадает: это служебный вызов без агента, и
        вариант фильтра «без агента» в интерфейсе отдельного смысла не имеет.
        """
        with self.session() as session:
            rows = (session.query(LLMUsage.agent_id)
                    .filter(LLMUsage.agent_id.isnot(None)).distinct().all())
        return sorted({str(value) for (value,) in rows if value})
