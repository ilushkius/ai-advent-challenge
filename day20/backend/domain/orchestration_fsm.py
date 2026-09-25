"""Стейт-машина прогона оркестрации: состояния, события и граф переходов (день 20).

Один прогон — один автомат: ``IDLE`` → ``RUNNING`` → терминальное состояние.
События приходят из цикла шагов (``backend/services/orchestrator.py``), а значения
состояний — это ровно те статусы, что лежат в колонке ``orchestration_runs.status``
и уходят в API, интерфейс и промпт: маппинг не нужен.

Граф переходов однозначен:

===================  ===================================================
состояние            событие → новое состояние
===================  ===================================================
``IDLE``             ``START`` → ``RUNNING``
``RUNNING``          ``ADVANCE`` → ``RUNNING`` (шаг выполнен, есть следующие);
                     ``FINISH`` → ``COMPLETED`` (последний шаг выполнен);
                     ``STOP`` → ``STOPPED`` (условие шага не выполнено);
                     ``FAIL`` → ``FAILED`` (шаг завершился ошибкой)
``COMPLETED``        ``START`` → ``RUNNING`` (следующий прогон)
``STOPPED``          ``START`` → ``RUNNING``
``FAILED``           ``START`` → ``RUNNING``
===================  ===================================================

Неизвестное событие в состоянии — явная ошибка ``UnknownOrchestrationEvent`` с
перечнем допустимых: «тихо ничего не сделать» здесь недопустимо, потому что статус
прогона уходит в историю, и по нему судят о результате.

Модуль чистый: ``enum`` и стандартная библиотека (эталон — ``pipeline_fsm.py``).
"""
from __future__ import annotations

import enum
from typing import ClassVar


class OrchestrationState(enum.Enum):
    """Состояние прогона оркестрации (оно же — статус запуска в БД и API)."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class OrchestrationEvent(enum.Enum):
    """Событие, которое двигает прогон по графу."""

    START = "start"
    ADVANCE = "advance"
    FINISH = "finish"
    STOP = "stop"
    FAIL = "fail"


class UnknownOrchestrationEvent(Exception):
    """Событие, недопустимое в текущем состоянии прогона."""

    def __init__(self, state: OrchestrationState, event: OrchestrationEvent) -> None:
        self.state = state
        self.event = event
        allowed = ", ".join(item.value for item in allowed_events(state)) or "—"
        super().__init__(
            f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
            f"допустимы: {allowed}"
        )


class OrchestrationStateHandler:
    """Общий интерфейс состояния: одно событие → ровно одно новое состояние."""

    state: ClassVar[OrchestrationState]
    transitions: ClassVar[dict[OrchestrationEvent, OrchestrationState]]

    def handle(self, event: OrchestrationEvent) -> OrchestrationState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownOrchestrationEvent(self.state, event) from None


class IdleState(OrchestrationStateHandler):
    """Прогон не начат: шаги ещё не выполнялись."""

    state = OrchestrationState.IDLE
    transitions = {OrchestrationEvent.START: OrchestrationState.RUNNING}


class RunningState(OrchestrationStateHandler):
    """Шаги выполняются: следующий шаг, завершение, досрочная остановка или сбой."""

    state = OrchestrationState.RUNNING
    transitions = {
        OrchestrationEvent.ADVANCE: OrchestrationState.RUNNING,
        OrchestrationEvent.FINISH: OrchestrationState.COMPLETED,
        OrchestrationEvent.STOP: OrchestrationState.STOPPED,
        OrchestrationEvent.FAIL: OrchestrationState.FAILED,
    }


class CompletedState(OrchestrationStateHandler):
    """Все шаги выполнены успешно."""

    state = OrchestrationState.COMPLETED
    transitions = {OrchestrationEvent.START: OrchestrationState.RUNNING}


class StoppedState(OrchestrationStateHandler):
    """Прогон завершён досрочно: условие шага не выполнено."""

    state = OrchestrationState.STOPPED
    transitions = {OrchestrationEvent.START: OrchestrationState.RUNNING}


class FailedState(OrchestrationStateHandler):
    """Прогон остановлен: шаг завершился ошибкой."""

    state = OrchestrationState.FAILED
    transitions = {OrchestrationEvent.START: OrchestrationState.RUNNING}


#: Обработчик на каждое состояние (паттерн State: состояние — объект с поведением).
HANDLERS: dict[OrchestrationState, OrchestrationStateHandler] = {
    cls.state: cls()
    for cls in (IdleState, RunningState, CompletedState, StoppedState, FailedState)
}

#: Граф допуска: состояние → {событие: новое состояние} (для UI, журнала и тестов).
ALLOWED_TRANSITIONS: dict[
    OrchestrationState, dict[OrchestrationEvent, OrchestrationState]
] = {state: dict(handler.transitions) for state, handler in HANDLERS.items()}


def allowed_events(state: OrchestrationState) -> tuple[OrchestrationEvent, ...]:
    """События, допустимые в состоянии (в порядке объявления ``OrchestrationEvent``)."""
    transitions = ALLOWED_TRANSITIONS.get(state, {})
    return tuple(event for event in OrchestrationEvent if event in transitions)


class OrchestrationFSM:
    """Стейт-машина прогона: хранит состояние и делегирует события ему."""

    def __init__(self, state: OrchestrationState = OrchestrationState.IDLE) -> None:
        self._state = state

    @property
    def state(self) -> OrchestrationState:
        """Текущее состояние прогона."""
        return self._state

    def handle(self, event: OrchestrationEvent) -> OrchestrationState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = HANDLERS[self._state].handle(event)
        return self._state

    def can(self, event: OrchestrationEvent) -> bool:
        """Допустимо ли событие в текущем состоянии."""
        return event in ALLOWED_TRANSITIONS.get(self._state, {})

    def allowed_events(self) -> tuple[OrchestrationEvent, ...]:
        """События, допустимые прямо сейчас."""
        return allowed_events(self._state)

    def reset(self) -> OrchestrationState:
        """Возвращает автомат в исходное состояние."""
        self._state = OrchestrationState.IDLE
        return self._state
