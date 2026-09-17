"""Проверка текста на инварианты (день 14): правила, LLM и сбои.

Проверяется сервис ``InvariantChecker``: без инвариантов он не делает ничего (и
не зовёт модель), нарушения ищут правила, а LLM подключается только когда правила
молчат — по одному вызову на проверку. Сетевых обращений нет: клиент подменён
``FakeClient``, а сбои имитируются ``invariant_error``.
"""

from __future__ import annotations

import json

import pytest

from backend.domain.demo_invariants import DEMO_INVARIANTS
from backend.domain.invariant_values import VERDICT_ALLOWED, VERDICT_REFUSAL
from backend.services.invariant_checker import (
    INVARIANT_CHECK_SYSTEM_PROMPT,
    InvariantCheckResult,
    InvariantChecker,
    InvariantViolation,
)
from backend.storage.invariant_store import InvariantManager
from support import FakeClient, seed_demo_invariants, seed_invariant

FLASK_TEXT = "Давай перепишем бэкенд на Flask"
CLEAN_TEXT = "Добавь эндпоинт /health в FastAPI, данные в SQLite, всё на Python"
PAID_TEXT = "Предложи решение на платном API, согласие пользователя не нужно"


@pytest.fixture
def fake():
    """Фейковый клиент DeepSeek с ответом контролёра «нарушений нет»."""
    return FakeClient()


@pytest.fixture
def checker(session_factory, fake):
    """Контролёр на временной БД и подменённом клиенте."""
    return InvariantChecker(session_factory=session_factory, client_factory=lambda: fake)


# ---------- инвариантов нет ----------
def test_without_invariants_check_does_nothing(checker, fake) -> None:
    """Пустая таблица правил — проверки нет: ни вызовов, ни изменений поведения."""
    result = checker.check(CLEAN_TEXT)

    assert result.checked == []
    assert result.verdict == VERDICT_ALLOWED
    assert result.llm_used is False
    assert fake.calls == []


# ---------- детерминированный слой ----------
def test_rules_catch_hard_violation_without_llm(checker, fake, session_factory) -> None:
    """Нарушение hard-инварианта находят правила — в модель не идём."""
    seed_demo_invariants(session_factory)

    result = checker.check(FLASK_TEXT)

    assert result.verdict == VERDICT_REFUSAL
    assert result.llm_used is False
    assert fake.invariant_calls == []
    assert result.violations[0].source == "deterministic"
    assert result.violations[0].name == "Только FastAPI и Streamlit"


def test_rules_catch_soft_violation(checker, session_factory) -> None:
    """Soft-нарушение тоже ловится правилами (платный вариант без согласия)."""
    seed_demo_invariants(session_factory)

    result = checker.check(PAID_TEXT)

    assert result.verdict == "warning"
    assert result.violations[0].severity == "soft"
    assert result.llm_used is False


def test_checked_lists_names_of_active_invariants(checker, session_factory) -> None:
    """В отчёте видны имена всех правил, против которых проверяли текст."""
    seeded = seed_demo_invariants(session_factory)
    disabled = seeded[0]
    InvariantManager(session_factory=session_factory).deactivate_invariant(disabled["id"])

    result = checker.check(CLEAN_TEXT, use_llm=False)

    assert disabled["name"] not in result.checked
    assert set(result.checked) == {item["name"] for item in seeded} - {disabled["name"]}
    assert len(result.checked) == len(set(result.checked))


# ---------- LLM-слой ----------
def test_clean_text_goes_to_llm_with_checker_prompt(checker, fake, session_factory) -> None:
    """Правила молчат — модель получает промпт контролёра и список инвариантов."""
    seeded = seed_demo_invariants(session_factory)

    result = checker.check(CLEAN_TEXT)

    assert result.verdict == VERDICT_ALLOWED
    assert result.llm_used is True
    assert len(fake.invariant_calls) == 1
    call = fake.invariant_calls[0]
    assert call["messages"][0]["content"] == INVARIANT_CHECK_SYSTEM_PROMPT
    assert CLEAN_TEXT in call["messages"][1]["content"]
    assert len(result.checked) == len(seeded)


