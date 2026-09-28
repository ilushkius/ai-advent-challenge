"""Тесты текстов инвариантов для промпта и ответа (день 14).

Формулировки видит и модель (блок в системном промпте), и пользователь (отказ или
предупреждение), поэтому они зафиксированы дословно: расхождение между тем, что
ушло в промпт, и тем, что показано в чате, ищется именно здесь.
"""

from __future__ import annotations

import pytest

from backend.domain.invariant_prompt import (
    INVARIANTS_FOOTER,
    INVARIANTS_HEADER,
    REFUSAL_FOOTER,
    REFUSAL_HEADER,
    WARNING_HEADER,
    invariant_line,
    render_check_user_message,
    render_invariants_block,
    render_violation_refusal,
    render_violation_warning,
    violation_line,
)

HARD_INVARIANT = {
    "name": "Только FastAPI и Streamlit",
    "description": "Используем только FastAPI и Streamlit, никаких Flask или Django",
    "category": "architecture",
    "severity": "hard",
}
SOFT_INVARIANT = {
    "name": "Платные API — только с согласия",
    "description": "Платный вариант — только с явного согласия пользователя",
    "category": "business_rules",
    "severity": "soft",
}
VIOLATION = {
    "name": "Только FastAPI и Streamlit",
    "category": "architecture",
    "severity": "hard",
    "reason": "текст упоминает Flask, а инвариант «Только FastAPI и Streamlit» это запрещает",
    "source": "deterministic",
}


def test_block_of_no_invariants_is_empty() -> None:
    """Без инвариантов в промпт не уходит ничего — поведение дня 13 сохраняется."""
    assert render_invariants_block([]) == ""
    assert render_invariants_block(None) == ""


def test_block_of_one_invariant_is_exact() -> None:
    """Блок — заголовок, строка инварианта, пустая строка и условие отказа."""
    expected = (
        f"{INVARIANTS_HEADER}\n"
        f"- [hard] Только FastAPI и Streamlit (architecture): "
        f"Используем только FastAPI и Streamlit, никаких Flask или Django\n"
        f"\n"
        f"{INVARIANTS_FOOTER}"
    )

    assert render_invariants_block([HARD_INVARIANT]) == expected


def test_block_lists_every_invariant_in_order() -> None:
    """Порядок строк — порядок инвариантов: его задаёт выборка из БД."""
    block = render_invariants_block([HARD_INVARIANT, SOFT_INVARIANT])
    lines = block.split("\n")

    assert lines[0] == INVARIANTS_HEADER
    assert lines[1] == invariant_line(HARD_INVARIANT)
    assert lines[2] == invariant_line(SOFT_INVARIANT)
    assert lines[-1] == INVARIANTS_FOOTER


def test_invariant_line_shows_severity_and_category() -> None:
    """В строке видны важность, имя, категория и описание — модель решает по ним."""
    line = invariant_line(HARD_INVARIANT)

    assert line.startswith("- [hard] Только FastAPI и Streamlit (architecture): ")
    assert line.endswith(HARD_INVARIANT["description"])


def test_refusal_is_headed_and_footed() -> None:
    """Отказ начинается заголовком, содержит строку нарушения и что делать дальше."""
    text = render_violation_refusal([VIOLATION])

    assert text.startswith(REFUSAL_HEADER)
    assert text.endswith(REFUSAL_FOOTER)
    assert violation_line(VIOLATION) in text
    assert "[hard]" in text
    assert "Только FastAPI и Streamlit" in text


def test_refusal_lists_every_violation() -> None:
    """Все нарушения попадают в отказ: пользователь видит весь список причин."""
    second = dict(VIOLATION, name="Только Python", severity="hard",
                  reason="текст упоминает React, а инвариант «Только Python» это запрещает")
    text = render_violation_refusal([VIOLATION, second])

    assert text.count("\n- ") == 2
    assert second["name"] in text


def test_warning_contains_reason_without_footer() -> None:
    """Предупреждение короче отказа: заголовок и причины, без «не выполнено»."""
    text = render_violation_warning([VIOLATION])

    assert text.startswith(WARNING_HEADER)
    assert VIOLATION["reason"] in text
    assert REFUSAL_FOOTER not in text


def test_warning_for_soft_invariant_keeps_soft_mark() -> None:
    """Важность в строке предупреждения — soft: видно, что нарушение не жёсткое."""
    soft_violation = dict(VIOLATION, name=SOFT_INVARIANT["name"], severity="soft",
                          category="business_rules")

    assert "- [soft] Платные API" in render_violation_warning([soft_violation])


@pytest.mark.parametrize(
    "render, empty_text",
    [
        (render_violation_refusal, f"{REFUSAL_HEADER}\n{REFUSAL_FOOTER}"),
        (render_violation_warning, WARNING_HEADER),
    ],
)
def test_renders_without_violations_have_no_empty_lines(render, empty_text) -> None:
    """Пустой список нарушений не оставляет пустых строк в тексте ответа."""
    assert render([]) == empty_text


def test_check_message_carries_invariants_and_text() -> None:
    """Запрос к LLM содержит список инвариантов и проверяемый текст в конце."""
    text = "Давай перепишем бэкенд на Flask"
    message = render_check_user_message(text, [HARD_INVARIANT, SOFT_INVARIANT])

    assert message.startswith("Инварианты:\n")
    assert invariant_line(HARD_INVARIANT) in message
    assert invariant_line(SOFT_INVARIANT) in message
    assert message.endswith(f"Проверяемый текст:\n{text}")


def test_check_message_without_invariants_still_carries_text() -> None:
    """Список инвариантов пуст — сообщение остаётся разбираемым по разделителям."""
    message = render_check_user_message("текст", [])

    assert message == "Инварианты:\n\nПроверяемый текст:\nтекст"
