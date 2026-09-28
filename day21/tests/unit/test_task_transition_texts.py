"""Тесты текстов отказа и подсказок правил допуска состояния задачи (день 15).

Отказ должен не только запрещать, но и объяснять: что именно нельзя, почему и
что сделать. Здесь зафиксированы дословные тексты (их видит пользователь в
красном сообщении панели, в `detail` ответа 400 и в ответе агента), граница
длины причины — она уходит в колонку `task_transitions.reason` — и уведомление
агента об отклонённой реплике.

Тесты идут без БД, сети и UI: модуль знает только про ``enum``-члены
``backend/domain/task_fsm.py``.
"""

from __future__ import annotations

import itertools

import pytest

from backend.core import config
from backend.domain.task_fsm import TaskStage, TaskStep
from backend.domain.task_state_machine import (
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_PLAN_APPROVED,
    FLAG_VALIDATION_PASSED,
    intent_refusal_notice,
    transition_error_message,
    transition_explanation,
    transition_hint,
)

ALL_PAIRS = list(itertools.product(TaskStage, TaskStage))

# Флаги «как будто пользователь их отметил».
ALL_FLAGS = {
    FLAG_PLAN_APPROVED: True,
    FLAG_IMPLEMENTATION_COMPLETE: True,
    FLAG_VALIDATION_PASSED: True,
}


def make_ctx(context=None, paused_from=None) -> dict:
    """Guard-контекст строки задачи: флаги плюс производные поля состояния."""
    return {
        "stage": TaskStage.EXECUTION.value,
        "current_step": TaskStep.IMPLEMENT.value,
        "paused_from_stage": paused_from,
        **(context or {}),
    }


# ---------- тексты отказа и подсказки ----------
def test_transition_explanation_is_empty_for_allowed_pair() -> None:
    """У разрешённого перехода нет ни причины отказа, ни подсказки."""
    assert transition_explanation(
        TaskStage.PLANNING, TaskStage.EXECUTION, make_ctx(ALL_FLAGS)
    ) == ("", "")
    assert transition_error_message(
        TaskStage.EXECUTION, TaskStage.PAUSED, make_ctx(ALL_FLAGS)
    ) == ""


@pytest.mark.parametrize(
    "from_stage, to_stage, context, paused_from, message, hint",
    [
        (
            TaskStage.PLANNING, TaskStage.DONE, {}, None,
            "Нельзя перейти из planning в done: пропущены этапы execution и validation",
            "Сначала перейдите в execution и пройдите этапы по порядку.",
        ),
        (
            TaskStage.EXECUTION, TaskStage.DONE, {}, None,
            "Нельзя перейти из execution в done: пропущен этап validation",
            "Сначала перейдите в validation и пройдите этапы по порядку.",
        ),
        (
            TaskStage.PLANNING, TaskStage.VALIDATION, {}, None,
            "Нельзя перейти из planning в validation: пропущен этап execution",
            "Сначала перейдите в execution и пройдите этапы по порядку.",
        ),
        (
            TaskStage.VALIDATION, TaskStage.PLANNING, {}, None,
            "Нельзя перейти из validation в planning: откат идёт по одному этапу "
            "(сначала execution)",
            "Откатывайтесь по одному этапу (кнопка «Откат»).",
        ),
        (
            TaskStage.DONE, TaskStage.EXECUTION, {}, None,
            "Нельзя перейти из done: этап done терминальный",
            "Завершённая задача изменению не подлежит: заведите новую задачу.",
        ),
        (
            TaskStage.PAUSED, TaskStage.DONE, {}, "validation",
            "Нельзя перейти из paused в done: из паузы возвращаются только в "
            "planning, execution или validation",
            "Продолжите задачу в этап, откуда её поставили на паузу, и доведите "
            "до нужного этапа.",
        ),
        (
            TaskStage.PLANNING, TaskStage.PLANNING, {}, None,
            "Нельзя перейти из planning в planning: задача уже на этом этапе",
            "Выберите другой этап.",
        ),
        (
            TaskStage.PLANNING, TaskStage.EXECUTION, {}, None,
            "Нельзя перейти в execution: план не утверждён",
            "Утвердите план: отметьте флаг «📝 План утверждён» в панели задачи.",
        ),
        (
            TaskStage.EXECUTION, TaskStage.VALIDATION, {}, None,
            "Нельзя перейти в validation: реализация не завершена",
            "Отметьте флаг «⚙️ Реализация завершена» в панели задачи.",
        ),
        (
            TaskStage.VALIDATION, TaskStage.DONE, {}, None,
            "Нельзя перейти в done: валидация не пройдена",
            "Отметьте флаг «✅ Валидация пройдена» в панели задачи.",
        ),
        (
            TaskStage.PAUSED, TaskStage.EXECUTION, {}, "planning",
            "Нельзя перейти из paused в execution: пауза была на этапе planning",
            "Продолжите задачу в этап, откуда её поставили на паузу "
            "(или в доступный следующий этап).",
        ),
        (
            TaskStage.PAUSED, TaskStage.EXECUTION, {}, None,
            "Нельзя перейти из paused в execution: не сохранён этап паузы",
            "Продолжите задачу в этап, откуда её поставили на паузу "
            "(или в доступный следующий этап).",
        ),
    ],
    ids=lambda x: str(getattr(x, "value", x))[:28],
)
def test_transition_explanation_texts(
    from_stage, to_stage, context, paused_from, message, hint
) -> None:
    """Тексты отказа и подсказки зафиксированы дословно."""
    ctx = make_ctx(context, paused_from=paused_from)
    assert transition_explanation(from_stage, to_stage, ctx) == (message, hint)
    assert transition_error_message(from_stage, to_stage, ctx) == message
    assert transition_hint(from_stage, to_stage, ctx) == hint


@pytest.mark.parametrize("pair", ALL_PAIRS, ids=lambda p: f"{p[0].value}->{p[1].value}")
@pytest.mark.parametrize(
    "context, paused_from",
    [({}, None), (ALL_FLAGS, None), ({}, "execution"), ({}, "validation")],
    ids=["no-flags", "all-flags", "pause-execution", "pause-validation"],
)
def test_transition_error_message_fits_reason_column(pair, context, paused_from) -> None:
    """Причина отказа помещается в колонку журнала (TASK_REASON_MAX)."""
    message = transition_error_message(pair[0], pair[1], make_ctx(context, paused_from=paused_from))
    assert 0 <= len(message) <= config.TASK_REASON_MAX


def test_intent_refusal_notice_format() -> None:
    """Уведомление агента об отклонённой реплике называет причину и что доступно."""
    notice = intent_refusal_notice("advance", "Нельзя перейти в execution: план не утверждён", ["paused"])
    assert notice == (
        "⚠️ Переход по реплике «advance» не выполнен: "
        "Нельзя перейти в execution: план не утверждён "
        "Доступные следующие этапы: paused."
    )
    assert intent_refusal_notice("advance", "причина", []).endswith(
        "Доступные следующие этапы: нет."
    )


