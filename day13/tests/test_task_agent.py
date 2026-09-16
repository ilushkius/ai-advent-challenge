"""Тесты подключения состояния задачи к агенту (день 13, ``backend/agent.py``).

Главное, что здесь проверяется: блок состояния — часть СИСТЕМНОГО ПРОМПТА
каждого запроса, реплика пользователя обновляет состояние автоматически, а
состояние читается из БД (переживает пересборку агента). Тесты идут без сети:
клиент DeepSeek подменяется фейком.
"""

from __future__ import annotations

import pytest

from backend.task_fsm import TaskStage, TaskStep
from backend.task_prompt import (
    EXPECTED_ACTIONS, TASK_STATE_HEADER, render_task_state_block,
)
from backend.task_state import TaskStateMachine

from support import create_agent, create_task

TASK_ID = "tz"
EXPECTED_BLOCK_LINE = (
    "Текущий этап: execution. Текущий шаг: implement. "
    "Ожидаемое действие: ожидается реализация модуля. "
    "Предыдущие шаги: planning (gather_requirements, define_scope, "
    "create_plan) — завершены."
)


@pytest.fixture
def agent_with_task(make_agent, session_factory):
    """Агент с заведённой задачей на execution/implement."""
    agent = make_agent(task_id=TASK_ID)
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.EXECUTION.value)
    return agent


def test_agent_without_task_has_no_block_and_no_state(make_agent):
    """Без состояния задачи блок в промпт не попадает, поле ответа пусто."""
    agent = make_agent()

    assert agent.task_state() is None
    assert agent.task_state_block() == ""

    record = agent.generate("обычная реплика")
    assert record["task_state"] is None
    assert "Текущий этап:" not in record["system_prompt"]


def test_task_state_appears_in_system_prompt(agent_with_task):
    """Состояние задачи — часть системного промпта, дословно как в шаблоне."""
    record = agent_with_task.generate("покажи план")

    assert EXPECTED_BLOCK_LINE in record["system_prompt"]
    assert record["task_state"]["task_id"] == TASK_ID
    assert record["task_state"]["stage"] == TaskStage.EXECUTION.value
    assert record["task_state"]["prompt_block"] == render_task_state_block(
        TaskStage.EXECUTION,
        TaskStep.IMPLEMENT,
        EXPECTED_ACTIONS[(TaskStage.EXECUTION, TaskStep.IMPLEMENT)],
    )
    assert record["task_state"]["prompt_block"].startswith(TASK_STATE_HEADER)
    assert agent_with_task.task_state_block() in record["system_prompt"]


def test_reply_advances_the_step(agent_with_task):
    """«подтверждаю» двигает задачу на следующий шаг текущего этапа."""
    record = agent_with_task.generate("подтверждаю")
    assert record["task_state"]["current_step"] == TaskStep.TEST_LOCALLY.value
    assert "Текущий шаг: test_locally" in record["system_prompt"]


def test_reply_without_intent_keeps_state(agent_with_task):
    """Обычная реплика состояние не меняет."""
    agent_with_task.generate("расскажи про токены и контекст")
    assert agent_with_task.task_state()["current_step"] == TaskStep.IMPLEMENT.value


def test_pause_and_resume_from_replies(agent_with_task):
    """«пауза» ставит задачу на паузу, «продолжи» возвращает на тот же шаг."""
    paused = agent_with_task.generate("поставь задачу на паузу")
    assert paused["task_state"]["stage"] == TaskStage.PAUSED.value
    assert paused["task_state"]["current_step"] == TaskStep.IMPLEMENT.value
    assert "Текущий этап: paused." in paused["system_prompt"]

    resumed = agent_with_task.generate("продолжи")
    assert resumed["task_state"]["stage"] == TaskStage.EXECUTION.value
    assert resumed["task_state"]["current_step"] == TaskStep.IMPLEMENT.value
    assert resumed["task_state"]["paused_from_stage"] is None


def test_rollback_from_reply(make_agent, session_factory):
    """«вернись на предыдущий этап» откатывает на этап назад."""
    agent = make_agent(task_id=TASK_ID)
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.VALIDATION.value)

    record = agent.generate("вернись на предыдущий этап")
    assert record["task_state"]["stage"] == TaskStage.EXECUTION.value
    assert record["task_state"]["current_step"] == TaskStep.IMPLEMENT.value


def test_invalid_intent_does_not_break_the_dialog(make_agent, session_factory):
    """На planning откатываться некуда: диалог продолжается, состояние прежнее."""
    agent = make_agent(task_id=TASK_ID)
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.PLANNING.value)

    record = agent.generate("вернись на предыдущий этап")
    assert record["status"] == "ok"
    state = record["task_state"]
    assert (state["stage"], state["current_step"]) == (
        TaskStage.PLANNING.value, TaskStep.GATHER_REQUIREMENTS.value,
    )


def test_finished_task_is_not_changed_by_replies(make_agent, session_factory):
    """Завершённую задачу реплики не воскрешают: она остаётся в done."""
    agent = make_agent(task_id=TASK_ID)
    machine = TaskStateMachine(session_factory=session_factory)
    machine.create(agent.agent_id, TASK_ID, TaskStage.VALIDATION.value)
    machine.transition_to(
        TASK_ID, TaskStage.DONE.value, TaskStep.FINALIZE.value,
        "задача завершена; ожидается новая задача", reason="задача завершена",
    )

    record = agent.generate("продолжи")
    assert record["task_state"]["stage"] == TaskStage.DONE.value
    assert record["task_state"]["is_active"] is False


def test_state_survives_agent_rebuild(make_agent, session_factory):
    """После переходов второй Agent на той же БД видит тот же этап и шаг."""
    agent = make_agent(task_id=TASK_ID)
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.EXECUTION.value)
    agent.generate("подтверждаю")  # execution/test_locally

    restarted = create_agent(
        session_factory, agent.agent_id, ensure_record=False, task_id=TASK_ID
    )
    block = restarted.task_state_block()
    assert "Текущий шаг: test_locally" in block
    assert restarted.task_state()["expected_action"] == EXPECTED_ACTIONS[
        (TaskStage.EXECUTION, TaskStep.TEST_LOCALLY)
    ]


def test_agent_owns_a_task_state_machine(agent_with_task):
    """Контракт дня 13: у агента есть машина состояния задачи."""
    assert isinstance(agent_with_task.task_state_machine, TaskStateMachine)
    assert agent_with_task.task_state_machine.get_state(TASK_ID) is not None
