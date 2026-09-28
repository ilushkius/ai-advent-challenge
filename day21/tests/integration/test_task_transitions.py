"""Правила допуска переходов на уровне сервиса (день 15).

Поведение машины (создание, шаги, пауза, откат) — в
``tests/integration/test_task_state.py``; здесь — то, ЧТО машина не пускает и
почему: закрытые guard-условиями границы этапов, пропуск этапов, откат не по
одному этапу, неизвестный этап, журнал отклонённых попыток и флаги
согласования. Сеть и рабочая БД не используются.
"""

from __future__ import annotations

import pytest

from backend.domain.task_fsm import InvalidTransitionError, TaskStage, TaskStep
from backend.domain.task_state_machine import (
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_PLAN_APPROVED,
    FLAG_VALIDATION_PASSED,
    TASK_FLAGS,
    can_transition,
)
from backend.services.task_state import TaskNotFoundError, TaskStateMachine

AGENT_ID = "task01"
TASK_ID = "tz"


@pytest.fixture
def created(task_machine):
    """Задача в состоянии planning/gather_requirements."""
    return task_machine.create(AGENT_ID, TASK_ID)


# ---------- закрытые границы этапов ----------
def test_advance_across_border_without_flag_is_refused(task_machine, created):
    """Последний шаг этапа не выпускает задачу без согласования этапа."""
    for _ in range(2):  # planning: gather_requirements -> create_plan
        task_machine.advance_step(TASK_ID)

    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.advance_step(TASK_ID)
    assert str(excinfo.value) == "Нельзя перейти в execution: план не утверждён"

    state = task_machine.get_state(TASK_ID)
    assert (state["stage"], state["current_step"]) == (
        TaskStage.PLANNING.value, TaskStep.CREATE_PLAN.value,
    )
    # Флаг открывает тот же переход — и задача идёт дальше.
    task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    assert task_machine.advance_step(TASK_ID)["stage"] == TaskStage.EXECUTION.value


@pytest.mark.parametrize(
    "stage, step, target, flag, message",
    [
        (TaskStage.PLANNING, TaskStep.CREATE_PLAN, TaskStage.EXECUTION,
         FLAG_PLAN_APPROVED, "Нельзя перейти в execution: план не утверждён"),
        (TaskStage.EXECUTION, TaskStep.TEST_LOCALLY, TaskStage.VALIDATION,
         FLAG_IMPLEMENTATION_COMPLETE,
         "Нельзя перейти в validation: реализация не завершена"),
        (TaskStage.VALIDATION, TaskStep.FINALIZE, TaskStage.DONE,
         FLAG_VALIDATION_PASSED, "Нельзя перейти в done: валидация не пройдена"),
    ],
    ids=lambda x: getattr(x, "value", str(x))[:26],
)
def test_transition_forward_requires_its_flag(
    task_machine, stage, step, target, flag, message
):
    """Каждый прямой переход закрыт своим флагом и объясняет, каким именно."""
    task_machine.create(
        AGENT_ID, TASK_ID, initial_stage=stage.value, initial_step=step.value
    )

    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(TASK_ID, target.value)
    assert str(excinfo.value) == message
    assert task_machine.get_state(TASK_ID)["stage"] == stage.value

    task_machine.set_flags(TASK_ID, {flag: True})
    assert task_machine.transition_to(TASK_ID, target.value)["stage"] == target.value


def test_paused_task_can_continue_into_another_allowed_stage(task_machine, created):
    """Продолжение в другой этап — только если он доступен из этапа паузы."""
    task_machine.pause(TASK_ID)

    # Из planning доступна только пауза: без согласования плана выхода нет.
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(TASK_ID, TaskStage.EXECUTION.value)
    assert str(excinfo.value) == (
        "Нельзя перейти из paused в execution: пауза была на этапе planning"
    )

    task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    state = task_machine.transition_to(TASK_ID, TaskStage.EXECUTION.value)
    assert state["stage"] == TaskStage.EXECUTION.value
    assert state["paused_from_stage"] is None


