"""Инструмент ``filter_by_date`` (день 20): разбор дат, границы и ``skipped``.

Проверяются правила отбора: ISO-8601 и ``ДД.ММ.ГГГГ`` понимаются, границы
включительные, пустая граница — без ограничения, а запись без разобранной даты
попадает в счётчик ``skipped``, а не превращается в ошибку всего вызова: в лентах
источников такие записи есть всегда, и терять из-за них остальные нельзя.
"""
from datetime import datetime, timezone

import pytest

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.data_server import dates


@pytest.mark.parametrize("value,expected", [
    ("2026-01-02", datetime(2026, 1, 2)),
    ("2026-01-02T03:04:05", datetime(2026, 1, 2, 3, 4, 5)),
    ("02.01.2026", datetime(2026, 1, 2)),
    ("02.01.2026 03:04", datetime(2026, 1, 2, 3, 4)),
    ("2026-01-02T03:04:05Z", datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)),
])
def test_parse_moment_understands_day_formats(value, expected):
    """Разбираются ISO-8601 (в том числе с ``Z``) и формат ``ДД.ММ.ГГГГ``."""
    assert dates.parse_moment(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "не дата", "02/01/2026", 42, True])
def test_parse_moment_returns_none_for_other_values(value):
    """Нераспознанное значение датой не считается: ``None``, а не догадка."""
    assert dates.parse_moment(value) is None


def test_parse_moment_passes_datetime_through():
    """Готовый ``datetime`` возвращается как есть, без повторного разбора."""
    moment = datetime(2026, 1, 2, 3, 4, 5)
    assert dates.parse_moment(moment) is moment


def _items():
    """Записи с датами в двух форматах, без даты и с мусором вместо даты."""
    return [
        {"id": 1, "created_at": "2026-01-02"},
        {"id": 2, "created_at": "02.01.2026"},
        {"id": 3, "created_at": "2025-12-31"},
        {"id": 4},
        {"id": 5, "created_at": "не дата"},
        "совсем не запись",
    ]


def test_bounds_are_inclusive():
    """Записи ровно на границах попадают в результат: границы включительные."""
    result = dates.filter_by_date(_items(), since="2026-01-02", until="02.01.2026")
    assert [item["id"] for item in result["items"]] == [1, 2]
    assert result["count"] == 2


def test_records_without_a_date_go_to_skipped():
    """Записи без даты и с мусором в поле даты считаются в ``skipped``, а не падают."""
    result = dates.filter_by_date(_items(), since="2026-01-01")
    assert result["skipped"] == 3
    assert result["count"] == 2


def test_empty_bounds_mean_no_limit():
    """Пустые границы отбора не ограничивают: возвращаются все записи с датой."""
    result = dates.filter_by_date(_items())
    assert [item["id"] for item in result["items"]] == [1, 2, 3]
    assert result["count"] == 3 and result["skipped"] == 3


def test_unparsable_bound_is_a_tool_error():
    """Неразобранная непустая граница — ошибка с текстом границы и подсказкой."""
    with pytest.raises(ToolError) as excinfo:
        dates.filter_by_date(_items(), since="вчера")
    message = str(excinfo.value)
    assert "«вчера»" in message and "не разобрана" in message


def test_unparsable_until_bound_is_a_tool_error():
    """Верхняя граница проверяется так же, как нижняя."""
    with pytest.raises(ToolError, match="31/12/2026"):
        dates.filter_by_date(_items(), until="31/12/2026")


@pytest.mark.parametrize("limit,expected", [(0, 1), (10_000, 3)])
def test_limit_is_clamped(limit, expected):
    """Границы ``limit``: ноль поднимается до единицы, большое значение не режет выборку."""
    result = dates.filter_by_date(_items(), limit=limit)
    assert result["count"] == len(result["items"]) == expected


def test_limit_keeps_the_original_order():
    """``limit`` обрезает хвост, порядок записей исходный."""
    result = dates.filter_by_date(_items(), limit=2)
    assert [item["id"] for item in result["items"]] == [1, 2]


def test_response_echoes_field_and_bounds():
    """Поле и границы возвращаются как переданы: отчёт печатает именно их."""
    items = [{"id": 1, "moment": "02.01.2026 10:00"}]
    result = dates.filter_by_date(items, field="moment", since="02.01.2026",
                                  until="02.01.2026 23:59")
    assert result["field"] == "moment"
    assert result["since"] == "02.01.2026"
    assert result["until"] == "02.01.2026 23:59"
    assert result["count"] == 1


def test_aware_and_naive_moments_are_comparable():
    """Запись с ``Z`` и граница без зоны сравниваются: смещение приводится к UTC."""
    items = [{"created_at": "2026-01-02T00:00:00Z"}]
    result = dates.filter_by_date(items, since="2026-01-02", until="2026-01-03")
    assert result["count"] == 1
