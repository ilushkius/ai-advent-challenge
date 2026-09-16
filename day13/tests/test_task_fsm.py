"""Тесты стейт-машины состояния задачи (день 13, ``backend/task_fsm.py``).

Что здесь проверяется: таблица переходов «этап × событие», шаги внутри этапа,
явные ошибки на недопустимый переход и на неизвестное событие. Тесты идут без
сети и без БД — модуль ``task_fsm`` не знает ни про SQLAlchemy, ни про FastAPI,
ни про Streamlit.

Форма — как в ``tests/test_context_fsm.py``: таблица переходов объявлена
модульной константой ``TRANSITIONS`` и служит единственным источником правды,
а тест параметризуется по ВСЕМ парам «этап × событие».
"""

from __future__ import annotations

import pytest

from backend.task_fsm import (
    STAGE_BY_VALUE,
    STAGE_CLASS_BY_STAGE,
    STEP_BY_VALUE,
    STAGE_ORDER,
    STAGE_STEPS,
    STAGE_TRANSITIONS,
    DoneState,
    ExecutionState,
    InvalidTaskTransition,
    PausedState,
    PlanningState,
    TaskEvent,
    TaskStage,
    TaskStageBase,
    TaskStep,
    UnknownTaskEvent,
    first_step,
    is_valid_transition,
    next_step,
    rollback_target,
    stage_from_value,
    stage_state_from_value,
    step_from_value,
    steps_of,
)

# Этап, в который возвращает PausedState (для пары «paused × resume»).
RESUME_STAGE = TaskStage.EXECUTION

# Шаг-представитель каждого этапа: вход, на котором проверяется таблица переходов.
STAGE_SAMPLE_STEP: dict[TaskStage, TaskStep] = {
    TaskStage.PLANNING: TaskStep.GATHER_REQUIREMENTS,
    TaskStage.EXECUTION: TaskStep.IMPLEMENT,
    TaskStage.VALIDATION: TaskStep.REVIEW,
    TaskStage.DONE: TaskStep.FINALIZE,
    TaskStage.PAUSED: TaskStep.IMPLEMENT,
}

# Таблица переходов — ЕДИНСТВЕННЫЙ источник правды и наглядная диаграмма.
# Если пары (этап, событие) здесь нет — ожидаем ошибку из EXPECTED_ERRORS.
TRANSITIONS: dict[TaskStage, dict[TaskEvent, tuple[TaskStage, TaskStep]]] = {
    TaskStage.PLANNING: {
        TaskEvent.ADVANCE: (TaskStage.PLANNING, TaskStep.DEFINE_SCOPE),
        TaskEvent.PAUSE: (TaskStage.PAUSED, TaskStep.GATHER_REQUIREMENTS),
    },
    TaskStage.EXECUTION: {
        TaskEvent.ADVANCE: (TaskStage.EXECUTION, TaskStep.TEST_LOCALLY),
        TaskEvent.ROLLBACK: (TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS),
        TaskEvent.PAUSE: (TaskStage.PAUSED, TaskStep.IMPLEMENT),
    },
    TaskStage.VALIDATION: {
        TaskEvent.ADVANCE: (TaskStage.VALIDATION, TaskStep.RUN_TESTS),
        TaskEvent.ROLLBACK: (TaskStage.EXECUTION, TaskStep.IMPLEMENT),
        TaskEvent.PAUSE: (TaskStage.PAUSED, TaskStep.REVIEW),
    },
    TaskStage.DONE: {
        TaskEvent.PAUSE: (TaskStage.PAUSED, TaskStep.FINALIZE),
    },
    TaskStage.PAUSED: {
        TaskEvent.RESUME: (RESUME_STAGE, TaskStep.IMPLEMENT),
    },
}

# Пары вне TRANSITIONS: недопустимый переход или событие, которого у этапа нет.
EXPECTED_ERRORS: dict[TaskStage, dict[TaskEvent, type[Exception]]] = {
    TaskStage.PLANNING: {
        TaskEvent.ROLLBACK: InvalidTaskTransition,
        TaskEvent.RESUME: UnknownTaskEvent,
    },
    TaskStage.EXECUTION: {TaskEvent.RESUME: UnknownTaskEvent},
    TaskStage.VALIDATION: {TaskEvent.RESUME: UnknownTaskEvent},
    TaskStage.DONE: {
        TaskEvent.ADVANCE: InvalidTaskTransition,
        TaskEvent.ROLLBACK: InvalidTaskTransition,
        TaskEvent.RESUME: UnknownTaskEvent,
    },
    TaskStage.PAUSED: {
        TaskEvent.ADVANCE: InvalidTaskTransition,
        TaskEvent.ROLLBACK: InvalidTaskTransition,
        TaskEvent.PAUSE: InvalidTaskTransition,
    },
}


