"""Поведение TaskStateMachine (день 15): переходы, флаги, отказы, пауза, откат.

Проверяется наблюдаемый контракт машины: с какого этапа можно завести задачу,
куда ведут advance/rollback, почему переход вперёд без согласования этапа
отклоняется, что сохраняет пауза, какие ошибки кидаются на недопустимый переход
и на неизвестную задачу. Хранение (журнал попыток, проекция в словарь,
переживание перезапуска) проверяется отдельно —
``tests/integration/test_task_store.py``; тонкие обёртки менеджера —
``tests/integration/test_task_manager.py``. Сеть и рабочая БД не используются.
"""

from __future__ import annotations

import pytest

from backend.domain.task_fsm import InvalidTransitionError, TaskStage, TaskStep
from backend.domain.task_prompt import DONE_ACTION, EXPECTED_ACTIONS, PAUSED_ACTION
from backend.domain.task_state_machine import (
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_PLAN_APPROVED,
    FLAG_VALIDATION_PASSED,
    TASK_FLAGS,
)
from backend.services.task_state import TaskExistsError, TaskNotFoundError, TaskStateMachine

AGENT_ID = "task01"
TASK_ID = "tz"

# Этапы, с которых задачу можно завести, и их первый шаг.
ACTIVE_START_STAGES = (
    (TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS),
    (TaskStage.EXECUTION, TaskStep.IMPLEMENT),
    (TaskStage.VALIDATION, TaskStep.REVIEW),
)

# Полный прямой ход задачи от planning/gather_requirements до done/finalize.
FORWARD_PATH = (
    (TaskStage.PLANNING, TaskStep.DEFINE_SCOPE),
    (TaskStage.PLANNING, TaskStep.CREATE_PLAN),
    (TaskStage.EXECUTION, TaskStep.IMPLEMENT),
    (TaskStage.EXECUTION, TaskStep.TEST_LOCALLY),
    (TaskStage.VALIDATION, TaskStep.REVIEW),
    (TaskStage.VALIDATION, TaskStep.RUN_TESTS),
    (TaskStage.VALIDATION, TaskStep.FINALIZE),
    (TaskStage.DONE, TaskStep.FINALIZE),
)

# Флаг, без которого соответствующий шаг прямого хода не наступает: он закрывает
# выход из предыдущего этапа (``task_state_machine.GUARDS``).
BORDER_FLAGS = {
    (TaskStage.EXECUTION, TaskStep.IMPLEMENT): FLAG_PLAN_APPROVED,
    (TaskStage.VALIDATION, TaskStep.REVIEW): FLAG_IMPLEMENTATION_COMPLETE,
    (TaskStage.DONE, TaskStep.FINALIZE): FLAG_VALIDATION_PASSED,
}


@pytest.fixture
def created(task_machine):
    """Задача в состоянии planning/gather_requirements."""
    return task_machine.create(AGENT_ID, TASK_ID)


def walk_forward(machine, task_id: str) -> dict:
    """Проводит задачу по всему прямому ходу, выставляя согласования этапов."""
    state = machine.get_state(task_id)
    for stage, step in FORWARD_PATH:
        flag = BORDER_FLAGS.get((stage, step))
        if flag:
            machine.set_flags(task_id, {flag: True})
        state = machine.advance_step(task_id)
        assert (state["stage"], state["current_step"]) == (stage.value, step.value)
    return state


# ---------- создание ----------
def test_create_returns_initial_state(task_machine, created):
    """Новая задача встаёт на первый шаг planning с ожидаемым действием."""
    assert created["task_id"] == TASK_ID
    assert created["agent_id"] == AGENT_ID
    assert created["stage"] == TaskStage.PLANNING.value
    assert created["current_step"] == TaskStep.GATHER_REQUIREMENTS.value
    assert created["expected_action"] == EXPECTED_ACTIONS[
        (TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS)
    ]
    assert task_machine.get_state(TASK_ID) == created


