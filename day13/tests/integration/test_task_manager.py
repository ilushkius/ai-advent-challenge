"""Тесты миксина задач (день 13): состояние задачи через ``AgentManager``.

Проверяется то, чем пользуется API: создание задачи, пауза и продолжение с тем
же шагом, откат на предыдущий этап, завершение и список активных задач плюс
причины в журнале переходов. Всё офлайн: временная SQLite и подменённый клиент.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.agents.agent_manager import AgentManager
from backend.storage.database import TaskState, TaskTransition
from backend.agents.manager_agents import AgentNotFoundError
from backend.domain.task_fsm import InvalidTaskTransition, TaskStage, TaskStep
from backend.services.task_state import TaskNotFoundError

from support import create_agent

AGENT_ID = "mem01"
TASK_ID = "tz"


@pytest.fixture
def manager(session_factory):
    """AgentManager со живым агентом на временной БД (агент нужен для create_task)."""
    seed_agent(session_factory)
    manager = AgentManager(session_factory=session_factory)
    manager.restore_from_db()
    return manager


def seed_agent(session_factory) -> None:
    """Строка agents + объект Agent на той же БД (как при старте бэкенда)."""
    create_agent(session_factory, AGENT_ID, session_id="sess0001")


def test_create_task_starts_from_planning(manager):
    """Новая задача встаёт на planning/gather_requirements и даёт блок промпта."""
    state = manager.create_task(AGENT_ID, TASK_ID)
    assert state["agent_id"] == AGENT_ID
    assert state["stage"] == TaskStage.PLANNING.value
    assert state["current_step"] == TaskStep.GATHER_REQUIREMENTS.value
    assert state["is_active"] is True
    assert "Текущий шаг: gather_requirements" in state["prompt_block"]
    assert manager.get_task_state(TASK_ID) == state


def test_create_task_activates_it_on_the_agent(manager):
    """Заведение состояния делает задачу активной — иначе блок не попадёт в промпт."""
    manager.create_task(AGENT_ID, TASK_ID, TaskStage.EXECUTION.value)
    agent = manager.get_agent(AGENT_ID)
    assert agent.task_id == TASK_ID
    assert "Текущий этап: execution" in agent.task_state_block()


def test_create_task_for_unknown_agent_raises(manager):
    """Неизвестный агент — та же ошибка, что у остальных методов менеджера (404)."""
    with pytest.raises(AgentNotFoundError):
        manager.create_task("нет-такого", TASK_ID)


def test_advance_pause_resume_rollback_roundtrip(manager):
    """advance → pause → resume → rollback: шаг переживает паузу, откат его сбрасывает."""
    manager.create_task(AGENT_ID, TASK_ID)
    for _ in range(3):
        manager.advance_task_step(TASK_ID)
    assert manager.get_task_state(TASK_ID)["stage"] == TaskStage.EXECUTION.value
    assert manager.get_task_state(TASK_ID)["current_step"] == TaskStep.IMPLEMENT.value

    paused = manager.pause_task(TASK_ID)
    assert paused["stage"] == TaskStage.PAUSED.value
    assert paused["current_step"] == TaskStep.IMPLEMENT.value

    resumed = manager.resume_task(TASK_ID)
    assert (resumed["stage"], resumed["current_step"]) == (
        TaskStage.EXECUTION.value, TaskStep.IMPLEMENT.value,
    )

    assert manager.rollback_task(TASK_ID, TaskStage.PLANNING.value)["stage"] == (
        TaskStage.PLANNING.value
    )
    assert manager.get_task_state(TASK_ID)["current_step"] == (
        TaskStep.GATHER_REQUIREMENTS.value
    )


def test_rollback_task_to_wrong_stage_raises(manager):
    """Откат проверяет целевой этап: «куда захотелось» не работает."""
    manager.create_task(AGENT_ID, TASK_ID, TaskStage.VALIDATION.value)
    with pytest.raises(InvalidTaskTransition):
        manager.rollback_task(TASK_ID, TaskStage.VALIDATION.value)
    assert manager.get_task_state(TASK_ID)["stage"] == TaskStage.VALIDATION.value


def test_transition_task_resolves_defaults(manager):
    """Без step/expected_action менеджер подставляет первый шаг и действие этапа."""
    manager.create_task(AGENT_ID, TASK_ID, TaskStage.VALIDATION.value)
    state = manager.transition_task(TASK_ID, TaskStage.DONE.value, reason="задача завершена")
    assert state["stage"] == TaskStage.DONE.value
    assert state["current_step"] == TaskStep.FINALIZE.value
    assert state["is_active"] is False
    assert state["expected_action"].startswith("задача завершена")


def test_transition_task_to_paused_keeps_current_step(manager):
    """Переход в paused без явного шага берёт шаг из текущего состояния."""
    manager.create_task(AGENT_ID, TASK_ID, TaskStage.EXECUTION.value)
    manager.advance_task_step(TASK_ID)  # execution/test_locally

    state = manager.transition_task(TASK_ID, TaskStage.PAUSED.value)
    assert state["stage"] == TaskStage.PAUSED.value
    assert state["current_step"] == TaskStep.TEST_LOCALLY.value


def test_list_active_tasks_excludes_completed(manager):
    """Список задач агента — только незавершённые (пауза считается активной)."""
    manager.create_task(AGENT_ID, TASK_ID)
    manager.create_task(AGENT_ID, "tz2", TaskStage.VALIDATION.value)
    manager.pause_task(TASK_ID)

    assert [state["task_id"] for state in manager.list_active_tasks(AGENT_ID)] == [
        TASK_ID, "tz2",
    ]

    manager.transition_task("tz2", TaskStage.DONE.value)

    assert [state["task_id"] for state in manager.list_active_tasks(AGENT_ID)] == [TASK_ID]
    assert manager.list_active_tasks("чужой") == []


def test_history_reasons_follow_operations(manager):
    """Журнал объясняет каждый переход — по нему восстанавливается ход работы."""
    manager.create_task(AGENT_ID, TASK_ID, TaskStage.EXECUTION.value)
    manager.advance_task_step(TASK_ID)
    manager.pause_task(TASK_ID)
    manager.resume_task(TASK_ID)
    manager.rollback_task(TASK_ID, TaskStage.PLANNING.value)

    entries = manager.get_task_history(TASK_ID)
    assert [entry["reason"] for entry in entries] == [
        "задача создана",
        "следующий шаг",
        "пауза",
        "продолжение после паузы",
        "откат на предыдущий этап",
    ]
    assert entries[-1]["from_stage"] == TaskStage.EXECUTION.value
    assert entries[-1]["to_stage"] == TaskStage.PLANNING.value


def test_transition_task_default_reason_and_completion(manager):
    """Переход без причины пишется «переход по запросу», завершение — своей."""
    manager.create_task(AGENT_ID, TASK_ID)
    manager.transition_task(TASK_ID, TaskStage.EXECUTION.value)
    assert manager.get_task_history(TASK_ID)[-1]["reason"] == "переход по запросу"

    manager.transition_task(TASK_ID, TaskStage.VALIDATION.value)
    state = manager.transition_task(
        TASK_ID, TaskStage.DONE.value, reason="задача завершена"
    )
    assert state["is_active"] is False
    assert manager.get_task_history(TASK_ID)[-1]["reason"] == "задача завершена"


def test_unknown_task_raises_not_found(manager):
    """Неизвестная задача — TaskNotFoundError (роутер отвечает 404)."""
    assert manager.get_task_state("нет-такой") is None
    with pytest.raises(TaskNotFoundError):
        manager.pause_task("нет-такой")
    with pytest.raises(TaskNotFoundError):
        manager.transition_task("нет-такой", TaskStage.EXECUTION.value)


def test_state_survives_manager_restart(session_factory):
    """Состояние читается из БД: новый менеджер видит ту же задачу."""
    seed_agent(session_factory)

    first = AgentManager(session_factory=session_factory)
    first.restore_from_db()
    first.create_task(AGENT_ID, TASK_ID, TaskStage.EXECUTION.value)
    first.pause_task(TASK_ID)

    second = AgentManager(session_factory=session_factory)
    second.restore_from_db()
    state = second.get_task_state(TASK_ID)
    assert state["stage"] == TaskStage.PAUSED.value
    assert second.resume_task(TASK_ID)["stage"] == TaskStage.EXECUTION.value


def test_remove_agent_deletes_task_rows(manager, session_factory):
    """Удаление агента уносит и состояние задачи, и её журнал."""
    manager.create_task(AGENT_ID, TASK_ID)
    manager.advance_task_step(TASK_ID)

    assert manager.remove_agent(AGENT_ID) is True
    assert manager.get_task_state(TASK_ID) is None
    with session_factory() as session:
        assert session.query(TaskState).count() == 0
        assert session.query(TaskTransition).count() == 0