def make_state(stage: TaskStage) -> TaskStageBase:
    """Объект этапа для теста: у paused обязателен этап возврата."""
    if stage is TaskStage.PAUSED:
        return PausedState(RESUME_STAGE)
    return STAGE_CLASS_BY_STAGE[stage]()


@pytest.mark.parametrize("stage", list(TaskStage), ids=lambda s: s.value)
@pytest.mark.parametrize("event", list(TaskEvent), ids=lambda e: e.value)
def test_transition_table(stage: TaskStage, event: TaskEvent) -> None:
    """Каждая пара «этап × событие» даёт ровно один результат.

    Пара из TRANSITIONS → точная пара «этап, шаг»; пара вне таблицы →
    объявленная ошибка (недопустимый переход или неописанное событие).
    """
    step = STAGE_SAMPLE_STEP[stage]
    state = make_state(stage)
    expected = TRANSITIONS.get(stage, {}).get(event)

    if expected is not None:
        assert state.handle(event, step) == expected
        return

    with pytest.raises(EXPECTED_ERRORS[stage][event]):
        state.handle(event, step)


@pytest.mark.parametrize(
    "stage, step, expected",
    [
        (TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS, TaskStep.DEFINE_SCOPE),
        (TaskStage.PLANNING, TaskStep.DEFINE_SCOPE, TaskStep.CREATE_PLAN),
        (TaskStage.EXECUTION, TaskStep.IMPLEMENT, TaskStep.TEST_LOCALLY),
        (TaskStage.VALIDATION, TaskStep.REVIEW, TaskStep.RUN_TESTS),
        (TaskStage.VALIDATION, TaskStep.RUN_TESTS, TaskStep.FINALIZE),
    ],
)
def test_advance_inside_stage(stage, step, expected) -> None:
    """ADVANCE не на последнем шаге этапа оставляет этап и берёт следующий шаг."""
    new_stage, new_step = make_state(stage).handle(TaskEvent.ADVANCE, step)
    assert (new_stage, new_step) == (stage, expected)


@pytest.mark.parametrize(
    "stage, step, expected_stage, expected_step",
    [
        (TaskStage.PLANNING, TaskStep.CREATE_PLAN, TaskStage.EXECUTION, TaskStep.IMPLEMENT),
        (TaskStage.EXECUTION, TaskStep.TEST_LOCALLY, TaskStage.VALIDATION, TaskStep.REVIEW),
        (TaskStage.VALIDATION, TaskStep.FINALIZE, TaskStage.DONE, TaskStep.FINALIZE),
    ],
)
def test_advance_crosses_stage_border(stage, step, expected_stage, expected_step) -> None:
    """ADVANCE с последнего шага этапа переводит в первый шаг следующего этапа."""
    new_stage, new_step = make_state(stage).handle(TaskEvent.ADVANCE, step)
    assert (new_stage, new_step) == (expected_stage, expected_step)


def test_rollback_targets_first_step_of_previous_stage() -> None:
    """ROLLBACK возвращает в ПЕРВЫЙ шаг предыдущего этапа, а не в сохранённый."""
    assert ExecutionState().handle(TaskEvent.ROLLBACK, TaskStep.TEST_LOCALLY) == (
        TaskStage.PLANNING,
        TaskStep.GATHER_REQUIREMENTS,
    )
    validation = STAGE_CLASS_BY_STAGE[TaskStage.VALIDATION]()
    assert validation.handle(TaskEvent.ROLLBACK, TaskStep.FINALIZE) == (
        TaskStage.EXECUTION,
        TaskStep.IMPLEMENT,
    )


@pytest.mark.parametrize(
    "stage",
    [stage for stage in TaskStage if stage is not TaskStage.PAUSED],
    ids=lambda s: s.value,
)
def test_pause_keeps_step(stage: TaskStage) -> None:
    """PAUSE сохраняет текущий шаг — его же вернёт RESUME."""
    step = STAGE_SAMPLE_STEP[stage]
    assert make_state(stage).handle(TaskEvent.PAUSE, step) == (TaskStage.PAUSED, step)


@pytest.mark.parametrize("stage", list(TaskStage), ids=lambda s: s.value)
def test_paused_resume_returns_to_saved_stage_and_step(stage: TaskStage) -> None:
    """PausedState помнит этап возврата и не трогает шаг."""
    step = STAGE_SAMPLE_STEP[stage]
    assert PausedState(stage).handle(TaskEvent.RESUME, step) == (stage, step)