def test_create_can_start_from_any_active_stage(task_machine):
    """Стартовать можно с любого рабочего этапа — не только с планирования."""
    for index, (stage, first) in enumerate(ACTIVE_START_STAGES):
        state = task_machine.create(AGENT_ID, f"tz{index}", initial_stage=stage.value)
        assert state["stage"] == stage.value
        assert state["current_step"] == first.value
        assert state["expected_action"] == EXPECTED_ACTIONS[(stage, first)]


def test_create_accepts_explicit_step_and_action(task_machine):
    """Шаг и ожидаемое действие можно задать, а не только получить по умолчанию."""
    state = task_machine.create(
        AGENT_ID, TASK_ID, TaskStage.PLANNING.value,
        initial_step=TaskStep.CREATE_PLAN.value,
        expected_action="ожидается утверждение плана пользователем",
    )
    assert state["current_step"] == TaskStep.CREATE_PLAN.value
    assert state["expected_action"] == "ожидается утверждение плана пользователем"


def test_create_rejects_duplicate_task_id(task_machine, created):
    """task_id уникален: вторая задача с тем же id — конфликт, а не перезапись."""
    with pytest.raises(TaskExistsError):
        task_machine.create(AGENT_ID, TASK_ID)
    assert task_machine.get_state(TASK_ID) == created


@pytest.mark.parametrize(
    "agent_id, task_id", [("", TASK_ID), (AGENT_ID, ""), (" ", TASK_ID), (AGENT_ID, " ")]
)
def test_create_rejects_blank_ids(task_machine, agent_id, task_id):
    """Пустые agent_id/task_id — ошибка."""
    with pytest.raises(ValueError):
        task_machine.create(agent_id, task_id)


@pytest.mark.parametrize("stage", [TaskStage.PAUSED.value, TaskStage.DONE.value])
def test_create_rejects_terminal_and_paused_stages(task_machine, stage):
    """Задачу нельзя завести уже приостановленной или завершённой."""
    with pytest.raises(InvalidTransitionError):
        task_machine.create(AGENT_ID, "tz-nope", initial_stage=stage)


def test_create_rejects_step_of_another_stage(task_machine):
    """Шаг обязан принадлежать стартовому этапу."""
    with pytest.raises(InvalidTransitionError):
        task_machine.create(
            AGENT_ID, TASK_ID, TaskStage.PLANNING.value,
            initial_step=TaskStep.RUN_TESTS.value,
        )


# ---------- прямой ход ----------
def test_advance_step_walks_the_whole_forward_path(task_machine, created):
    """advance_step проходит все шаги и границы этапов до done включительно."""
    state = walk_forward(task_machine, TASK_ID)

    assert state["is_active"] is False
    assert state["rollback_stage"] is None
    assert state["allowed_next"] == []
    with pytest.raises(InvalidTransitionError):
        task_machine.advance_step(TASK_ID)