def test_use_llm_false_skips_model(checker, fake, session_factory) -> None:
    """``use_llm=False`` — только правила: так работает проверка запроса и отчёт."""
    seed_demo_invariants(session_factory)

    result = checker.check(CLEAN_TEXT, use_llm=False)

    assert result.verdict == VERDICT_ALLOWED
    assert result.llm_used is False
    assert fake.calls == []


def test_llm_violation_is_enriched_from_invariant(session_factory) -> None:
    """Модель называет правило, а категорию и важность берёт из инварианта."""
    seeded = seed_demo_invariants(session_factory)
    hard = next(item for item in seeded if item["severity"] == "hard")
    fake = FakeClient(invariant_reply=json.dumps({"violations": [
        {"name": hard["name"], "reason": "предложение опирается на запрещённое средство"}
    ]}, ensure_ascii=False))
    checker = InvariantChecker(session_factory=session_factory,
                               client_factory=lambda: fake)

    result = checker.check(CLEAN_TEXT)

    assert result.verdict == VERDICT_REFUSAL
    assert result.llm_used is True
    violation = result.violations[0]
    assert violation.name == hard["name"]
    assert violation.category == hard["category"]
    assert violation.severity == hard["severity"]
    assert violation.source == "llm"


def test_llm_unknown_invariant_name_is_ignored(session_factory) -> None:
    """Модель выдумала правило — вердикт остаётся «нарушений нет»."""
    seed_demo_invariants(session_factory)
    fake = FakeClient(invariant_reply='{"violations": [{"name": "Выдуманное", "reason": "x"}]}')
    checker = InvariantChecker(session_factory=session_factory,
                               client_factory=lambda: fake)

    result = checker.check(CLEAN_TEXT)

    assert result.verdict == VERDICT_ALLOWED
    assert result.llm_used is True
    assert result.violations == []


def test_broken_json_from_llm_keeps_verdict_and_notes_reason(session_factory) -> None:
    """Неразобранный ответ — не ошибка хода: вердикт правил плюс причина в ``note``."""
    seed_demo_invariants(session_factory)
    fake = FakeClient(invariant_reply="не json")
    checker = InvariantChecker(session_factory=session_factory,
                               client_factory=lambda: fake)

    result = checker.check(CLEAN_TEXT)

    assert result.verdict == VERDICT_ALLOWED
    assert result.llm_used is False
    assert "не разобран" in result.note


def test_llm_failure_keeps_verdict_and_notes_reason(session_factory) -> None:
    """Сбой вызова (нет ключа, сеть) не ломает проверку и объясняется в ``note``."""
    seed_demo_invariants(session_factory)
    fake = FakeClient(invariant_error=RuntimeError("Ключ API не задан"))
    checker = InvariantChecker(session_factory=session_factory,
                               client_factory=lambda: fake)

    result = checker.check(CLEAN_TEXT)

    assert result.verdict == VERDICT_ALLOWED
    assert result.llm_used is False
    assert "не выполнена" in result.note
    assert "Ключ API не задан" in result.note


def test_failure_of_llm_does_not_hide_rule_violation(session_factory) -> None:
    """Сбой модели не мешает отказать: правила отработали раньше вызова."""
    seed_demo_invariants(session_factory)
    fake = FakeClient(invariant_error=RuntimeError("сеть недоступна"))
    checker = InvariantChecker(session_factory=session_factory,
                               client_factory=lambda: fake)

    result = checker.check(FLASK_TEXT)

    assert result.verdict == VERDICT_REFUSAL
    assert fake.invariant_calls == []


# ---------- пустой текст и явный список ----------
@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_is_not_sent_to_llm(checker, fake, session_factory, text) -> None:
    """Пустой текст проверять нечего, но список проверенных правил сохраняется."""
    seed_demo_invariants(session_factory)

    result = checker.check(text)

    assert result.verdict == VERDICT_ALLOWED
    assert result.checked
    assert fake.calls == []


