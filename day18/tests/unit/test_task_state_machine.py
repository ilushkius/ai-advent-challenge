"""Тесты графа допуска и guard-условий состояния задачи (день 15).

Что здесь проверяется: какие переходы этапов вообще допустимы
(``ALLOWED_TRANSITIONS``), что дополнительно требуют guard-условия (флаги
``plan_approved``, ``implementation_complete``, ``validation_passed`` и этап
паузы), какие тексты отказа и подсказки получает пользователь, какие флаги
сбрасывает движение назад и как из этого собираются списки ``allowed_next`` и
``blocked`` для API и интерфейса.

Тесты идут без БД, сети и UI: модуль знает только про ``enum``-члены
``backend/domain/task_fsm.py``. Форма — как в ``test_task_fsm.py``: таблица
пар «этап → этап» объявлена модульной константой и параметризует тесты.
"""

from __future__ import annotations

import itertools

import pytest

from backend.domain.task_fsm import (
    STAGE_CLASS_BY_STAGE,
    STAGE_ORDER,
    InvalidTransitionError,
    TaskEvent,
    TaskStage,
    TaskStep,
    UnknownTaskEvent,
)
from backend.domain.task_state_machine import (
    ALLOWED_TRANSITIONS,
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_PLAN_APPROVED,
    FLAG_VALIDATION_PASSED,
    GUARDS,
    STAGE_DISPLAY_ORDER,
    STAGE_FLAG,
    TASK_FLAGS,
    can_transition,
    cleared_flags,
    get_allowed_next_stages,
    get_blocked_stages,
    guard_context,
    is_transition_allowed,
)

# Пары, которые разрешает граф: (planning→execution|paused, execution→validation|
# planning|paused, validation→done|execution|paused, paused→планирование/выполнение/
# валидация). Всё остальное — отказ.
ALLOWED_PAIRS = frozenset({
    (TaskStage.PLANNING, TaskStage.EXECUTION),
    (TaskStage.PLANNING, TaskStage.PAUSED),
    (TaskStage.EXECUTION, TaskStage.VALIDATION),
    (TaskStage.EXECUTION, TaskStage.PLANNING),
    (TaskStage.EXECUTION, TaskStage.PAUSED),
    (TaskStage.VALIDATION, TaskStage.DONE),
    (TaskStage.VALIDATION, TaskStage.EXECUTION),
    (TaskStage.VALIDATION, TaskStage.PAUSED),
    (TaskStage.PAUSED, TaskStage.PLANNING),
    (TaskStage.PAUSED, TaskStage.EXECUTION),
    (TaskStage.PAUSED, TaskStage.VALIDATION),
})

ALL_PAIRS = list(itertools.product(TaskStage, TaskStage))

# Шаг-представитель каждого этапа: вход, на котором проверяются классы этапов.
SAMPLE_STEP: dict[TaskStage, TaskStep] = {
    TaskStage.PLANNING: TaskStep.GATHER_REQUIREMENTS,
    TaskStage.EXECUTION: TaskStep.IMPLEMENT,
    TaskStage.VALIDATION: TaskStep.REVIEW,
    TaskStage.DONE: TaskStep.FINALIZE,
    TaskStage.PAUSED: TaskStep.IMPLEMENT,
}

# Все флаги «как будто пользователь их отметил».
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


# ---------- граф ----------
def test_allowed_transitions_covers_every_stage() -> None:
    """Граф описан для всех пяти этапов; done — терминальный, paused — три этапа."""
    assert set(ALLOWED_TRANSITIONS) == set(TaskStage)
    assert ALLOWED_TRANSITIONS[TaskStage.DONE] == frozenset()
    assert ALLOWED_TRANSITIONS[TaskStage.PAUSED] == frozenset({
        TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION,
    })


@pytest.mark.parametrize("pair", ALL_PAIRS, ids=lambda p: f"{p[0].value}->{p[1].value}")
def test_can_transition_matrix(pair) -> None:
    """Проверка по графу: разрешена ровно объявленная пара, и ничего кроме."""
    assert can_transition(pair[0], pair[1]) is (pair in ALLOWED_PAIRS)


def test_can_transition_accepts_strings_and_enum_members() -> None:
    """Этап из БД приходит строкой — ответ от формы аргумента не зависит."""
    assert can_transition("planning", "execution") is True
    assert can_transition(TaskStage.VALIDATION, TaskStage.DONE) is True
    assert can_transition("done", "execution") is False


@pytest.mark.parametrize("pair", [("нет-такого", "done"), ("done", "нет-такого")])
def test_can_transition_unknown_stage_raises(pair) -> None:
    """Неизвестный этап — явный ValueError, а не «False по умолчанию»."""
    with pytest.raises(ValueError):
        can_transition(*pair)


def test_stage_display_order_is_forward_path_plus_paused() -> None:
    """Порядок отображения этапов: прямой ход и пауза в конце."""
    assert STAGE_DISPLAY_ORDER == STAGE_ORDER + (TaskStage.PAUSED,)


