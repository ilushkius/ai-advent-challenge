"""Поведение TaskStateMachine (день 13): переходы, пауза, откат, ошибки.

Проверяется наблюдаемый контракт машины: с какого этапа можно завести задачу,
куда ведут advance/rollback, что сохраняет пауза, какие ошибки кидаются на
недопустимый переход и на неизвестную задачу. Хранение (журнал, проекция в
словарь, сохранение между перезапусками) проверяется отдельно —
``tests/test_task_store.py``. Сеть и рабочая БД не используются.
"""

from __future__ import annotations

import pytest

from backend.task_fsm import InvalidTaskTransition, TaskStage, TaskStep
from backend.task_prompt import DONE_ACTION, EXPECTED_ACTIONS, PAUSED_ACTION
from backend.task_state import TaskExistsError, TaskNotFoundError, TaskStateMachine

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


@pytest.fixture
def created(task_machine):
    """Задача в состоянии planning/gather_requirements."""
    return task_machine.create(AGENT_ID, TASK_ID)


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
    with pytest.raises(InvalidTaskTransition):
        task_machine.create(AGENT_ID, "tz-nope", initial_stage=stage)


def test_create_rejects_step_of_another_stage(task_machine):
    """Шаг обязан принадлежать стартовому этапу."""
    with pytest.raises(InvalidTaskTransition):
        task_machine.create(
            AGENT_ID, TASK_ID, TaskStage.PLANNING.value,
            initial_step=TaskStep.RUN_TESTS.value,
        )


# ---------- прямой ход ----------
def test_advance_step_walks_the_whole_forward_path(task_machine, created):
    """advance_step проходит все шаги и границы этапов до done включительно."""
    for stage, step in FORWARD_PATH:
        state = task_machine.advance_step(TASK_ID)
        assert (state["stage"], state["current_step"]) == (stage.value, step.value)
        assert state["expected_action"] == EXPECTED_ACTIONS.get((stage, step), DONE_ACTION)

    assert state["is_active"] is False
    assert state["rollback_stage"] is None
    with pytest.raises(InvalidTaskTransition):
        task_machine.advance_step(TASK_ID)


# ---------- пауза и продолжение ----------
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
    assert "Текущий этап: paused." in paused["prompt_block"]

    resumed = task_machine.resume(TASK_ID)
    assert (resumed["stage"], resumed["current_step"]) == (stage.value, step.value)
    assert resumed["expected_action"] == EXPECTED_ACTIONS[(stage, step)]
    assert resumed["paused_from_stage"] is None


def test_pause_from_done_returns_to_done(task_machine, created):
    """Пауза разрешена из любого этапа, включая терминальный done."""
    for _ in FORWARD_PATH:
        task_machine.advance_step(TASK_ID)
    assert task_machine.pause(TASK_ID)["stage"] == TaskStage.PAUSED.value

    resumed = task_machine.resume(TASK_ID)
    assert resumed["stage"] == TaskStage.DONE.value
    assert resumed["current_step"] == TaskStep.FINALIZE.value


def test_pause_twice_raises(task_machine, created):
    """Повторная пауза — явная ошибка."""
    task_machine.pause(TASK_ID)
    with pytest.raises(InvalidTaskTransition):
        task_machine.pause(TASK_ID)


def test_resume_without_pause_raises(task_machine, created):
    """Продолжение задачи, которая не на паузе, — явная ошибка."""
    with pytest.raises(InvalidTaskTransition):
        task_machine.resume(TASK_ID)


def test_step_forward_and_rollback_are_rejected_on_pause(task_machine, created):
    """На паузе задача не двигается: сначала нужно продолжить её."""
    task_machine.pause(TASK_ID)
    with pytest.raises(InvalidTaskTransition):
        task_machine.advance_step(TASK_ID)
    with pytest.raises(InvalidTaskTransition):
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


def test_rollback_from_planning_and_done_raises(task_machine):
    """Откатываться некуда: планирование — первый этап, done — терминальный."""
    task_machine.create(AGENT_ID, "tz-plan")
    with pytest.raises(InvalidTaskTransition):
        task_machine.rollback("tz-plan")

    task_machine.create(AGENT_ID, "tz-done")
    for _ in FORWARD_PATH:
        task_machine.advance_step("tz-done")
    with pytest.raises(InvalidTaskTransition):
        task_machine.rollback("tz-done")