@pytest.mark.parametrize("stage, step", ACTIVE_START_STAGES, ids=lambda x: str(x))
def test_pause_and_resume_keep_the_step(task_machine, stage, step):
    """Пауза сохраняет шаг, продолжение возвращает в тот же этап и шаг."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=stage.value)

    paused = task_machine.pause(TASK_ID)
    assert paused["stage"] == TaskStage.PAUSED.value
    assert paused["current_step"] == step.value
    assert paused["expected_action"] == PAUSED_ACTION
    assert paused["paused_from_stage"] == stage.value
    assert paused["is_active"] is True
    assert "Текущий этап задачи: paused." in paused["prompt_block"]

    resumed = task_machine.resume(TASK_ID)
    assert (resumed["stage"], resumed["current_step"]) == (stage.value, step.value)
    assert resumed["expected_action"] == EXPECTED_ACTIONS[(stage, step)]
    assert resumed["paused_from_stage"] is None


def test_pause_from_done_raises(task_machine, created):
    """Из завершённой задачи на паузу не встать: этап done терминальный."""
    walk_forward(task_machine, TASK_ID)

    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.pause(TASK_ID)
    assert str(excinfo.value) == "Нельзя перейти из done: этап done терминальный"
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.DONE.value


def test_pause_twice_raises(task_machine, created):
    """Повторная пауза — явная ошибка."""
    task_machine.pause(TASK_ID)
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.pause(TASK_ID)
    assert "задача уже на этом этапе" in str(excinfo.value)


def test_resume_without_pause_raises(task_machine, created):
    """Продолжение задачи, которая не на паузе, — явная ошибка."""
    with pytest.raises(InvalidTransitionError):
        task_machine.resume(TASK_ID)


def test_resume_from_pause_goes_to_the_saved_stage(task_machine, created):
    """Продолжение из паузы возвращает ровно туда, где задача стояла."""
    task_machine.create(AGENT_ID, "tz-plan")
    task_machine.pause("tz-plan")

    resumed = task_machine.resume("tz-plan")
    assert (resumed["stage"], resumed["current_step"]) == (
        TaskStage.PLANNING.value, TaskStep.GATHER_REQUIREMENTS.value,
    )


def test_step_forward_and_rollback_are_rejected_on_pause(task_machine, created):
    """На паузе задача не двигается: сначала нужно продолжить её."""
    task_machine.pause(TASK_ID)
    with pytest.raises(InvalidTransitionError):
        task_machine.advance_step(TASK_ID)
    with pytest.raises(InvalidTransitionError):
        task_machine.rollback(TASK_ID)


# ---------- откат ----------
def test_rollback_returns_to_first_step_of_previous_stage(task_machine):
    """Откат сбрасывает шаг на первый шаг предыдущего этапа."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    task_machine.advance_step(TASK_ID)  # validation/run_tests

    rolled = task_machine.rollback(TASK_ID)
    assert rolled["stage"] == TaskStage.EXECUTION.value
    assert rolled["current_step"] == TaskStep.IMPLEMENT.value
    assert rolled["expected_action"] == EXPECTED_ACTIONS[
        (TaskStage.EXECUTION, TaskStep.IMPLEMENT)
    ]

    assert task_machine.rollback(TASK_ID)["stage"] == TaskStage.PLANNING.value
    assert task_machine.get_state(TASK_ID)["current_step"] == (
        TaskStep.GATHER_REQUIREMENTS.value
    )


def test_rollback_clears_agreements_of_the_target_stage(task_machine):
    """Возврат назад отменяет согласования: после отката их нужно получить снова."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    task_machine.set_flags(TASK_ID, {
        FLAG_PLAN_APPROVED: True,
        FLAG_IMPLEMENTATION_COMPLETE: True,
        FLAG_VALIDATION_PASSED: True,
    })

    rolled = task_machine.rollback(TASK_ID)  # validation -> execution
    assert FLAG_IMPLEMENTATION_COMPLETE not in rolled["context"]
    assert FLAG_VALIDATION_PASSED not in rolled["context"]
    assert rolled["context"][FLAG_PLAN_APPROVED] is True

    back_to_plan = task_machine.rollback(TASK_ID)  # execution -> planning
    assert all(flag not in back_to_plan["context"] for flag in TASK_FLAGS)


def test_rollback_from_planning_and_done_raises(task_machine):
    """Откатываться некуда: планирование — первый этап, done — терминальный."""
    task_machine.create(AGENT_ID, "tz-plan")
    with pytest.raises(InvalidTransitionError):
        task_machine.rollback("tz-plan")

    task_machine.create(AGENT_ID, "tz-done")
    walk_forward(task_machine, "tz-done")
    with pytest.raises(InvalidTransitionError):
        task_machine.rollback("tz-done")


def test_rollback_to_wrong_stage_raises(task_machine):
    """Откат разрешён ровно на один этап назад, не «куда захотелось»."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    with pytest.raises(InvalidTransitionError):
        task_machine.rollback(TASK_ID, to_stage=TaskStage.PLANNING.value)
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.VALIDATION.value


