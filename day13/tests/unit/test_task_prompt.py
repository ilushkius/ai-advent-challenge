"""Тесты текстов состояния задачи для системного промпта (день 13).

Проверяется ровно то, что уходит в промпт: ожидаемое действие по паре
«этап, шаг», перечень уже завершённых этапов и дословный формат одной строки
блока. Тесты идут без БД и без сети — модуль ``task_prompt`` знает только про
``backend/task_fsm.py``.
"""

from __future__ import annotations

import pytest

from backend.domain.task_fsm import TaskStage, TaskStep, steps_of
from backend.domain.task_prompt import (
    DONE_ACTION,
    EXPECTED_ACTIONS,
    PAUSED_ACTION,
    TASK_STATE_HEADER,
    build_prompt_block,
    default_expected_action,
    previous_stages_text,
    render_task_state_block,
)

# Этапы с собственными шагами и собственным ожидаемым действием.
STEPPED_STAGES = (TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION)

# Все пары «этап, шаг», у которых есть действие в EXPECTED_ACTIONS.
ALL_STEP_PAIRS = tuple(
    (stage, step) for stage in STEPPED_STAGES for step in steps_of(stage)
)


@pytest.mark.parametrize("stage, step", ALL_STEP_PAIRS, ids=lambda x: str(x))
def test_default_expected_action_is_a_request_to_the_user(stage, step) -> None:
    """Для активных этапов ожидаемое действие — фраза «ожидается …»."""
    action = default_expected_action(stage, step)
    assert action == EXPECTED_ACTIONS[(stage, step)]
    assert action.startswith("ожидается")


def test_default_expected_action_for_done_and_paused() -> None:
    """У завершённой задачи и у паузы действия не зависят от шага."""
    assert default_expected_action(TaskStage.DONE, TaskStep.FINALIZE) == DONE_ACTION
    assert default_expected_action(TaskStage.PAUSED, TaskStep.IMPLEMENT) == PAUSED_ACTION
    assert DONE_ACTION == "задача завершена; ожидается новая задача"
    assert PAUSED_ACTION == "задача на паузе; ожидается продолжение (resume)"


def test_default_expected_action_for_foreign_pair_raises() -> None:
    """Шаг чужого этапа — явная ошибка, а не пустая строка."""
    with pytest.raises(ValueError):
        default_expected_action(TaskStage.PLANNING, TaskStep.RUN_TESTS)


def test_expected_actions_cover_every_step_of_every_stage() -> None:
    """Пропущенный шаг — это пустое «ожидаемое действие» в промпте."""
    assert set(EXPECTED_ACTIONS) == set(ALL_STEP_PAIRS)
    assert all(action for action in EXPECTED_ACTIONS.values())


@pytest.mark.parametrize(
    "stage, resume_stage, expected",
    [
        (TaskStage.PLANNING, None, "нет"),
        (
            TaskStage.EXECUTION,
            None,
            "planning (gather_requirements, define_scope, create_plan) — завершены",
        ),
        (
            TaskStage.VALIDATION,
            None,
            "planning (gather_requirements, define_scope, create_plan) — завершены; "
            "execution (implement, test_locally) — завершены",
        ),
        (TaskStage.PAUSED, TaskStage.EXECUTION,
         "planning (gather_requirements, define_scope, create_plan) — завершены"),
        (TaskStage.PAUSED, TaskStage.PLANNING, "нет"),
        (TaskStage.PAUSED, None,
         "planning (gather_requirements, define_scope, create_plan) — завершены; "
         "execution (implement, test_locally) — завершены"),
    ],
)
def test_previous_stages_text(stage, resume_stage, expected) -> None:
    """Предыдущие этапы — строго до текущего; у паузы ориентир — этап возврата."""
    assert previous_stages_text(stage, resume_stage) == expected


def test_previous_stages_text_for_done_lists_all_three() -> None:
    """У завершённой задачи пройдены все три рабочих этапа."""
    text = previous_stages_text(TaskStage.DONE)
    assert text.count("— завершены") == 3
    assert text.startswith("planning (")
    assert "validation (review, run_tests, finalize) — завершены" in text


def test_build_prompt_block_is_exactly_one_line() -> None:
    """Формат блока зафиксирован дословно: этап, шаг, действие, предыдущие шаги."""
    block = build_prompt_block(
        TaskStage.EXECUTION,
        TaskStep.IMPLEMENT,
        "ожидается реализация модуля",
    )
    assert block == (
        "Текущий этап: execution. Текущий шаг: implement. "
        "Ожидаемое действие: ожидается реализация модуля. "
        "Предыдущие шаги: planning (gather_requirements, define_scope, "
        "create_plan) — завершены."
    )
    assert "\n" not in block


def test_build_prompt_block_accepts_stored_string_values() -> None:
    """Этап и шаг приходят из БД строкой — блок от этого не меняется."""
    from_enum = build_prompt_block(
        TaskStage.EXECUTION, TaskStep.IMPLEMENT, "ожидается реализация модуля"
    )
    from_str = build_prompt_block(
        "execution", "implement", "ожидается реализация модуля"
    )
    assert from_str == from_enum


def test_build_prompt_block_for_first_step_has_no_previous_stages() -> None:
    """В самом начале задачи завершённых этапов ещё нет."""
    block = build_prompt_block(
        TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS, "ожидается уточнение требований пользователем"
    )
    assert "Текущий этап: planning." in block
    assert "Текущий шаг: gather_requirements." in block
    assert "Предыдущие шаги: нет." in block


def test_build_prompt_block_on_validation_lists_both_finished_stages() -> None:
    """На валидации в «предыдущих» — и планирование, и выполнение."""
    block = build_prompt_block(TaskStage.VALIDATION, TaskStep.REVIEW, "ожидается ревью результата пользователем")
    assert "planning (gather_requirements, define_scope, create_plan) — завершены" in block
    assert "execution (implement, test_locally) — завершены" in block


def test_build_prompt_block_on_pause_keeps_stage_and_step() -> None:
    """На паузе видны и paused, и шаг, на котором встали, и этап возврата."""
    block = build_prompt_block(
        TaskStage.PAUSED, TaskStep.IMPLEMENT, PAUSED_ACTION, resume_stage=TaskStage.EXECUTION
    )
    assert "Текущий этап: paused." in block
    assert "Текущий шаг: implement." in block
    assert PAUSED_ACTION in block
    assert "planning (gather_requirements, define_scope, create_plan) — завершены" in block
    assert "execution (" not in block


@pytest.mark.parametrize(
    "stage, step, expected_action",
    [
        (TaskStage.PLANNING, TaskStep.CREATE_PLAN, "ожидается утверждение плана пользователем"),
        (TaskStage.DONE, TaskStep.FINALIZE, DONE_ACTION),
        (TaskStage.PAUSED, TaskStep.RUN_TESTS, PAUSED_ACTION),
    ],
)
def test_render_task_state_block_starts_with_header(stage, step, expected_action) -> None:
    """В системный промпт уходит заголовок + ровно одна строка состояния."""
    rendered = render_task_state_block(stage, step, expected_action)
    assert rendered.startswith(TASK_STATE_HEADER)
    header, _, body = rendered.partition("\n")
    assert header == TASK_STATE_HEADER
    assert body == build_prompt_block(stage, step, expected_action)
