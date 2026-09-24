"""Значения инвариантов проекта дня 14: категории, важность и вердикты.

Модуль намеренно не знает ни про SQLAlchemy, ни про FastAPI, ни про Streamlit:
здесь только перечисления и чистые функции, поэтому валидация значений
инварианта проверяется модульными тестами без БД и без сети (конвенция
AGENTS.md).

Что здесь есть:

- ``InvariantCategory`` — категория правила (``invariants.category``): четыре
  значения, покрывающие архитектуру, технические решения, ограничения стека и
  бизнес-правила проекта;
- ``InvariantSeverity`` — жёсткость правила: ``hard`` (нарушение → отказ) и
  ``soft`` (нарушение → предупреждение, но решение предлагается);
- ``AVAILABLE_CATEGORIES`` / ``AVAILABLE_SEVERITIES`` — готовые кортежи значений
  для валидации API и селекторов интерфейса;
- ``CATEGORY_LABELS`` / ``SEVERITY_LABELS`` — человекочитаемые подписи (в UI и в
  отчёте не нужен отдельный маппинг);
- ``VERDICT_ALLOWED`` / ``VERDICT_WARNING`` / ``VERDICT_REFUSAL`` — исход
  проверки текста против инвариантов; одни и те же строки использует сервис
  проверки, агент, API и интерфейс;
- ``category_from_value`` / ``severity_from_value`` — перевод «строка → член
  Enum»; неизвестное значение — явная ``InvariantValueError``, а не «тихое»
  значение по умолчанию (см. ``strategies.py``, ``task_fsm.py``).

Детерминированные правила проверки живут в
``backend/domain/invariant_rules.py``, тексты для промпта и отказа — в
``backend/domain/invariant_prompt.py``; этот модуль — общий словарь значений для
них.
"""
from enum import Enum
from typing import Dict, Tuple

__all__ = [
    "AVAILABLE_CATEGORIES",
    "AVAILABLE_SEVERITIES",
    "CATEGORY_LABELS",
    "SEVERITY_LABELS",
    "VERDICT_ALLOWED",
    "VERDICT_REFUSAL",
    "VERDICT_WARNING",
    "InvariantCategory",
    "InvariantSeverity",
    "InvariantValueError",
    "category_from_value",
    "severity_from_value",
]


class InvariantValueError(Exception):
    """Невалидное значение инварианта (неизвестная категория или важность)."""


class InvariantCategory(str, Enum):
    """Категория инварианта (поле ``invariants.category``)."""

    ARCHITECTURE = "architecture"
    TECH_DECISIONS = "tech_decisions"
    STACK_CONSTRAINTS = "stack_constraints"
    BUSINESS_RULES = "business_rules"


class InvariantSeverity(str, Enum):
    """Жёсткость инварианта: hard — отказ, soft — предупреждение."""

    HARD = "hard"
    SOFT = "soft"


# Значения для валидации тела запроса и для селекторов интерфейса.
AVAILABLE_CATEGORIES: Tuple[str, ...] = tuple(item.value for item in InvariantCategory)
AVAILABLE_SEVERITIES: Tuple[str, ...] = tuple(item.value for item in InvariantSeverity)

# Подписи для интерфейса и отчёта: «значение из БД → что видит человек».
CATEGORY_LABELS: Dict[str, str] = {
    InvariantCategory.ARCHITECTURE.value: "архитектура",
    InvariantCategory.TECH_DECISIONS.value: "технические решения",
    InvariantCategory.STACK_CONSTRAINTS.value: "ограничения стека",
    InvariantCategory.BUSINESS_RULES.value: "бизнес-правила",
}

SEVERITY_LABELS: Dict[str, str] = {
    InvariantSeverity.HARD.value: "hard — отказ при нарушении",
    InvariantSeverity.SOFT.value: "soft — предупреждение",
}

# Исход проверки текста: нарушений нет / только soft / есть hard.
VERDICT_ALLOWED = "allowed"
VERDICT_WARNING = "warning"
VERDICT_REFUSAL = "refusal"

# Таблицы «значение → член Enum» для восстановления из БД/API.
CATEGORY_BY_VALUE: Dict[str, InvariantCategory] = {
    item.value: item for item in InvariantCategory
}
SEVERITY_BY_VALUE: Dict[str, InvariantSeverity] = {
    item.value: item for item in InvariantSeverity
}


def category_from_value(value: str) -> InvariantCategory:
    """Категория инварианта по строке из БД/API; неизвестная — ``InvariantValueError``."""
    try:
        return CATEGORY_BY_VALUE[value]
    except KeyError:
        raise InvariantValueError(
            f"Неизвестная категория инварианта: {value!r}. "
            f"Допустимые: {', '.join(AVAILABLE_CATEGORIES)}"
        ) from None


def severity_from_value(value: str) -> InvariantSeverity:
    """Важность инварианта по строке из БД/API; неизвестная — ``InvariantValueError``."""
    try:
        return SEVERITY_BY_VALUE[value]
    except KeyError:
        raise InvariantValueError(
            f"Неизвестная важность инварианта: {value!r}. "
            f"Допустимые: {', '.join(AVAILABLE_SEVERITIES)}"
        ) from None