def test_task_flags_and_stage_flag_table() -> None:
    """Флаги этапов объявлены одной таблицей; у done и paused своего флага нет."""
    assert TASK_FLAGS == (
        FLAG_PLAN_APPROVED, FLAG_IMPLEMENTATION_COMPLETE, FLAG_VALIDATION_PASSED,
    )
    assert STAGE_FLAG == {
        TaskStage.PLANNING: FLAG_PLAN_APPROVED,
        TaskStage.EXECUTION: FLAG_IMPLEMENTATION_COMPLETE,
        TaskStage.VALIDATION: FLAG_VALIDATION_PASSED,
    }


# ---------- guards ----------
def test_guards_cover_exactly_the_rule_pairs() -> None:
    """Guard описан у трёх прямых переходов и у трёх выходов из паузы."""
    assert set(GUARDS) == {
        (TaskStage.PLANNING, TaskStage.EXECUTION),
        (TaskStage.EXECUTION, TaskStage.VALIDATION),
        (TaskStage.VALIDATION, TaskStage.DONE),
        (TaskStage.PAUSED, TaskStage.PLANNING),
        (TaskStage.PAUSED, TaskStage.EXECUTION),
        (TaskStage.PAUSED, TaskStage.VALIDATION),
    }


@pytest.mark.parametrize(
    "pair, flag",
    [
        ((TaskStage.PLANNING, TaskStage.EXECUTION), FLAG_PLAN_APPROVED),
        ((TaskStage.EXECUTION, TaskStage.VALIDATION), FLAG_IMPLEMENTATION_COMPLETE),
        ((TaskStage.VALIDATION, TaskStage.DONE), FLAG_VALIDATION_PASSED),
    ],
    ids=lambda x: str(x),
)
@pytest.mark.parametrize(
    "flag_value, expected",
    [(True, True), (False, False), (None, False), ("true", False), (1, False)],
)
def test_forward_guard_requires_flag_is_true(pair, flag, flag_value, expected) -> None:
    """Прямой переход открыт только при флаге, выставленном именно в True."""
    context = {} if flag_value is None else {flag: flag_value}
    assert GUARDS[pair](make_ctx(context)) is expected


@pytest.mark.parametrize(
    "pair",
    [pair for pair in ALL_PAIRS if pair not in GUARDS],
    ids=lambda p: f"{p[0].value}->{p[1].value}",
)
def test_guards_absent_means_transition_allowed_by_the_graph(pair) -> None:
    """Пары без guard решает только граф (откаты, переходы в паузу)."""
    expected = pair in ALLOWED_PAIRS
    assert is_transition_allowed(pair[0], pair[1], make_ctx(ALL_FLAGS)) is expected


@pytest.mark.parametrize(
    "paused_from, context, target, expected",
    [
        # Из паузы всегда можно вернуться в свой же этап.
        ("planning", {}, TaskStage.PLANNING, True),
        ("execution", {}, TaskStage.EXECUTION, True),
        ("validation", {}, TaskStage.VALIDATION, True),
        # В другой этап — только если он и так доступен из этапа паузы.
        ("planning", {}, TaskStage.EXECUTION, False),
        ("planning", {FLAG_PLAN_APPROVED: True}, TaskStage.EXECUTION, True),
        ("execution", {}, TaskStage.VALIDATION, False),
        (
            "execution",
            {FLAG_IMPLEMENTATION_COMPLETE: True},
            TaskStage.VALIDATION,
            True,
        ),
        # validation -> execution — обычный откат, он открыт всегда.
        ("validation", {}, TaskStage.EXECUTION, True),
        # Без сохранённого этапа паузы продолжать некуда.
        (None, {}, TaskStage.EXECUTION, False),
    ],
    ids=lambda x: str(x),
)
def test_resume_guard(paused_from, context, target, expected) -> None:
    """Guard паузы: свой этап или следующий доступный из него."""
    guard = GUARDS[(TaskStage.PAUSED, target)]
    assert guard(make_ctx(context, paused_from=paused_from)) is expected


# ---------- списки допустимых и заблокированных этапов ----------
@pytest.mark.parametrize(
    "stage, context, paused_from, expected",
    [
        (TaskStage.PLANNING, {}, None, ["paused"]),
        (TaskStage.PLANNING, {FLAG_PLAN_APPROVED: True}, None, ["execution", "paused"]),
        (TaskStage.EXECUTION, {}, None, ["planning", "paused"]),
        (
            TaskStage.EXECUTION,
            {FLAG_IMPLEMENTATION_COMPLETE: True},
            None,
            ["planning", "validation", "paused"],
        ),
        (TaskStage.VALIDATION, {}, None, ["execution", "paused"]),
        (
            TaskStage.VALIDATION,
            {FLAG_VALIDATION_PASSED: True},
            None,
            ["execution", "done", "paused"],
        ),
        (TaskStage.DONE, ALL_FLAGS, None, []),
        (TaskStage.PAUSED, {}, "planning", ["planning"]),
        (TaskStage.PAUSED, {}, "execution", ["planning", "execution"]),
        (
            TaskStage.PAUSED,
            {FLAG_IMPLEMENTATION_COMPLETE: True},
            "execution",
            ["planning", "execution", "validation"],
        ),
        (TaskStage.PAUSED, {}, "validation", ["execution", "validation"]),
        (TaskStage.PAUSED, {}, None, []),
    ],
    ids=lambda x: str(x),
)
def test_get_allowed_next_stages(stage, context, paused_from, expected) -> None:
    """Допустимые следующие этапы — точный список в порядке отображения."""
    result = get_allowed_next_stages(stage, make_ctx(context, paused_from=paused_from))
    assert [item.value for item in result] == expected