def test_pause_from_done_and_rollback_from_planning_are_explicit_errors() -> None:
    """Недопустимые переходы — явные ошибки, а не тихий переход."""
    with pytest.raises(InvalidTaskTransition):
        make_state(TaskStage.PLANNING).handle(TaskEvent.ROLLBACK, TaskStep.DEFINE_SCOPE)
    with pytest.raises(InvalidTaskTransition):
        DoneState().handle(TaskEvent.ADVANCE, TaskStep.FINALIZE)
    with pytest.raises(InvalidTaskTransition):
        PausedState(RESUME_STAGE).handle(TaskEvent.ADVANCE, TaskStep.IMPLEMENT)


def test_unknown_event_message_names_event_and_stage() -> None:
    """UnknownTaskEvent — Exception с читаемым текстом: событие и этап."""
    with pytest.raises(UnknownTaskEvent) as excinfo:
        ExecutionState().handle(TaskEvent.RESUME, TaskStep.IMPLEMENT)

    message = str(excinfo.value)
    assert TaskEvent.RESUME.value in message
    assert TaskStage.EXECUTION.value in message


@pytest.mark.parametrize(
    "from_stage, to_stage, expected",
    [
        ("planning", "execution", True),
        ("execution", "validation", True),
        ("validation", "done", True),
        ("validation", "execution", True),
        ("execution", "planning", True),
        ("planning", "paused", True),
        ("execution", "paused", True),
        ("validation", "paused", True),
        ("done", "paused", True),
        ("paused", "planning", True),
        ("paused", "execution", True),
        ("paused", "validation", True),
        ("paused", "done", True),
        ("planning", "validation", False),
        ("planning", "done", False),
        ("execution", "done", False),
        ("done", "execution", False),
        ("done", "validation", False),
        ("done", "planning", False),
        ("planning", "planning", False),
        ("execution", "execution", False),
        ("validation", "validation", False),
        ("paused", "paused", False),
    ],
)
def test_is_valid_transition(from_stage, to_stage, expected) -> None:
    """Допустимость перехода описывается одной таблицей STAGE_TRANSITIONS."""
    assert is_valid_transition(from_stage, to_stage) is expected


def test_is_valid_transition_accepts_enum_members() -> None:
    """Аргументы — и строки, и члены Enum (состояние из БД приходит строкой)."""
    assert is_valid_transition(TaskStage.VALIDATION, TaskStage.DONE) is True
    assert is_valid_transition(TaskStage.DONE, TaskStage.EXECUTION) is False


def test_is_valid_transition_unknown_stage_raises() -> None:
    """Неизвестный этап — явный ValueError, а не «False по умолчанию»."""
    with pytest.raises(ValueError):
        is_valid_transition("нет-такого", "done")


def test_stage_and_step_from_value_roundtrip() -> None:
    """Значения Enum и строки из БД согласованы."""
    for stage in TaskStage:
        assert stage_from_value(stage.value) is STAGE_BY_VALUE[stage.value]
        assert stage_from_value(stage.value) is stage
    for step in TaskStep:
        assert step_from_value(step.value) is STEP_BY_VALUE[step.value]
        assert step_from_value(step.value) is step


@pytest.mark.parametrize("value", ["", "нет-такого", "PLANNING", "planing"])
def test_stage_from_value_unknown_raises(value: str) -> None:
    """Неизвестное значение этапа — явный ValueError."""
    with pytest.raises(ValueError):
        stage_from_value(value)


def test_step_from_value_unknown_raises() -> None:
    """Неизвестное значение шага — явный ValueError."""
    with pytest.raises(ValueError):
        step_from_value("нет-такого")


def test_steps_of_each_stage() -> None:
    """Шаги этапов объявлены таблицей STAGE_STEPS; у done и paused их нет."""
    assert steps_of(TaskStage.PLANNING) == (
        TaskStep.GATHER_REQUIREMENTS,
        TaskStep.DEFINE_SCOPE,
        TaskStep.CREATE_PLAN,
    )
    assert steps_of(TaskStage.EXECUTION) == (TaskStep.IMPLEMENT, TaskStep.TEST_LOCALLY)
    assert steps_of(TaskStage.VALIDATION) == (
        TaskStep.REVIEW,
        TaskStep.RUN_TESTS,
        TaskStep.FINALIZE,
    )
    assert steps_of(TaskStage.DONE) == ()
    assert steps_of(TaskStage.PAUSED) == ()
    assert STAGE_STEPS[TaskStage.DONE] == ()


