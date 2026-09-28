"""Инструмент ``aggregate``: группировка записей и метрика по группе.

Одна группировка и одна метрика за вызов: ``count`` считает записи, ``sum``/
``avg``/``min``/``max`` — числа поля ``value_field``. Нечисловые значения поля
пропускаются, группа без чисел в ответ не попадает: показать нуль вместо «данных
нет» значило бы соврать в отчёте.

Порядок групп задан: значение по убыванию, при равенстве — ключ по алфавиту, и
только потом обрезка по ``limit``. Так «топ групп» — это действительно топ, а не
первые попавшиеся записи.
"""
from __future__ import annotations

from typing import Any, Dict, List

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.data_server import config
from mcp_servers.data_server.schemas import AggregateGroup, AggregateResult

#: Ключ единственной группы, когда группировка не задана.
ALL_GROUP_KEY = "все"


def clamp_limit(limit) -> int:
    """Сколько групп вернуть: в границах 1..``ITEMS_MAX``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = config.AGGREGATE_LIMIT_DEFAULT
    return max(1, min(value, config.ITEMS_MAX))


def number_of(value: Any) -> float | None:
    """Число из значения поля: ``int``/``float``, а нечисловое — ``None``.

    ``bool`` числом не считается: ``True`` в JSON — это признак, а не количество,
    и складывать его с суммами нельзя.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def metric_value(bucket: List[Dict[str, Any]], metric: str,
                 value_field: str) -> float | int | None:
    """Значение метрики по группе: ``None``, если в группе нет числовых значений."""
    if metric == "count":
        return len(bucket)
    numbers = [number for number in
               (number_of(item.get(value_field)) for item in bucket)
               if number is not None]
    if not numbers:
        return None
    if metric == "sum":
        return round(sum(numbers), 2)
    if metric == "avg":
        return round(sum(numbers) / len(numbers), 2)
    if metric == "min":
        return round(min(numbers), 2)
    return round(max(numbers), 2)


def aggregate(items: List[Dict[str, Any]], group_by: str = "", metric: str = "count",
              value_field: str = "",
              limit: int = config.AGGREGATE_LIMIT_DEFAULT) -> AggregateResult:
    """Группирует записи и считает метрику по каждой группе.

    Параметры: items — список записей (словарей); group_by — имя поля группировки
    (пустая строка — одна группа с ключом ``все``); metric — ``count`` (число
    записей, по умолчанию), ``sum``, ``avg``, ``min`` или ``max``; value_field —
    имя числового поля для всех метрик кроме ``count`` (для ``count`` не нужен);
    limit — сколько групп вернуть (1..200, по умолчанию 20). Пример:
    aggregate(items=items, group_by="status", metric="avg", value_field="amount",
    limit=5).

    Возвращает объект с полями groups (ключ и значение, по убыванию значения, при
    равенстве — по алфавиту ключа; значения округлены до двух знаков), count
    (сколько групп вернулось), metric и group_by (как переданы). Нечисловые
    значения поля пропускаются, а группа без чисел в ответ не попадает.

    Неизвестная метрика и отсутствие ``value_field`` для ``sum``/``avg``/``min``/
    ``max`` — ошибка инструмента с перечнем допустимого.
    """
    metric_used = str(metric or "").strip().lower() or "count"
    if metric_used not in config.AGGREGATE_METRICS:
        raise ToolError(
            f"Метрика «{metric}» не поддержана. Допустимы: "
            + ", ".join(config.AGGREGATE_METRICS)
        )
    if metric_used != "count" and not str(value_field or "").strip():
        raise ToolError(f"Метрика «{metric}» требует value_field")

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = ALL_GROUP_KEY if not str(group_by or "").strip() else str(item.get(group_by, ""))
        buckets.setdefault(key, []).append(item)

    groups: List[AggregateGroup] = []
    for key, bucket in buckets.items():
        value = metric_value(bucket, metric_used, value_field)
        if value is None:
            continue
        groups.append(AggregateGroup(key=key, value=value))
    groups.sort(key=lambda group: (-float(group["value"]), group["key"]))

    selected = groups[:clamp_limit(limit)]
    return AggregateResult(
        groups=selected,
        count=len(selected),
        metric=metric_used,
        group_by="" if group_by is None else str(group_by),
    )