# ---------- запрещённые пары этапов ----------
def test_transition_skipping_stages_explains_what_is_skipped(task_machine, created):
    """Пропуск этапов отклоняется с перечислением пропущенного."""
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(TASK_ID, TaskStage.DONE.value)
    assert str(excinfo.value) == (
        "Нельзя перейти из planning в done: пропущены этапы execution и validation"
    )

    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(TASK_ID, TaskStage.VALIDATION.value)
    assert str(excinfo.value) == (
        "Нельзя перейти из planning в validation: пропущен этап execution"
    )
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.PLANNING.value


def test_transition_backwards_by_two_stages_is_refused(task_machine):
    """Перескок назад на два этапа — отказ: откат идёт по одному этапу."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(TASK_ID, TaskStage.PLANNING.value)
    assert "откат идёт по одному этапу" in str(excinfo.value)


def test_transition_unknown_stage_is_refused_and_journaled(task_machine, created):
    """Значение этапа вне Enum — отказ с перечислением допустимых этапов."""
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(TASK_ID, "нет-такого")
    assert str(excinfo.value) == (
        "Неизвестный этап задачи: 'нет-такого'. "
        "Допустимые: planning, execution, validation, done, paused"
    )
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.PLANNING.value


def test_rejected_transition_is_journaled_and_keeps_state(task_machine, created):
    """Отклонённая попытка видна в журнале и состояние не меняет."""
    with pytest.raises(InvalidTransitionError):
        task_machine.transition_to(TASK_ID, TaskStage.DONE.value)

    entries = task_machine.get_full_history(TASK_ID)
    assert [entry["accepted"] for entry in entries] == [True, False]
    assert entries[-1]["to_stage"] == TaskStage.DONE.value
    assert entries[-1]["reason"].startswith("Нельзя перейти из planning в done")
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.PLANNING.value


# ---------- флаги-согласования ----------
def test_set_flags_writes_context_and_returns_state(task_machine, created):
    """Флаг сохраняется в context и сразу меняет список доступных этапов."""
    before = task_machine.get_state(TASK_ID)
    assert before["allowed_next"] == [TaskStage.PAUSED.value]

    state = task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    assert state["context"][FLAG_PLAN_APPROVED] is True
    assert state["allowed_next"] == [
        TaskStage.EXECUTION.value, TaskStage.PAUSED.value,
    ]
    # Смена флага — не переход: журнал не растёт.
    assert len(task_machine.get_full_history(TASK_ID)) == 1


def test_set_flags_rejects_unknown_flag(task_machine, created):
    """Опечатка в имени флага — ошибка, а не молча закрытый переход."""
    with pytest.raises(ValueError) as excinfo:
        task_machine.set_flags(TASK_ID, {"plan_aproved": True})
    assert "неизвестные флаги задачи: plan_aproved" in str(excinfo.value)


def test_set_flags_rejects_empty_dict(task_machine, created):
    """Пустой запрос флагов — ошибка: он ничего не меняет."""
    with pytest.raises(ValueError) as excinfo:
        task_machine.set_flags(TASK_ID, {})
    assert "не передан ни один флаг" in str(excinfo.value)


def test_set_flags_of_unknown_task_raises(task_machine):
    """Неизвестная задача — TaskNotFoundError (роутер отвечает 404)."""
    with pytest.raises(TaskNotFoundError):
        task_machine.set_flags("нет-такой", {FLAG_PLAN_APPROVED: True})


@pytest.mark.parametrize("flag", TASK_FLAGS)
def test_every_flag_is_known_to_the_service(task_machine, created, flag):
    """Флаги из домена принимаются сервисом: списки не разъехались."""
    state = task_machine.set_flags(TASK_ID, {flag: True})
    assert state["context"][flag] is True


# ---------- таблица допуска ----------
def test_can_transition_matrix_matches_the_graph(task_machine):
    """Тот же ответ, что у графа допуска (в т.ч. на неизвестном этапе)."""
    assert can_transition("validation", "execution") is True
    assert can_transition("validation", "done") is True
    assert can_transition("done", "execution") is False
    assert can_transition("paused", "done") is False
    with pytest.raises(ValueError):
        can_transition("нет-такого", "done")


def test_task_state_machine_exposes_no_validity_helper():
    """Допуск перехода — функция домена, а не метод сервиса (день 15)."""
    assert not hasattr(TaskStateMachine, "is_valid_transition")
    assert can_transition is not None
