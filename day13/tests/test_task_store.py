"""Хранение состояния задачи (день 13): журнал, снимок и переживание рестарта.

Поведение переходов проверяется в ``tests/test_task_state.py``; здесь — то, что
 состояние задачи лежит в SQLite и читается оттуда: строки ``task_transitions``,
снимок рабочей памяти в ``context``, проекция строки в словарь для API/UI и
чтение тем же состоянием после «перезапуска» (новый объект машины на той же
базе). Сеть и рабочая БД не используются.
"""

from __future__ import annotations

from datetime import timezone

import pytest

from backend.database import TaskTransition
from backend.memory import MemoryManager
from backend.task_fsm import TaskStage, TaskStep
from backend.task_prompt import TASK_STATE_HEADER
from backend.task_state import TaskStateMachine

AGENT_ID = "task01"
TASK_ID = "tz"


@pytest.fixture
def created(task_machine):
    """Задача в состоянии planning/gather_requirements."""
    return task_machine.create(AGENT_ID, TASK_ID)


# ---------- журнал переходов ----------
def test_create_writes_one_transition_row(task_machine, created):
    """Создание — это первый переход журнала, и у него ещё нет «из»."""
    entries = task_machine.get_full_history(TASK_ID)
    assert len(entries) == 1
    assert entries[0]["from_stage"] is None
    assert entries[0]["from_step"] is None
    assert entries[0]["to_stage"] == TaskStage.PLANNING.value
    assert entries[0]["to_step"] == TaskStep.GATHER_REQUIREMENTS.value
    assert entries[0]["reason"] == "задача создана"
    assert entries[0]["created_at"].tzinfo is not None
    assert len(created["history"]) == 1


