"""Стейт-машина управления контекстом диалога (день 9).

Что это.
    Конечный автомат, который решает, когда историю диалога пора сжимать
    (суммаризировать), а когда — просто накапливать реплики. Состояния и
    события описаны через `enum.Enum`, переходы — паттерном State: у каждого
    состояния свой маленький класс с общим интерфейсом `handle(event)`,
    который возвращает следующее состояние. Классы состояний не знают ни про
    UI, ни про БД, ни про сеть — это чистый домен (см. AGENTS.md).

    Диаграмма переходов (единственный источник правды, см. TRANSITIONS в тестах):

        IDLE            --TURN_ADDED--------> TRACKING
        IDLE            --DISABLED/ENABLED--> IDLE
        IDLE            --RESET-------------> IDLE
        TRACKING        --TURN_ADDED--------> TRACKING
        TRACKING        --THRESHOLD_REACHED-> SUMMARY_PENDING
        TRACKING        --RESET/DISABLED----> IDLE
        SUMMARY_PENDING --TURN_ADDED--------> SUMMARY_PENDING
        SUMMARY_PENDING --SUMMARY_REQUESTED-> SUMMARIZING
        SUMMARY_PENDING --RESET/DISABLED----> IDLE
        SUMMARIZING     --SUMMARY_READY-----> TRACKING
        SUMMARIZING     --SUMMARY_FAILED----> ERROR
        ERROR           --TURN_ADDED--------> TRACKING
        ERROR           --RESET/DISABLED----> IDLE

    Любая другая пара «состояние × событие» — явная ошибка `UnknownContextEvent`
    (никаких «тихих» зависаний). В частности, в SUMMARIZING событие RESET не
    описано осознанно: пока идёт вызов суммаризации, прерывать его нечем.

Как запустить.
    Модуль не имеет побочных эффектов на импорте и не требует зависимостей
    кроме стандартной библиотеки. Проверяется тестами:

        # из папки day9
        python -m pytest -q tests/unit/test_context_fsm.py

    Пример использования:

        machine = ContextMachine()
        machine.dispatch(ContextEvent.TURN_ADDED)        # -> tracking
        machine.dispatch(ContextEvent.THRESHOLD_REACHED)  # -> summary_pending
        machine.state_value()                             # "summary_pending"
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "ContextState",
    "ContextEvent",
    "UnknownContextEvent",
    "ContextStateBase",
    "IdleState",
    "TrackingState",
    "SummaryPendingState",
    "SummarizingState",
    "ErrorState",
    "ContextMachine",
    "STATE_BY_VALUE",
    "STATE_CLASS_BY_STATE",
    "state_from_value",
]


class ContextState(Enum):
    """Состояния процесса сжатия контекста."""

    IDLE = "idle"  # сжатие выключено или накапливать нечего
    TRACKING = "tracking"  # копим реплики выше watermark, порог не достигнут
    SUMMARY_PENDING = "summary_pending"  # порог достигнут, требуется суммаризация
    SUMMARIZING = "summarizing"  # вызов суммаризации в полёте
    ERROR = "error"  # суммаризация упала, повтор на следующем ходу


class ContextEvent(Enum):
    """События, которые машина умеет обрабатывать."""

    TURN_ADDED = "turn_added"
    THRESHOLD_REACHED = "threshold_reached"
    SUMMARY_REQUESTED = "summary_requested"
    SUMMARY_READY = "summary_ready"
    SUMMARY_FAILED = "summary_failed"
    RESET = "reset"
    DISABLED = "disabled"
    ENABLED = "enabled"


class UnknownContextEvent(Exception):
    """Событие не описано для текущего состояния (см. AGENTS.md: явная ошибка)."""


class ContextStateBase:
    """Базовое состояние: общий интерфейс `handle` и поведение по умолчанию.

    Поведение по умолчанию — явная ошибка: если подкласс не переопределил
    событие, значит, для этого состояния оно не описано.
    """

    state: ContextState

    def handle(self, event: ContextEvent) -> "ContextStateBase":
        """Обработать событие и вернуть следующее состояние.

        Подклассы переопределяют метод только для своих событий, а для всех
        прочих вызывают `super().handle(event)` — так таблица переходов каждого
        состояния читается одним взглядом.
        """
        raise UnknownContextEvent(
            f"Событие {event.value} не описано для состояния {self.state.value}"
        )

    def __str__(self) -> str:
        return self.state.value


class IdleState(ContextStateBase):
    """IDLE: сжатие выключено или накапливать нечего."""

    state = ContextState.IDLE

    def handle(self, event: ContextEvent) -> ContextStateBase:
        if event is ContextEvent.TURN_ADDED:
            return TrackingState()
        if event is ContextEvent.DISABLED:
            return IdleState()
        if event is ContextEvent.ENABLED:
            return IdleState()
        if event is ContextEvent.RESET:
            return IdleState()
        return super().handle(event)


class TrackingState(ContextStateBase):
    """TRACKING: копим реплики выше watermark, порог ещё не достигнут."""

    state = ContextState.TRACKING

    def handle(self, event: ContextEvent) -> ContextStateBase:
        if event is ContextEvent.TURN_ADDED:
            return TrackingState()
        if event is ContextEvent.THRESHOLD_REACHED:
            return SummaryPendingState()
        if event is ContextEvent.RESET:
            return IdleState()
        if event is ContextEvent.DISABLED:
            return IdleState()
        return super().handle(event)


class SummaryPendingState(ContextStateBase):
    """SUMMARY_PENDING: порог достигнут, требуется вызвать суммаризацию."""

    state = ContextState.SUMMARY_PENDING

    def handle(self, event: ContextEvent) -> ContextStateBase:
        if event is ContextEvent.TURN_ADDED:
            return SummaryPendingState()
        if event is ContextEvent.SUMMARY_REQUESTED:
            return SummarizingState()
        if event is ContextEvent.RESET:
            return IdleState()
        if event is ContextEvent.DISABLED:
            return IdleState()
        return super().handle(event)


class SummarizingState(ContextStateBase):
    """SUMMARIZING: вызов суммаризации в полёте.

    Пока вызов не завершится, машина принимает только его исход —
    SUMMARY_READY или SUMMARY_FAILED. Остальные события (в том числе RESET)
    считаются ошибкой: прерывать полёт нечем.
    """

    state = ContextState.SUMMARIZING

    def handle(self, event: ContextEvent) -> ContextStateBase:
        if event is ContextEvent.SUMMARY_READY:
            return TrackingState()
        if event is ContextEvent.SUMMARY_FAILED:
            return ErrorState()
        return super().handle(event)


class ErrorState(ContextStateBase):
    """ERROR: суммаризация упала, повтор на следующем ходу."""

    state = ContextState.ERROR

    def handle(self, event: ContextEvent) -> ContextStateBase:
        if event is ContextEvent.TURN_ADDED:
            return TrackingState()
        if event is ContextEvent.RESET:
            return IdleState()
        if event is ContextEvent.DISABLED:
            return IdleState()
        return super().handle(event)


# Таблица «значение Enum → член Enum» и «член Enum → класс состояния».
# Нужны, чтобы восстанавливать машину из API/БД, где состояние хранится строкой.
STATE_BY_VALUE: dict[str, ContextState] = {state.value: state for state in ContextState}

STATE_CLASS_BY_STATE: dict[ContextState, type[ContextStateBase]] = {
    ContextState.IDLE: IdleState,
    ContextState.TRACKING: TrackingState,
    ContextState.SUMMARY_PENDING: SummaryPendingState,
    ContextState.SUMMARIZING: SummarizingState,
    ContextState.ERROR: ErrorState,
}


def state_from_value(value: str) -> ContextStateBase:
    """Восстановить объект состояния по его строковому значению.

    Используется при чтении состояния из API/БД. Неизвестное значение —
    явная ошибка `ValueError`, а не «тихий» откат в IDLE.
    """
    try:
        state = STATE_BY_VALUE[value]
    except KeyError:
        raise ValueError(f"Неизвестное состояние контекста: {value!r}") from None
    return STATE_CLASS_BY_STATE[state]()


class ContextMachine:
    """Хранит текущее состояние и делегирует ему обработку события."""

    def __init__(self, state: ContextStateBase | None = None) -> None:
        # Состояние по умолчанию — IDLE; передавать его снаружи можно, например,
        # при восстановлении из БД.
        self._state: ContextStateBase = state if state is not None else IdleState()

    @property
    def state(self) -> ContextStateBase:
        """Текущее состояние (объект-класс состояния)."""
        return self._state

    def dispatch(self, event: ContextEvent) -> ContextStateBase:
        """Обработать событие, запомнить новое состояние и вернуть его."""
        self._state = self._state.handle(event)
        return self._state

    def reset(self) -> ContextStateBase:
        """Сбросить машину в IDLE (сокращение для `dispatch(RESET)`)."""
        return self.dispatch(ContextEvent.RESET)

    def state_value(self) -> str:
        """Строковое значение состояния — для API/UI и логов."""
        return self._state.state.value

    def is_idle(self) -> bool:
        """Находится ли машина в состоянии IDLE."""
        return self._state.state is ContextState.IDLE
