"""Тесты значений инвариантов (день 14, ``backend/domain/invariant_values.py``).

Проверяется контракт перечислений: любое допустимое значение превращается в член
Enum, неизвестное — в явную ``InvariantValueError`` (а не в «тихое» значение по
умолчанию), а словари подписей покрывают все члены — иначе в интерфейсе и в
отчёте появился бы пустой ярлык.
"""

from __future__ import annotations

import pytest

from backend.domain.invariant_values import (
    AVAILABLE_CATEGORIES,
    AVAILABLE_SEVERITIES,
    CATEGORY_LABELS,
    SEVERITY_LABELS,
    VERDICT_ALLOWED,
    VERDICT_REFUSAL,
    VERDICT_WARNING,
    InvariantCategory,
    InvariantSeverity,
    InvariantValueError,
    category_from_value,
    severity_from_value,
)

CATEGORY_VALUES = ("architecture", "tech_decisions", "stack_constraints", "business_rules")
SEVERITY_VALUES = ("hard", "soft")


@pytest.mark.parametrize("value", CATEGORY_VALUES)
def test_category_is_translated_to_enum_member(value) -> None:
    """Строка из БД/API превращается в член Enum без маппинга в коде."""
    assert category_from_value(value) is InvariantCategory(value)


@pytest.mark.parametrize("value", SEVERITY_VALUES)
def test_severity_is_translated_to_enum_member(value) -> None:
    """Важность из БД/API превращается в член Enum."""
    assert severity_from_value(value) is InvariantSeverity(value)


def test_available_values_match_enum_members() -> None:
    """Списки для валидации API и селекторов интерфейса не расходятся с Enum."""
    assert AVAILABLE_CATEGORIES == tuple(item.value for item in InvariantCategory)
    assert AVAILABLE_SEVERITIES == tuple(item.value for item in InvariantSeverity)


@pytest.mark.parametrize("value", ["flask", "архитектура", "", "ARCHITECTURE"])
def test_unknown_category_raises_with_value(value) -> None:
    """Неизвестная категория — доменная ошибка с указанием значения."""
    with pytest.raises(InvariantValueError) as excinfo:
        category_from_value(value)

    assert repr(value) in str(excinfo.value)


@pytest.mark.parametrize("value", ["medium", "HARD", "жёсткий", ""])
def test_unknown_severity_raises_with_value(value) -> None:
    """Неизвестная важность — доменная ошибка с указанием значения."""
    with pytest.raises(InvariantValueError) as excinfo:
        severity_from_value(value)

    assert repr(value) in str(excinfo.value)


def test_labels_cover_every_value() -> None:
    """У каждой категории и важности есть непустая подпись для UI и отчёта."""
    assert set(CATEGORY_LABELS) == set(AVAILABLE_CATEGORIES)
    assert set(SEVERITY_LABELS) == set(AVAILABLE_SEVERITIES)
    assert all(CATEGORY_LABELS.values())
    assert all(SEVERITY_LABELS.values())


def test_verdicts_are_distinct_non_empty_strings() -> None:
    """Вердикты — три разных строки: их сравнивают и API, и агент, и интерфейс."""
    verdicts = (VERDICT_ALLOWED, VERDICT_WARNING, VERDICT_REFUSAL)

    assert all(verdicts)
    assert len(set(verdicts)) == len(verdicts)