def test_history_grows_by_one_per_transition(task_machine):
    """Журнал объясняет каждый переход: создание плюс по записи на операцию."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.EXECUTION.value)
    task_machine.advance_step(TASK_ID)   # execution/test_locally
    task_machine.pause(TASK_ID)          # paused/test_locally
    task_machine.resume(TASK_ID)         # execution/test_locally
    task_machine.rollback(TASK_ID)       # planning/gather_requirements

    entries = task_machine.get_full_history(TASK_ID)
    assert [entry["reason"] for entry in entries] == [
        "задача создана",
        "следующий шаг",
        "пауза",
        "продолжение после паузы",
        "откат на предыдущий этап",
    ]
    assert [entry["id"] for entry in entries] == sorted(entry["id"] for entry in entries)
    assert entries[-1]["from_stage"] == TaskStage.EXECUTION.value
    assert entries[-1]["from_step"] == TaskStep.TEST_LOCALLY.value
    assert entries[-1]["to_stage"] == TaskStage.PLANNING.value
    assert len(task_machine.get_state(TASK_ID)["history"]) == len(entries)


def test_history_rows_live_in_transitions_table(
    task_session_factory, task_machine, created
):
    """Журнал — это таблица, а не только JSON: строки видны в task_transitions."""
    task_machine.advance_step(TASK_ID)
    with task_session_factory() as session:
        rows = session.query(TaskTransition).order_by(TaskTransition.id.asc()).all()

    assert [row.reason for row in rows] == ["задача создана", "следующий шаг"]
    assert rows[0].from_stage is None
    assert rows[1].from_step == TaskStep.GATHER_REQUIREMENTS.value
    assert rows[1].to_step == TaskStep.DEFINE_SCOPE.value
    assert rows[1].task_id == TASK_ID


# ---------- снимок рабочей памяти ----------
def test_create_snapshots_working_memory(task_session_factory, task_machine):
    """context задачи — снимок рабочей памяти дня 11 на момент перехода."""
    MemoryManager(session_factory=task_session_factory).add_working(
        AGENT_ID, TASK_ID, "цель", "портал заявок"
    )
    state = task_machine.create(AGENT_ID, TASK_ID)

    assert state["context"]["task_id"] == TASK_ID
    assert state["context"]["working_memory"] == {"цель": "портал заявок"}
    assert state["context"]["paused_from_stage"] is None
    assert state["context"]["paused_from_step"] is None


def test_working_memory_snapshot_is_refreshed_on_transition(
    task_session_factory, task_machine
):
    """Каждый переход перечитывает рабочую память задачи."""
    memory = MemoryManager(session_factory=task_session_factory)
    memory.add_working(AGENT_ID, TASK_ID, "цель", "портал заявок")
    task_machine.create(AGENT_ID, TASK_ID)
    memory.add_working(AGENT_ID, TASK_ID, "ограничение", "без мобильного клиента")

    state = task_machine.advance_step(TASK_ID)
    assert state["context"]["working_memory"] == {
        "цель": "портал заявок",
        "ограничение": "без мобильного клиента",
    }


# ---------- проекция строки в словарь ----------
def test_state_dict_projection_fields(task_machine, created):
    """Производные поля считаются из строки: активность, откат, блок промпта."""
    assert created["is_active"] is True
    assert created["rollback_stage"] is None
    assert created["paused_from_stage"] is None
    assert created["prompt_block"].startswith(TASK_STATE_HEADER)
    assert created["created_at"].tzinfo is not None
    assert created["updated_at"] >= created["created_at"]

    paused = task_machine.pause(TASK_ID)
    assert paused["is_active"] is True          # пауза — не завершение задачи
    assert paused["rollback_stage"] is None     # из paused откат не описан
    assert paused["paused_from_stage"] == TaskStage.PLANNING.value

    resumed = task_machine.resume(TASK_ID)
    assert resumed["paused_from_stage"] is None
    assert resumed["is_active"] is True


def test_state_dict_reports_rollback_target_and_utc_timestamps(task_machine):
    """rollback_stage — цель отката, метки времени — UTC-aware."""
    state = task_machine.create(AGENT_ID, TASK_ID, TaskStage.VALIDATION.value)
    assert state["rollback_stage"] == TaskStage.EXECUTION.value
    assert state["created_at"].tzinfo is timezone.utc

    task_machine.advance_step(TASK_ID)
    task_machine.advance_step(TASK_ID)  # validation/finalize
    done = task_machine.transition_to(
        TASK_ID, TaskStage.DONE.value, TaskStep.FINALIZE.value, "задача завершена"
    )
    assert done["is_active"] is False
    assert done["rollback_stage"] is None


# ---------- список задач ----------
def test_list_states_returns_agent_tasks_in_creation_order(task_machine, created):
    """list_states отдаёт задачи агента по порядку создания; чужие не попадают."""
    task_machine.create(AGENT_ID, "tz2", initial_stage=TaskStage.EXECUTION.value)
    states = task_machine.list_states(AGENT_ID)

    assert [state["task_id"] for state in states] == [TASK_ID, "tz2"]
    assert [state["stage"] for state in states] == [
        TaskStage.PLANNING.value, TaskStage.EXECUTION.value,
    ]
    assert task_machine.list_states("чужой") == []


# ---------- переживание рестарта ----------
def test_state_survives_new_machine_instance(task_session_factory, task_machine):
    """Новый объект машины на той же базе читает то же состояние и журнал."""
    task_machine.create(AGENT_ID, TASK_ID, initial_stage=TaskStage.EXECUTION.value)
    task_machine.advance_step(TASK_ID)
    task_machine.pause(TASK_ID)

    before = task_machine.get_state(TASK_ID)
    history_before = task_machine.get_full_history(TASK_ID)

    restarted = TaskStateMachine(session_factory=task_session_factory)
    after = restarted.get_state(TASK_ID)

    assert (after["stage"], after["current_step"], after["expected_action"]) == (
        before["stage"], before["current_step"], before["expected_action"]
    )
    assert after["history"] == before["history"]
    assert after["prompt_block"] == before["prompt_block"]
    assert restarted.get_full_history(TASK_ID) == history_before
    # И продолжение работает с того же шага.
    assert restarted.resume(TASK_ID)["current_step"] == TaskStep.TEST_LOCALLY.value


def test_machine_keeps_no_state_in_memory(task_machine, created):
    """Машина не держит состояние в памяти: каждый вызов читает строку из БД."""
    task_machine.pause(TASK_ID)
    assert task_machine.get_state(TASK_ID)["stage"] == TaskStage.PAUSED.value
    # Единственный атрибут — хранилище; этапа/шага/журнала в памяти нет.
    assert list(vars(task_machine)) == ["_store"]
    assert set(vars(task_machine._store)) <= {"_session_factory", "_memory"}
