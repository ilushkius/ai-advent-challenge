"""Тесты подключения состояния задачи к агенту (день 15, ``backend/agents/agent.py``).

Главное, что здесь проверяется: блок состояния — часть СИСТЕМНОГО ПРОМПТА
каждого запроса, реплика пользователя обновляет состояние автоматически,
состояние читается из БД (переживает пересборку агента), а контролируемые
переходы работают с двух сторон — неприменённое намерение пользователя и
недопустимое предложение модели превращаются в объяснение, а не в тишину.
Тесты идут без сети: клиент DeepSeek подменяется фейком.
"""

from __future__ import annotations

import pytest

from backend.domain.task_fsm import TaskStage, TaskStep
from backend.domain.task_prompt import (
    EXPECTED_ACTIONS, TASK_STATE_HEADER, render_task_state_block,
)
from backend.services.task_state import TaskStateMachine

from support import FakeClient, create_agent, create_task

TASK_ID = "tz"
EXPECTED_BLOCK_LINE = (
    "Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. "
    "Ожидаемое действие: ожидается реализация модуля. "
    "Не пытайся перейти в недопустимый этап — сначала заверши текущий. "
    "Текущий шаг: implement. "
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
    assert record["task_intent"] is None
    assert "Текущий этап задачи:" not in record["system_prompt"]


def test_task_state_appears_in_system_prompt(agent_with_task):
    """Состояние задачи — часть системного промпта, дословно как в шаблоне."""
    record = agent_with_task.generate("покажи план")

    assert EXPECTED_BLOCK_LINE in record["system_prompt"]
    assert record["task_state"]["task_id"] == TASK_ID
    assert record["task_state"]["stage"] == TaskStage.EXECUTION.value
    assert record["task_state"]["allowed_next"] == [
        TaskStage.PLANNING.value, TaskStage.PAUSED.value,
    ]
    assert record["task_state"]["prompt_block"] == render_task_state_block(
        TaskStage.EXECUTION,
        TaskStep.IMPLEMENT,
        EXPECTED_ACTIONS[(TaskStage.EXECUTION, TaskStep.IMPLEMENT)],
        record["task_state"]["allowed_next"],
    )
    assert record["task_state"]["prompt_block"].startswith(TASK_STATE_HEADER)
    assert agent_with_task.task_state_block() in record["system_prompt"]


def test_reply_advances_the_step(agent_with_task):
    """«подтверждаю» двигает задачу на следующий шаг текущего этапа."""
    record = agent_with_task.generate("подтверждаю")

    assert record["task_state"]["current_step"] == TaskStep.TEST_LOCALLY.value
    assert record["task_intent"]["intent"] == "advance"
    assert record["task_intent"]["applied"] is True
    assert "Текущий шаг: test_locally" in record["system_prompt"]


def test_reply_without_intent_keeps_state(agent_with_task):
    """Обычная реплика состояние не меняет."""
    record = agent_with_task.generate("расскажи про токены и контекст")

    assert record["task_intent"] is None
    assert record["task_proposal"] is None
    assert agent_with_task.task_state()["current_step"] == TaskStep.IMPLEMENT.value


def test_refused_intent_is_reported_in_the_answer(make_agent, session_factory):
    """Реплика, которую правила не пускают, объясняет отказ в самом ответе.

    «подтверждаю» на последнем шаге планирования пытается выйти в execution,
    но план не утверждён: состояние прежнее, а пользователь видит причину и
    список доступных этапов.
    """
    agent = make_agent(task_id=TASK_ID)
    machine = TaskStateMachine(session_factory=session_factory)
    machine.create(
        agent.agent_id, TASK_ID, TaskStage.PLANNING.value,
        initial_step=TaskStep.CREATE_PLAN.value,
    )

    record = agent.generate("подтверждаю")

    assert record["task_intent"] == {
        "intent": "advance",
        "applied": False,
        "reason": "Нельзя перейти в execution: план не утверждён",
        "allowed_next": [TaskStage.PAUSED.value],
    }
    assert record["response"].startswith(
        "⚠️ Переход по реплике «advance» не выполнен: "
        "Нельзя перейти в execution: план не утверждён "
        "Доступные следующие этапы: paused."
    )
    assert record["task_state"]["current_step"] == TaskStep.CREATE_PLAN.value
    assert machine.get_state(TASK_ID)["stage"] == TaskStage.PLANNING.value


def test_refused_intent_is_journaled(make_agent, session_factory):
    """Отклонённая реплика остаётся в журнале попыток задачи."""
    agent = make_agent(task_id=TASK_ID)
    machine = TaskStateMachine(session_factory=session_factory)
    machine.create(
        agent.agent_id, TASK_ID, TaskStage.PLANNING.value,
        initial_step=TaskStep.CREATE_PLAN.value,
    )

    agent.generate("подтверждаю")

    entries = machine.get_full_history(TASK_ID)
    assert [entry["accepted"] for entry in entries] == [True, False]
    assert entries[-1]["reason"] == "Нельзя перейти в execution: план не утверждён"


def test_model_proposal_of_a_forbidden_transition_is_refused(make_agent, session_factory):
    """Предложение модели перейти в недопустимый этап заменяется отказом."""
    agent = make_agent(
        task_id=TASK_ID, fake=FakeClient(reply="Задача завершена, можно сдавать.")
    )
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.VALIDATION.value)

    record = agent.generate("как дела с задачей?")

    assert record["task_proposal"] == {
        "proposed": TaskStage.DONE.value,
        "allowed_next": [TaskStage.EXECUTION.value, TaskStage.PAUSED.value],
        "reason": "Нельзя перейти в done: валидация не пройдена",
        "hint": "Отметьте флаг «✅ Валидация пройдена» в панели задачи.",
    }
    assert "🚧 Ответ предлагает переход в done, но это недопустимо." in record["response"]
    assert "Нельзя перейти в done: валидация не пройдена" in record["response"]
    # Состояние прежнее: предложение модели задачу не двигает.
    assert agent.task_state()["stage"] == TaskStage.VALIDATION.value


