"""Стейт-машины планировщика (день 18): состояние задачи и состояние напоминания.

Две машины в одном модуле — так их читают рядом, и обе устроены одинаково:
состояния и события — ``enum.Enum``, переходы — паттерн State (класс состояния с
интерфейсом ``handle(event)``), неизвестное событие — явная ошибка
``UnknownSchedulerEvent``, а не «тихое» зависание. То же правило, что у
``mcp_connection_fsm.py`` дня 16 и ``mcp_tool_call.py`` дня 17.

Графы переходов однозначны:

======================================  ==========================================
состояние задачи                        событие → новое состояние
======================================  ==========================================
``ACTIVE``                              ``PAUSE`` → ``PAUSED`` (⏸)
                                        ``COMPLETE`` → ``COMPLETED`` (✅, разовая задача)
``PAUSED``                              ``RESUME`` → ``ACTIVE`` (▶)
``COMPLETED``                           — (задача выполнена, дальше пути нет)
======================================  ==========================================

======================================  ==========================================
состояние напоминания                   событие → новое состояние
======================================  ==========================================
``SCHEDULED``                           ``FIRE`` → ``DONE`` (⏰ выдано)
``DONE``                                — (повторный ``FIRE`` — ошибка, а не no-op)
======================================  ==========================================

Почему недопустимый шаг — ошибка, а не «ничего». Пауза уже стоящей на паузе
задачи и повторная выдача напоминания — это попытка сделать действие дважды;
«тихий» no-op скрыл бы от пользователя, что состояние было другим. Отказ виден
сразу: роутер переводит ошибку в 409 с текстом «допустимы: resume».

Модуль чистый: только ``enum`` — ни БД, ни HTTP, ни Streamlit.
"""

from __future__ import annotations

import enum
from typing import ClassVar

from .scheduler_values import ReminderState, ScheduledTaskState


class ScheduledTaskEvent(enum.Enum):
    """Событие, которое двигает задачу планировщика по графу."""

    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"


class ReminderEvent(enum.Enum):
    """Событие напоминания: момент выдачи наступил."""

    FIRE = "fire"


class UnknownSchedulerEvent(Exception):
    """Событие, недопустимое в текущем состоянии (задачи или напоминания)."""

    def __init__(self, state: enum.Enum, event: enum.Enum,
                 allowed: tuple[enum.Enum, ...] = ()):
        self.state = state
        self.event = event
        names = ", ".join(item.value for item in allowed) or "—"
        super().__init__(
            f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
            f"допустимы: {names}"
        )


class TaskStateHandler:
    """Общий интерфейс состояния задачи: одно событие → ровно одно состояние."""

    state: ClassVar[ScheduledTaskState]
    transitions: ClassVar[dict[ScheduledTaskEvent, ScheduledTaskState]]

    def handle(self, event: ScheduledTaskEvent) -> ScheduledTaskState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownSchedulerEvent(
                self.state, event, task_allowed_events(self.state)
            ) from None


class ActiveState(TaskStateHandler):
    """Задача работает по расписанию."""

    state = ScheduledTaskState.ACTIVE
    transitions = {
        ScheduledTaskEvent.PAUSE: ScheduledTaskState.PAUSED,
        ScheduledTaskEvent.COMPLETE: ScheduledTaskState.COMPLETED,
    }


class PausedState(TaskStateHandler):
    """Задача на паузе: расписание сохраняется, запусков нет."""

    state = ScheduledTaskState.PAUSED
    transitions = {ScheduledTaskEvent.RESUME: ScheduledTaskState.ACTIVE}


class CompletedState(TaskStateHandler):
    """Разовая задача отработала: срабатывает один раз и завершается."""

    state = ScheduledTaskState.COMPLETED
    transitions: ClassVar[dict[ScheduledTaskEvent, ScheduledTaskState]] = {}


class ReminderStateHandler:
    """Общий интерфейс состояния напоминания."""

    state: ClassVar[ReminderState]
    transitions: ClassVar[dict[ReminderEvent, ReminderState]]

    def handle(self, event: ReminderEvent) -> ReminderState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownSchedulerEvent(
                self.state, event, reminder_allowed_events(self.state)
            ) from None


