"""Тесты детерминированных правил проверки инвариантов (день 14).

Правила — первый слой ``InvariantChecker`` и единственный, который работает без
сети, поэтому проверяется он отдельно и без БД: привязка правила к описанию
инварианта (``gate``), срабатывание на тексте (``signal``), снятие нарушения
согласием пользователя (``exclude``) и форма записи о нарушении.
"""

from __future__ import annotations

import pytest

from backend.domain.demo_invariants import DEMO_INVARIANTS
from backend.domain.invariant_rules import deterministic_violations

DEMO_BY_CATEGORY = {item["category"]: dict(item) for item in DEMO_INVARIANTS}

ARCHITECTURE = DEMO_BY_CATEGORY["architecture"]
TECH_DECISIONS = DEMO_BY_CATEGORY["tech_decisions"]
STACK_CONSTRAINTS = DEMO_BY_CATEGORY["stack_constraints"]
BUSINESS_RULES = DEMO_BY_CATEGORY["business_rules"]

# «Признак инварианта» и текст, который его нарушает: правила-термины работают,
# только когда средство упомянуто и в описании инварианта, и в проверяемом тексте.
VIOLATING_TEXTS = (
    ("architecture", "Давай перепишем бэкенд на Flask"),
    ("architecture", "Предлагаю Django вместо FastAPI"),
    ("architecture", "Поднимем Bottle как основу сервиса"),
    ("architecture", "Развернём Tornado за прокси"),
    ("tech_decisions", "Состояние задачи будем держать в Redis"),
    ("tech_decisions", "Кэш на memcached"),
    ("tech_decisions", "Переедем на MongoDB"),
    ("tech_decisions", "Очередь через kafka"),
    ("stack_constraints", "Сделаем фронтенд на JavaScript"),
    ("stack_constraints", "Напишем сервис на Node.js"),
    ("stack_constraints", "Типизируем проект через TypeScript"),
    ("stack_constraints", "Интерфейс на React"),
    ("stack_constraints", "Компонент на Vue.js"),
    ("stack_constraints", "Соберём на Angular"),
)


@pytest.mark.parametrize("category, text", VIOLATING_TEXTS)
def test_term_of_invariant_in_text_is_a_violation(category, text) -> None:
    """Упоминание запрещённого инвариантом средства — нарушение его категории."""
    violations = deterministic_violations(text, DEMO_BY_CATEGORY[category])

    assert len(violations) == 1
    assert violations[0]["name"] == DEMO_BY_CATEGORY[category]["name"]
    assert violations[0]["category"] == category
    assert violations[0]["severity"] == DEMO_BY_CATEGORY[category]["severity"]


def test_allowed_means_are_not_violations() -> None:
    """Разрешённые средства (FastAPI, SQLite, Python) нарушением не считаются."""
    text = "Добавь эндпоинт /health в FastAPI, данные в SQLite, всё на Python"

    for invariant in DEMO_INVARIANTS:
        assert deterministic_violations(text, invariant) == []


def test_paid_service_without_consent_is_a_violation() -> None:
    """Платный вариант без согласия пользователя нарушает бизнес-правило."""
    violations = deterministic_violations("API на платном тарифе", BUSINESS_RULES)

    assert len(violations) == 1
    assert violations[0]["severity"] == "soft"


def test_paid_service_with_consent_is_not_a_violation() -> None:
    """Утвердительно выраженное согласие снимает нарушение (работает ``exclude``)."""
    text = "API на платном тарифе, если пользователь согласен"

    assert deterministic_violations(text, BUSINESS_RULES) == []


def test_denied_consent_is_a_violation() -> None:
    """Отрицание согласия («не нужно») согласием не считается."""
    text = "Предложи решение на платном API, согласие пользователя не нужно"

    violations = deterministic_violations(text, BUSINESS_RULES)

    assert len(violations) == 1
    assert "платный вариант" in violations[0]["reason"]


def test_rule_needs_the_term_in_the_invariant_description() -> None:
    """Одно и то же слово в тексте — не нарушение чужого по смыслу инварианта."""
    text = "Давай перепишем бэкенд на Flask"

    assert deterministic_violations(text, STACK_CONSTRAINTS) == []
    assert deterministic_violations(text, TECH_DECISIONS) == []


@pytest.mark.parametrize("text", ["flasks", "djangoize", "redisign", "компонент reactjs"])
def test_word_boundaries_prevent_substring_matches(text) -> None:
    """Подстрока внутри слова нарушением не считается: правило ищет слово целиком."""
    assert deterministic_violations(text, ARCHITECTURE) == []
    assert deterministic_violations(text, TECH_DECISIONS) == []
    assert deterministic_violations(text, STACK_CONSTRAINTS) == []


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_text_has_no_violations(text) -> None:
    """Пустой текст проверять нечего — обращений к правилам нет."""
    assert deterministic_violations(text, ARCHITECTURE) == []


def test_invariant_without_description_has_no_violations() -> None:
    """Инвариант без описания проверить нельзя: правило не к чему привязать."""
    assert deterministic_violations("Flask", {"name": "Без описания", "category": "architecture",
                                              "severity": "hard", "description": ""}) == []


def test_violation_shape_is_api_ready() -> None:
    """Запись о нарушении готова к выдаче в API и к подстановке в текст отказа."""
    violation = deterministic_violations("Давай перепишем бэкенд на Flask", ARCHITECTURE)[0]

    assert violation["source"] == "deterministic"
    assert violation["name"] == ARCHITECTURE["name"]
    assert violation["category"] == ARCHITECTURE["category"]
    assert violation["severity"] == ARCHITECTURE["severity"]
    assert "Flask" in violation["reason"]
    assert ARCHITECTURE["name"] in violation["reason"]