def test_model_proposal_without_flag_is_refused_with_the_rule(make_agent, session_factory):
    """На planning предложение «перехожу к реализации» отклоняется без плана."""
    agent = make_agent(
        task_id=TASK_ID, fake=FakeClient(reply="Перехожу к реализации.")
    )
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.PLANNING.value)

    record = agent.generate("что дальше?")

    assert record["task_proposal"]["proposed"] == TaskStage.EXECUTION.value
    assert record["task_proposal"]["reason"] == (
        "Нельзя перейти в execution: план не утверждён"
    )
    assert "🚧 Ответ предлагает переход в execution" in record["response"]


def test_naming_the_current_stage_is_not_a_proposal(make_agent, session_factory):
    """Модель, рассказывающая о текущем этапе, отказом не наказывается."""
    agent = make_agent(
        task_id=TASK_ID, fake=FakeClient(reply="Приступаю к реализации.")
    )
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.EXECUTION.value)

    record = agent.generate("как продвигается?")

    assert record["task_proposal"] is None
    assert record["response"] == "Приступаю к реализации."


def test_pause_and_resume_from_replies(agent_with_task):
    """«пауза» ставит задачу на паузу, «продолжи» возвращает на тот же шаг."""
    paused = agent_with_task.generate("поставь задачу на паузу")
    assert paused["task_state"]["stage"] == TaskStage.PAUSED.value
    assert paused["task_state"]["current_step"] == TaskStep.IMPLEMENT.value
    assert "Текущий этап задачи: paused." in paused["system_prompt"]
    assert paused["task_intent"]["applied"] is True

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


def test_rollback_intent_without_target_is_not_applied(make_agent, session_factory):
    """На planning откатываться некуда: диалог продолжается, состояние прежнее."""
    agent = make_agent(task_id=TASK_ID)
    create_task(session_factory, agent.agent_id, TASK_ID, TaskStage.PLANNING.value)

    record = agent.generate("вернись на предыдущий этап")
    assert record["status"] == "ok"
    assert record["task_intent"] is None  # цели отката нет — намерение не применено
    state = record["task_state"]
    assert (state["stage"], state["current_step"]) == (
        TaskStage.PLANNING.value, TaskStep.GATHER_REQUIREMENTS.value,
    )


def test_finished_task_is_not_changed_by_replies(make_agent, session_factory):
    """Завершённую задачу реплики не воскрешают: она остаётся в done."""
    agent = make_agent(task_id=TASK_ID)
    machine = TaskStateMachine(session_factory=session_factory)
    machine.create(agent.agent_id, TASK_ID, TaskStage.VALIDATION.value)
    machine.set_flags(TASK_ID, {"validation_passed": True})
    machine.transition_to(
        TASK_ID, TaskStage.DONE.value, None, None, reason="задача завершена",
    )

    record = agent.generate("продолжи")
    assert record["task_state"]["stage"] == TaskStage.DONE.value
    assert record["task_state"]["is_active"] is False
    assert record["task_state"]["allowed_next"] == []
    assert record["task_intent"] is None


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
    """У агента есть машина состояния задачи, читающая состояние из БД."""
    assert isinstance(agent_with_task.task_state_machine, TaskStateMachine)
    assert agent_with_task.task_state_machine.get_state(TASK_ID) is not None