def test_first_step_of_each_stage() -> None:
    """first_step — первый шаг активных этапов; у done остаётся finalize.

    Это значение хранится в task_states.current_step у завершённой задачи,
    поэтому у done шаг не пустой.
    """
    assert first_step(TaskStage.PLANNING) is TaskStep.GATHER_REQUIREMENTS
    assert first_step(TaskStage.EXECUTION) is TaskStep.IMPLEMENT
    assert first_step(TaskStage.VALIDATION) is TaskStep.REVIEW
    assert first_step(TaskStage.DONE) is TaskStep.FINALIZE


def test_first_step_of_paused_raises() -> None:
    """У paused нет собственных шагов — явная ошибка."""
    with pytest.raises(InvalidTaskTransition):
        first_step(TaskStage.PAUSED)


def test_next_step_and_last_step() -> None:
    """next_step даёт следующий шаг этапа, на последнем — None."""
    assert next_step(TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS) is TaskStep.DEFINE_SCOPE
    assert next_step(TaskStage.PLANNING, TaskStep.CREATE_PLAN) is None
    assert next_step(TaskStage.VALIDATION, TaskStep.FINALIZE) is None


def test_next_step_of_foreign_step_raises() -> None:
    """Шаг другого этапа — явная ошибка, а не «None»."""
    with pytest.raises(ValueError):
        next_step(TaskStage.PLANNING, TaskStep.RUN_TESTS)


@pytest.mark.parametrize(
    "stage, expected",
    [
        (TaskStage.PLANNING, None),
        (TaskStage.EXECUTION, TaskStage.PLANNING),
        (TaskStage.VALIDATION, TaskStage.EXECUTION),
        (TaskStage.DONE, None),
        (TaskStage.PAUSED, None),
    ],
)
def test_rollback_target(stage: TaskStage, expected) -> None:
    """Откат возможен только на один этап назад по STAGE_ORDER."""
    assert rollback_target(stage) is expected


def test_stage_order_is_forward_path() -> None:
    """STAGE_ORDER — прямой ход задачи без paused (её место задаёт метка паузы)."""
    assert STAGE_ORDER == (
        TaskStage.PLANNING,
        TaskStage.EXECUTION,
        TaskStage.VALIDATION,
        TaskStage.DONE,
    )
    assert TaskStage.PAUSED not in STAGE_ORDER


def test_stage_state_from_value_restores_states() -> None:
    """stage_state_from_value восстанавливает объект этапа по значению из БД."""
    for stage in TaskStage:
        state = stage_state_from_value(stage.value, resume_stage=RESUME_STAGE)
        assert isinstance(state, STAGE_CLASS_BY_STAGE[stage])
        assert state.stage is stage
        assert str(state) == stage.value


def test_stage_state_from_value_paused_requires_resume_stage() -> None:
    """У paused этап возврата обязателен — без него восстановить нечего."""
    with pytest.raises(ValueError):
        stage_state_from_value(TaskStage.PAUSED.value)
    state = stage_state_from_value(TaskStage.PAUSED.value, resume_stage=RESUME_STAGE)
    assert state.handle(TaskEvent.RESUME, TaskStep.IMPLEMENT) == (
        RESUME_STAGE,
        TaskStep.IMPLEMENT,
    )


def test_no_side_effects_on_import() -> None:
    """Классы состояний не хранят состояние: экземпляры независимы."""
    assert PlanningState() is not PlanningState()
    assert PlanningState().stage is TaskStage.PLANNING
    assert str(PlanningState()) == "planning"
    assert DoneState().stage is TaskStage.DONE


def test_stage_transitions_table_matches_state_classes() -> None:
    """STAGE_TRANSITIONS объявлена до классов и не расходится с их поведением."""
    assert STAGE_TRANSITIONS[TaskStage.PLANNING] == frozenset(
        {TaskStage.EXECUTION, TaskStage.PAUSED}
    )
    assert STAGE_TRANSITIONS[TaskStage.EXECUTION] == frozenset(
        {TaskStage.VALIDATION, TaskStage.PLANNING, TaskStage.PAUSED}
    )
    assert STAGE_TRANSITIONS[TaskStage.VALIDATION] == frozenset(
        {TaskStage.DONE, TaskStage.EXECUTION, TaskStage.PAUSED}
    )
    assert STAGE_TRANSITIONS[TaskStage.DONE] == frozenset({TaskStage.PAUSED})
    assert STAGE_TRANSITIONS[TaskStage.PAUSED] == frozenset(
        {TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION, TaskStage.DONE}
    )