class ScheduledReminderState(ReminderStateHandler):
    """Напоминание сохранено и ждёт своего момента."""

    state = ReminderState.SCHEDULED
    transitions = {ReminderEvent.FIRE: ReminderState.DONE}


class DoneReminderState(ReminderStateHandler):
    """Напоминание выдано (уведомление в очереди)."""

    state = ReminderState.DONE
    transitions: ClassVar[dict[ReminderEvent, ReminderState]] = {}


#: Обработчик на каждое состояние задачи (паттерн State: состояние — объект).
TASK_HANDLERS: dict[ScheduledTaskState, TaskStateHandler] = {
    cls.state: cls() for cls in (ActiveState, PausedState, CompletedState)
}

#: Обработчик на каждое состояние напоминания.
REMINDER_HANDLERS: dict[ReminderState, ReminderStateHandler] = {
    cls.state: cls() for cls in (ScheduledReminderState, DoneReminderState)
}

#: Граф задачи: состояние → {событие: новое состояние} (для UI, лога и тестов).
ALLOWED_TASK_TRANSITIONS: dict[
    ScheduledTaskState, dict[ScheduledTaskEvent, ScheduledTaskState]
] = {state: dict(handler.transitions) for state, handler in TASK_HANDLERS.items()}

#: Граф напоминания: состояние → {событие: новое состояние}.
ALLOWED_REMINDER_TRANSITIONS: dict[
    ReminderState, dict[ReminderEvent, ReminderState]
] = {state: dict(handler.transitions) for state, handler in REMINDER_HANDLERS.items()}


def task_allowed_events(state: ScheduledTaskState) -> tuple[ScheduledTaskEvent, ...]:
    """События задачи, допустимые в состоянии (в порядке объявления ``Enum``)."""
    transitions = ALLOWED_TASK_TRANSITIONS.get(state, {})
    return tuple(event for event in ScheduledTaskEvent if event in transitions)


def reminder_allowed_events(state: ReminderState) -> tuple[ReminderEvent, ...]:
    """События напоминания, допустимые в состоянии."""
    transitions = ALLOWED_REMINDER_TRANSITIONS.get(state, {})
    return tuple(event for event in ReminderEvent if event in transitions)


class ScheduledTaskFSM:
    """Стейт-машина одной задачи планировщика: состояние + делегирование событий."""

    def __init__(self, state: ScheduledTaskState = ScheduledTaskState.ACTIVE):
        self._state = state

    @property
    def state(self) -> ScheduledTaskState:
        """Текущее состояние задачи."""
        return self._state

    def handle(self, event: ScheduledTaskEvent) -> ScheduledTaskState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = TASK_HANDLERS[self._state].handle(event)
        return self._state

    def can(self, event: ScheduledTaskEvent) -> bool:
        """Допустимо ли событие в текущем состоянии (проверка до вызова)."""
        return event in ALLOWED_TASK_TRANSITIONS[self._state]

    def allowed_events(self) -> tuple[ScheduledTaskEvent, ...]:
        """События, допустимые в текущем состоянии."""
        return task_allowed_events(self._state)


class ReminderFSM:
    """Стейт-машина одного напоминания: ждёт выдачи → выдано."""

    def __init__(self, state: ReminderState = ReminderState.SCHEDULED):
        self._state = state

    @property
    def state(self) -> ReminderState:
        """Текущее состояние напоминания."""
        return self._state

    def handle(self, event: ReminderEvent) -> ReminderState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = REMINDER_HANDLERS[self._state].handle(event)
        return self._state

    def can(self, event: ReminderEvent) -> bool:
        """Допустимо ли событие в текущем состоянии."""
        return event in ALLOWED_REMINDER_TRANSITIONS[self._state]

    def allowed_events(self) -> tuple[ReminderEvent, ...]:
        """События, допустимые в текущем состоянии."""
        return reminder_allowed_events(self._state)