# ---------- прямой переход ----------
def test_transition_to_done(task_machine):
    """Завершение задачи — переход в done после согласования валидации."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    task_machine.set_flags(TASK_ID, {FLAG_VALIDATION_PASSED: True})

    state = task_machine.transition_to(
        TASK_ID, TaskStage.DONE.value, None, None, reason="задача завершена",
    )
    assert state["stage"] == TaskStage.DONE.value
    assert state["current_step"] == TaskStep.FINALIZE.value
    assert state["is_active"] is False
    assert state["expected_action"] == DONE_ACTION


def test_transition_to_step_of_another_stage_raises(task_machine, created):
    """Шаг обязан принадлежать целевому этапу."""
    task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(
            TASK_ID, TaskStage.EXECUTION.value, TaskStep.REVIEW.value
        )
    assert str(excinfo.value) == "шаг review не принадлежит этапу execution"


def test_transition_to_done_requires_finalize_step(task_machine):
    """У done единственный шаг — finalize."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    task_machine.set_flags(TASK_ID, {FLAG_VALIDATION_PASSED: True})
    with pytest.raises(InvalidTransitionError):
        task_machine.transition_to(
            TASK_ID, TaskStage.DONE.value, TaskStep.REVIEW.value
        )


def test_transition_to_paused_keeps_current_step(task_machine, created):
    """Переход в paused без сохранения шага — ошибка: пауза задачу не двигает."""
    with pytest.raises(InvalidTransitionError) as excinfo:
        task_machine.transition_to(
            TASK_ID, TaskStage.PAUSED.value, TaskStep.CREATE_PLAN.value, PAUSED_ACTION
        )
    assert "пауза сохраняет шаг gather_requirements" in str(excinfo.value)

    state = task_machine.transition_to(TASK_ID, TaskStage.PAUSED.value)
    assert state["stage"] == TaskStage.PAUSED.value
    assert state["paused_from_stage"] == TaskStage.PLANNING.value


def test_transition_resolves_default_step_and_action(task_machine, created):
    """Без step и expected_action берутся первый шаг этапа и текст действия."""
    task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    state = task_machine.transition_to(TASK_ID, TaskStage.EXECUTION.value)

    assert state["current_step"] == TaskStep.IMPLEMENT.value
    assert state["expected_action"] == EXPECTED_ACTIONS[
        (TaskStage.EXECUTION, TaskStep.IMPLEMENT)
    ]


@pytest.mark.parametrize("action", ["", None])
def test_transition_without_action_uses_default(task_machine, created, action):
    """Пустое ожидаемое действие — не ошибка: берётся текст этапа."""
    task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    state = task_machine.transition_to(
        TASK_ID, TaskStage.EXECUTION.value, TaskStep.IMPLEMENT.value, action
    )
    assert state["expected_action"] == EXPECTED_ACTIONS[
        (TaskStage.EXECUTION, TaskStep.IMPLEMENT)
    ]


def test_transition_rejects_too_long_expected_action(task_machine, created):
    """Слишком длинное действие — ошибка ЗАПРОСА (в журнал не пишется)."""
    task_machine.set_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    with pytest.raises(ValueError):
        task_machine.transition_to(
            TASK_ID, TaskStage.EXECUTION.value, TaskStep.IMPLEMENT.value, "х" * 1000
        )


def test_get_state_of_unknown_task_is_none(task_machine):
    """Чтение состояния неизвестной задачи — None (роут отвечает 404)."""
    assert task_machine.get_state("нет-такой") is None


@pytest.mark.parametrize(
    "call",
    [
        lambda m: m.get_full_history("нет-такой"),
        lambda m: m.pause("нет-такой"),
        lambda m: m.resume("нет-такой"),
        lambda m: m.advance_step("нет-такой"),
        lambda m: m.rollback("нет-такой"),
        lambda m: m.transition_to("нет-такой", "execution"),
    ],
    ids=["history", "pause", "resume", "advance", "rollback", "transition"],
)
def test_mutating_unknown_task_raises_not_found(task_machine, call):
    """Любая запись по неизвестному task_id — TaskNotFoundError."""
    with pytest.raises(TaskNotFoundError):
        call(task_machine)