def test_rollback_to_wrong_stage_raises(task_machine):
    """Откат разрешён ровно на один этап назад, не «куда захотелось»."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    with pytest.raises(InvalidTaskTransition):
        task_machine.rollback(TASK_ID, to_stage=TaskStage.PLANNING.value)
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.VALIDATION.value


# ---------- прямой переход ----------
def test_transition_to_done(task_machine):
    """Завершение задачи — прямой переход в done с шагом finalize."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.VALIDATION.value)
    task_machine.advance_step(TASK_ID)  # validation/finalize

    state = task_machine.transition_to(
        TASK_ID, TaskStage.DONE.value, TaskStep.FINALIZE.value, DONE_ACTION,
        reason="задача завершена",
    )
    assert state["stage"] == TaskStage.DONE.value
    assert state["current_step"] == TaskStep.FINALIZE.value
    assert state["is_active"] is False
    assert state["expected_action"] == DONE_ACTION


def test_transition_to_invalid_pair_raises(task_machine, created):
    """Недопустимая пара этапов — явная ошибка, состояние не меняется."""
    with pytest.raises(InvalidTaskTransition):
        task_machine.transition_to(
            TASK_ID, TaskStage.VALIDATION.value, TaskStep.REVIEW.value, "ожидается ревью"
        )
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.PLANNING.value


def test_transition_to_step_of_another_stage_raises(task_machine, created):
    """Шаг обязан принадлежать целевому этапу."""
    with pytest.raises(InvalidTaskTransition):
        task_machine.transition_to(
            TASK_ID, TaskStage.EXECUTION.value, TaskStep.REVIEW.value, "ожидается ревью"
        )


def test_transition_to_done_requires_finalize_step(task_machine, created):
    """У done единственный шаг — finalize."""
    with pytest.raises(InvalidTaskTransition):
        task_machine.transition_to(
            TASK_ID, TaskStage.DONE.value, TaskStep.REVIEW.value, DONE_ACTION
        )


def test_transition_to_paused_keeps_current_step(task_machine, created):
    """Переход в paused без сохранения шага — ошибка: пауза задачу не двигает."""
    with pytest.raises(InvalidTaskTransition):
        task_machine.transition_to(
            TASK_ID, TaskStage.PAUSED.value, TaskStep.CREATE_PLAN.value, PAUSED_ACTION
        )
    state = task_machine.transition_to(
        TASK_ID, TaskStage.PAUSED.value, TaskStep.GATHER_REQUIREMENTS.value, PAUSED_ACTION
    )
    assert state["stage"] == TaskStage.PAUSED.value
    assert state["paused_from_stage"] == TaskStage.PLANNING.value


def test_transition_requires_usable_expected_action(task_machine, created):
    """Пустое или слишком длинное ожидаемое действие — ошибка."""
    with pytest.raises(ValueError):
        task_machine.transition_to(
            TASK_ID, TaskStage.EXECUTION.value, TaskStep.IMPLEMENT.value, ""
        )
    with pytest.raises(ValueError):
        task_machine.transition_to(
            TASK_ID, TaskStage.EXECUTION.value, TaskStep.IMPLEMENT.value,
            "х" * 1000,
        )


def test_transition_unknown_stage_value_raises(task_machine, created):
    """Значение этапа вне Enum — явная ошибка."""
    with pytest.raises(ValueError):
        task_machine.transition_to(
            TASK_ID, "нет-такого", TaskStep.IMPLEMENT.value, "ожидается реализация"
        )


# ---------- список и валидация ----------
def test_is_valid_transition_delegates_to_fsm():
    """Тот же ответ, что у таблицы переходов FSM (в т.ч. на неизвестном этапе)."""
    assert TaskStateMachine.is_valid_transition("validation", "execution") is True
    assert TaskStateMachine.is_valid_transition("done", "execution") is False
    with pytest.raises(ValueError):
        TaskStateMachine.is_valid_transition("нет-такого", "done")


# ---------- неизвестная задача ----------
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
        lambda m: m.transition_to("нет-такой", "execution", "implement", "ожидается"),
    ],
    ids=["history", "pause", "resume", "advance", "rollback", "transition"],
)
def test_mutating_unknown_task_raises_not_found(task_machine, call):
    """Любая запись по неизвестному task_id — TaskNotFoundError."""
    with pytest.raises(TaskNotFoundError):
        call(task_machine)