@pytest.mark.parametrize("stage", list(TaskStage), ids=lambda s: s.value)
def test_get_blocked_stages_explains_every_other_stage(stage: TaskStage) -> None:
    """Каждый недоступный этап назван ровно один раз и с непустой причиной."""
    context = make_ctx(ALL_FLAGS, paused_from="execution" if stage is TaskStage.PAUSED else None)
    blocked = get_blocked_stages(stage, context)
    blocked_stages = [item[0] for item in blocked]

    assert len(blocked_stages) == len(set(blocked_stages))
    assert stage not in blocked_stages
    allowed = set(get_allowed_next_stages(stage, context))
    assert set(blocked_stages) == set(STAGE_DISPLAY_ORDER) - allowed - {stage}
    assert all(reason for _, reason in blocked)


# ---------- сброс флагов ----------
@pytest.mark.parametrize(
    "from_stage, to_stage, expected",
    [
        (TaskStage.VALIDATION, TaskStage.PLANNING,
         (FLAG_PLAN_APPROVED, FLAG_IMPLEMENTATION_COMPLETE, FLAG_VALIDATION_PASSED)),
        (TaskStage.EXECUTION, TaskStage.PLANNING,
         (FLAG_PLAN_APPROVED, FLAG_IMPLEMENTATION_COMPLETE, FLAG_VALIDATION_PASSED)),
        (TaskStage.VALIDATION, TaskStage.EXECUTION,
         (FLAG_IMPLEMENTATION_COMPLETE, FLAG_VALIDATION_PASSED)),
        (TaskStage.PLANNING, TaskStage.EXECUTION, ()),
        (TaskStage.EXECUTION, TaskStage.VALIDATION, ()),
        (TaskStage.VALIDATION, TaskStage.DONE, ()),
        (TaskStage.PLANNING, TaskStage.PAUSED, ()),
        (TaskStage.VALIDATION, TaskStage.PAUSED, ()),
        (TaskStage.PAUSED, TaskStage.PLANNING, ()),
        (TaskStage.VALIDATION, TaskStage.VALIDATION, ()),
        (TaskStage.PLANNING, TaskStage.PLANNING, ()),
    ],
    ids=lambda x: getattr(x, "value", str(x)),
)
def test_cleared_flags(from_stage, to_stage, expected) -> None:
    """Движение назад сбрасывает согласования этапа-цели и всех следующих."""
    assert cleared_flags(from_stage, to_stage) == expected


# ---------- guard-контекст ----------
def test_guard_context_merges_flags_and_derived_fields() -> None:
    """Guard-контекст — это context строки плюс этап, шаг и метка паузы."""
    state = {
        "stage": TaskStage.PAUSED.value,
        "current_step": TaskStep.REVIEW.value,
        "paused_from_stage": TaskStage.VALIDATION.value,
        "context": {FLAG_VALIDATION_PASSED: True, "task_id": "tz"},
    }
    ctx = guard_context(state)

    assert ctx[FLAG_VALIDATION_PASSED] is True
    assert ctx["task_id"] == "tz"
    assert ctx["stage"] == TaskStage.PAUSED.value
    assert ctx["current_step"] == TaskStep.REVIEW.value
    assert ctx["paused_from_stage"] == TaskStage.VALIDATION.value
    # Контекст строки не мутируется: это копия.
    assert state["context"] == {FLAG_VALIDATION_PASSED: True, "task_id": "tz"}


def test_guard_context_without_context_key() -> None:
    """Отсутствие context — не ошибка: этап и шаг всё равно попадают в контекст."""
    ctx = guard_context({"stage": "planning"})
    assert ctx["stage"] == "planning"
    assert ctx["current_step"] is None
    assert ctx["paused_from_stage"] is None


# ---------- согласованность графа и классов этапов ----------
def test_state_classes_only_target_allowed_stages() -> None:
    """Классы этапов не расходились с графом: их цель — тот же этап или из графа."""
    for stage in TaskStage:
        state = STAGE_CLASS_BY_STAGE[stage](TaskStage.EXECUTION) if stage is TaskStage.PAUSED \
            else STAGE_CLASS_BY_STAGE[stage]()
        for event in TaskEvent:
            try:
                target, _ = state.handle(event, SAMPLE_STEP[stage])
            except (InvalidTransitionError, UnknownTaskEvent):
                continue  # недопустимый переход или неописанное событие — норма
            assert target is stage or target in ALLOWED_TRANSITIONS[stage], (
                f"{stage.value} + {event.value} -> {target.value}"
            )
