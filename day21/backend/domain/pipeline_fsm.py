"""Стейт-машина прогона пайплайна: состояния, события и граф переходов (день 19).

Один прогон — один автомат: ``IDLE`` → ``RUNNING`` → терминальное состояние.
События приходят из цикла шагов (``backend/services/pipeline.py``), а значения
состояний — это ровно те статусы, что лежат в колонке ``pipeline_runs.status`` и
уходят в API и интерфейс: маппинг не нужен.

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

Неизвестное событие в состоянии — явная ошибка ``UnknownPipelineEvent`` с
перечнем допустимых: «тихо ничего не сделать» здесь недопустимо, потому что статус
прогона уходит в историю и по нему судят о результате.

Модуль чистый: ``enum`` и стандартная библиотека (эталон — ``mcp_tool_call.py``).
"""
from __future__ import annotations

import enum
from typing import ClassVar


class PipelineState(enum.Enum):
    """Состояние прогона пайплайна (оно же — статус запуска в БД и API)."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class PipelineEvent(enum.Enum):
    """Событие, которое двигает прогон по графу."""

    START = "start"
    ADVANCE = "advance"
    FINISH = "finish"
    STOP = "stop"
    FAIL = "fail"


class UnknownPipelineEvent(Exception):
    """Событие, недопустимое в текущем состоянии прогона."""

    def __init__(self, state: PipelineState, event: PipelineEvent) -> None:
        self.state = state
        self.event = event
        allowed = ", ".join(item.value for item in allowed_events(state)) or "—"
        super().__init__(
            f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
            f"допустимы: {allowed}"
        )


class PipelineStateHandler:
    """Общий интерфейс состояния: одно событие → ровно одно новое состояние."""

    state: ClassVar[PipelineState]
    transitions: ClassVar[dict[PipelineEvent, PipelineState]]

    def handle(self, event: PipelineEvent) -> PipelineState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownPipelineEvent(self.state, event) from None


class IdleState(PipelineStateHandler):
    """Прогон не начат: шаги ещё не выполнялись."""

    state = PipelineState.IDLE
    transitions = {PipelineEvent.START: PipelineState.RUNNING}


class RunningState(PipelineStateHandler):
    """Шаги выполняются: следующий шаг, завершение, досрочная остановка или сбой."""

    state = PipelineState.RUNNING
    transitions = {
        PipelineEvent.ADVANCE: PipelineState.RUNNING,
        PipelineEvent.FINISH: PipelineState.COMPLETED,
        PipelineEvent.STOP: PipelineState.STOPPED,
        PipelineEvent.FAIL: PipelineState.FAILED,
    }


class CompletedState(PipelineStateHandler):
    """Все шаги выполнены успешно."""

    state = PipelineState.COMPLETED
    transitions = {PipelineEvent.START: PipelineState.RUNNING}


class StoppedState(PipelineStateHandler):
    """Прогон завершён досрочно: условие шага не выполнено."""

    state = PipelineState.STOPPED
    transitions = {PipelineEvent.START: PipelineState.RUNNING}


class FailedState(PipelineStateHandler):
    """Прогон остановлен: шаг завершился ошибкой."""

    state = PipelineState.FAILED
    transitions = {PipelineEvent.START: PipelineState.RUNNING}


#: Обработчик на каждое состояние (паттерн State: состояние — объект с поведением).
HANDLERS: dict[PipelineState, PipelineStateHandler] = {
    cls.state: cls()
    for cls in (IdleState, RunningState, CompletedState, StoppedState, FailedState)
}

#: Граф допуска: состояние → {событие: новое состояние} (для UI, журнала и тестов).
ALLOWED_TRANSITIONS: dict[PipelineState, dict[PipelineEvent, PipelineState]] = {
    state: dict(handler.transitions) for state, handler in HANDLERS.items()
}


def allowed_events(state: PipelineState) -> tuple[PipelineEvent, ...]:
    """События, допустимые в состоянии (в порядке объявления ``PipelineEvent``)."""
    transitions = ALLOWED_TRANSITIONS.get(state, {})
    return tuple(event for event in PipelineEvent if event in transitions)


class PipelineFSM:
    """Стейт-машина прогона: хранит состояние и делегирует события ему."""

    def __init__(self, state: PipelineState = PipelineState.IDLE) -> None:
        self._state = state

    @property
    def state(self) -> PipelineState:
        """Текущее состояние прогона."""
        return self._state

    def handle(self, event: PipelineEvent) -> PipelineState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = HANDLERS[self._state].handle(event)
        return self._state

    def can(self, event: PipelineEvent) -> bool:
        """Допустимо ли событие в текущем состоянии."""
        return event in ALLOWED_TRANSITIONS.get(self._state, {})

    def allowed_events(self) -> tuple[PipelineEvent, ...]:
        """События, допустимые прямо сейчас."""
        return allowed_events(self._state)

    def reset(self) -> PipelineState:
        """Возвращает автомат в исходное состояние."""
        self._state = PipelineState.IDLE
        return self._state
