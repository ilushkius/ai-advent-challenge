"""Переходы стейт-машин планировщика (день 18).

Проверяется ГРАФ, а не реализация: таблица «состояние + событие → состояние»,
негативные случаи (событие, недопустимое в состоянии, — явная ошибка, а не
«тихий» no-op) и перечень допустимых событий. Именно на этот граф опирается и
роутер (409 на паузу неактивной задачи), и хранилище (повторная выдача
напоминания — ошибка).
"""
import pytest

from backend.domain.scheduler_fsm import (
    ALLOWED_REMINDER_TRANSITIONS,
    ALLOWED_TASK_TRANSITIONS,
    ReminderEvent,
    ReminderFSM,
    ScheduledTaskEvent,
    ScheduledTaskFSM,
    UnknownSchedulerEvent,
    reminder_allowed_events,
    task_allowed_events,
)
from backend.domain.scheduler_values import ReminderState, ScheduledTaskState

#: Таблица допустимых переходов задачи: состояние → {событие: новое состояние}.
TASK_CASES = [
    (ScheduledTaskState.ACTIVE, ScheduledTaskEvent.PAUSE, ScheduledTaskState.PAUSED),
    (ScheduledTaskState.ACTIVE, ScheduledTaskEvent.COMPLETE, ScheduledTaskState.COMPLETED),
    (ScheduledTaskState.PAUSED, ScheduledTaskEvent.RESUME, ScheduledTaskState.ACTIVE),
]

#: Каждая пара «состояние + событие», которой в графе НЕТ.
TASK_FORBIDDEN = [
    (ScheduledTaskState.PAUSED, ScheduledTaskEvent.PAUSE),
    (ScheduledTaskState.PAUSED, ScheduledTaskEvent.COMPLETE),
    (ScheduledTaskState.COMPLETED, ScheduledTaskEvent.PAUSE),
    (ScheduledTaskState.COMPLETED, ScheduledTaskEvent.RESUME),
    (ScheduledTaskState.COMPLETED, ScheduledTaskEvent.COMPLETE),
    (ScheduledTaskState.ACTIVE, ScheduledTaskEvent.RESUME),
]


@pytest.mark.parametrize("state,event,expected", TASK_CASES)
def test_task_transitions_table(state, event, expected):
    """Каждый объявленный переход задачи приводит в объявленное состояние."""
    machine = ScheduledTaskFSM(state)
    assert machine.handle(event) is expected
    assert machine.state is expected


@pytest.mark.parametrize("state,event", TASK_FORBIDDEN)
def test_task_forbidden_events_raise(state, event):
    """Событие вне графа — ошибка с перечнем допустимых, а не молчаливый no-op."""
    machine = ScheduledTaskFSM(state)
    with pytest.raises(UnknownSchedulerEvent) as excinfo:
        machine.handle(event)
    message = str(excinfo.value)
    assert event.value in message and state.value in message
    assert "допустимы" in message
    assert machine.state is state  # отказ состояние не меняет


@pytest.mark.parametrize("state,expected", [
    (ScheduledTaskState.ACTIVE, ("pause", "complete")),
    (ScheduledTaskState.PAUSED, ("resume",)),
    (ScheduledTaskState.COMPLETED, ()),
])
def test_task_allowed_events(state, expected):
    """Перечень допустимых событий совпадает с графом (в порядке объявления)."""
    assert tuple(item.value for item in task_allowed_events(state)) == expected
    assert tuple(item.value for item in ScheduledTaskFSM(state).allowed_events()) == expected
    assert ScheduledTaskFSM(state).can(ScheduledTaskEvent.PAUSE) == ("pause" in expected)


def test_task_graph_is_derived_from_handlers():
    """Граф — производная от обработчиков состояний, а не второй список переходов."""
    assert set(ALLOWED_TASK_TRANSITIONS) == set(ScheduledTaskState)
    assert list(ALLOWED_TASK_TRANSITIONS[ScheduledTaskState.PAUSED]) == [
        ScheduledTaskEvent.RESUME
    ]


def test_reminder_fires_once():
    """Напоминание выдаётся ровно раз: второй FIRE — ошибка."""
    machine = ReminderFSM()
    assert machine.state is ReminderState.SCHEDULED
    assert machine.handle(ReminderEvent.FIRE) is ReminderState.DONE
    with pytest.raises(UnknownSchedulerEvent):
        machine.handle(ReminderEvent.FIRE)
    assert machine.state is ReminderState.DONE


def test_reminder_allowed_events():
    """До выдачи допустим только FIRE, после — ни одного события."""
    assert tuple(item.value for item in reminder_allowed_events(ReminderState.SCHEDULED)) == ("fire",)
    assert reminder_allowed_events(ReminderState.DONE) == ()
    assert set(ALLOWED_REMINDER_TRANSITIONS) == set(ReminderState)