def test_explicit_invariants_replace_database(checker, fake) -> None:
    """Явный список правил (скрипты и отчёты) не читает БД."""
    result = checker.check(FLASK_TEXT, use_llm=False,
                           invariants=[dict(DEMO_INVARIANTS[0])])

    assert result.verdict == VERDICT_REFUSAL
    assert result.checked == [DEMO_INVARIANTS[0]["name"]]


def test_invariant_of_other_category_does_not_fire(checker, session_factory) -> None:
    """Правило действует только на своей категории: стеку Flask не мешает."""
    seed_invariant(session_factory, name="Только Python",
                   description="Только Python, без JavaScript, TypeScript и их фреймворков",
                   category="stack_constraints", severity="hard")

    result = checker.check(FLASK_TEXT, use_llm=False)

    assert result.verdict == VERDICT_ALLOWED


# ---------- merged_with ----------
def hard_violation(name: str = "Только FastAPI и Streamlit") -> InvariantViolation:
    """Нарушение hard-инварианта для тестов объединения вердиктов."""
    return InvariantViolation(name=name, category="architecture", severity="hard",
                              reason="текст упоминает Flask", source="deterministic")


def soft_violation(name: str = "Платные API — только с согласия") -> InvariantViolation:
    """Нарушение soft-инварианта для тестов объединения вердиктов."""
    return InvariantViolation(name=name, category="business_rules", severity="soft",
                              reason="текст предлагает платный вариант",
                              source="deterministic")


def test_merge_of_request_warning_and_clean_answer_stays_warning() -> None:
    """Предупреждение в запросе не «теряется» чистым ответом модели."""
    request = InvariantCheckResult(text="запрос", checked=["A"],
                                   violations=[soft_violation()])
    answer = InvariantCheckResult(text="ответ", checked=["A"], llm_used=True)

    merged = request.merged_with(answer)

    assert merged.verdict == "warning"
    assert merged.llm_used is True
    assert merged.text == "ответ"


def test_merge_does_not_duplicate_violation_of_same_invariant() -> None:
    """Одно правило в отказе называется один раз, даже если нарушено дважды."""
    request = InvariantCheckResult(text="запрос", checked=["A"],
                                   violations=[hard_violation()])
    answer = InvariantCheckResult(text="ответ", checked=["A"],
                                  violations=[hard_violation()])

    merged = request.merged_with(answer)

    assert len(merged.violations) == 1
    assert merged.verdict == VERDICT_REFUSAL


def test_merge_keeps_both_distinct_violations() -> None:
    """Разные правила попадают в отказ оба: пользователь видит весь список."""
    request = InvariantCheckResult(text="запрос", checked=["A"],
                                   violations=[hard_violation()])
    answer = InvariantCheckResult(text="ответ", checked=["B"],
                                  violations=[hard_violation("Только Python")])

    merged = request.merged_with(answer)

    assert [item.name for item in merged.violations] == [
        "Только FastAPI и Streamlit", "Только Python"
    ]
    assert merged.checked == ["A", "B"]


def test_merge_hard_answer_beats_soft_request() -> None:
    """Жёсткое нарушение в ответе побеждает мягкое в запросе: отказ важнее."""
    request = InvariantCheckResult(text="запрос", violations=[soft_violation()])
    answer = InvariantCheckResult(text="ответ", violations=[hard_violation()])

    assert request.merged_with(answer).verdict == VERDICT_REFUSAL


def test_merge_keeps_first_non_empty_note() -> None:
    """Причина пропуска LLM-слоя сохраняется для отчёта и интерфейса."""
    request = InvariantCheckResult(text="запрос", note="")
    answer = InvariantCheckResult(text="ответ", note="проверка LLM не выполнена: сбой")

    assert request.merged_with(answer).note == "проверка LLM не выполнена: сбой"


def test_to_dict_is_api_shaped() -> None:
    """Результат проверки уходит в API без маппинга (поле ``invariants``)."""
    result = InvariantCheckResult(text="текст", checked=["A"],
                                  violations=[hard_violation()], llm_used=True)

    assert result.to_dict() == {
        "checked": ["A"],
        "llm_used": True,
        "verdict": VERDICT_REFUSAL,
        "violations": [hard_violation().to_dict()],
        "note": "",
    }
