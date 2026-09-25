"""Инструмент ``aggregate`` (день 20): метрики, пропуски и порядок групп.

Проверяются правила, из-за которых отчёт по группам не врёт: ``count`` считает
записи, остальные метрики требуют числового поля, нечисловые значения пропускаются,
а группа без чисел не показывается вовсе. Порядок групп задан (значение по
убыванию, при равенстве — ключ по алфавиту) и применяется ДО обрезки по ``limit``.
"""
import pytest

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.data_server import aggregate


def _items():
    """Записи трёх групп: у двух есть числа, у третьей вместо числа текст."""
    return [
        {"status": "ok", "amount": 10},
        {"status": "ok", "amount": 5},
        {"status": "fail", "amount": 1},
        {"status": "skip", "amount": "нет данных"},
    ]


def test_count_is_the_default_metric():
    """Без метрики считается ``count``: число записей в каждой группе."""
    result = aggregate.aggregate(_items(), group_by="status")
    assert result["metric"] == "count"
    assert result["group_by"] == "status"
    assert result["groups"] == [
        {"key": "ok", "value": 2},
        {"key": "fail", "value": 1},
        {"key": "skip", "value": 1},
    ]
    assert result["count"] == 3


def test_empty_group_by_makes_a_single_group():
    """Пустая группировка — одна группа с ключом ``все`` и всеми записями."""
    result = aggregate.aggregate(_items())
    assert result["groups"] == [{"key": "все", "value": 4}]
    assert result["count"] == 1


@pytest.mark.parametrize("metric,expected", [
    ("count", 2),
    ("sum", 15.0),
    ("avg", 7.5),
    ("min", 5.0),
    ("max", 10.0),
])
def test_metrics_use_the_value_field(metric, expected):
    """``sum``/``avg``/``min``/``max`` считаются по числам поля ``value_field``."""
    items = [{"status": "ok", "amount": 10}, {"status": "ok", "amount": 5}]
    result = aggregate.aggregate(items, group_by="status", metric=metric,
                                 value_field="amount")
    assert result["groups"][0]["value"] == expected
    assert result["metric"] == metric


def test_average_is_rounded_to_two_digits():
    """Среднее округляется до двух знаков: отчёт печатает готовое число."""
    items = [{"amount": 10}, {"amount": 5}, {"amount": 1}]
    result = aggregate.aggregate(items, metric="avg", value_field="amount")
    assert result["groups"][0]["value"] == 5.33


def test_non_numeric_values_are_skipped():
    """Нечисловые значения поля пропускаются, а не считаются нулём."""
    items = [{"amount": 4}, {"amount": "5"}, {"amount": None},
             {"amount": True}, {"amount": 3.5}]
    result = aggregate.aggregate(items, metric="sum", value_field="amount")
    assert result["groups"][0]["value"] == 7.5


def test_group_without_numbers_is_dropped():
    """Группа, где нет ни одного числа, в ответ не попадает."""
    result = aggregate.aggregate(_items(), group_by="status", metric="sum",
                                 value_field="amount")
    assert [group["key"] for group in result["groups"]] == ["ok", "fail"]
    assert result["count"] == 2


@pytest.mark.parametrize("metric", ["sum", "avg", "min", "max"])
def test_value_field_is_mandatory_for_numeric_metrics(metric):
    """Метрика по числам без ``value_field`` — ошибка с текстом метрики."""
    with pytest.raises(ToolError) as excinfo:
        aggregate.aggregate(_items(), metric=metric)
    assert f"«{metric}» требует value_field" in str(excinfo.value)


def test_count_does_not_need_a_value_field():
    """``count`` считает записи и без ``value_field``."""
    result = aggregate.aggregate(_items(), metric="count")
    assert result["groups"][0]["value"] == 4


def test_unknown_metric_is_a_tool_error():
    """Неизвестная метрика — ошибка с перечнем допустимых."""
    with pytest.raises(ToolError) as excinfo:
        aggregate.aggregate(_items(), metric="median")
    message = str(excinfo.value)
    assert "«median»" in message and "не поддержана" in message
    assert "count, sum, avg, min, max" in message


def test_groups_are_sorted_then_limited():
    """Сортировка (значение вниз, при равенстве ключ по алфавиту) идёт до обрезки."""
    items = [{"g": "a", "amount": 1}, {"g": "b", "amount": 1},
             {"g": "c", "amount": 3}, {"g": "d", "amount": 2}]
    result = aggregate.aggregate(items, group_by="g", metric="sum",
                                 value_field="amount", limit=2)
    assert [group["key"] for group in result["groups"]] == ["c", "d"]
    assert result["count"] == 2
    full = aggregate.aggregate(items, group_by="g", metric="sum", value_field="amount")
    assert [group["key"] for group in full["groups"]] == ["c", "d", "a", "b"]


def test_missing_group_field_lands_in_the_empty_key():
    """Запись без поля группировки попадает в группу с пустым ключом."""
    items = [{"g": "a"}, {"other": 1}]
    result = aggregate.aggregate(items, group_by="g")
    # При равном значении порядок алфавитный, а пустой ключ идёт первым.
    assert [group["key"] for group in result["groups"]] == ["", "a"]


def test_non_dict_items_are_ignored():
    """Записи не-словари группировать не по чему: они пропускаются."""
    result = aggregate.aggregate([{"g": "a"}, "строка", 42], group_by="g")
    assert result["groups"] == [{"key": "a", "value": 1}]


def test_empty_items_give_empty_groups():
    """Пустой список — пустой результат, а не ошибка."""
    result = aggregate.aggregate([])
    assert result["groups"] == [] and result["count"] == 0
