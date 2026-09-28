"""Тесты стейт-машины управления контекстом (день 9).

Что это.
    Модульные тесты `backend/context_fsm.py` на pytest. Главный тест —
    параметризованная таблица переходов: она записана явно и читается как
    диаграмма автомата. Негативные кейсы (неизвестное событие для состояния)
    проверяются там же — ожидаем `UnknownContextEvent`.

Как запустить.
        # из папки day9 (pytest.ini добавит корень дня в sys.path)
        python -m pytest -q tests/unit/test_context_fsm.py
"""

from __future__ import annotations

import pytest

from backend.domain.context_fsm import (
    STATE_BY_VALUE,
    ContextEvent,
    ContextMachine,
    ContextState,
    ContextStateBase,
    ErrorState,
    IdleState,
    SummaryPendingState,
    SummarizingState,
    TrackingState,
    UnknownContextEvent,
    state_from_value,
)

# Класс состояния по члену Enum — чтобы строить машину в каждом тесте.
STATE_CLASS_BY_STATE: dict[ContextState, type[ContextStateBase]] = {
    ContextState.IDLE: IdleState,
    ContextState.TRACKING: TrackingState,
    ContextState.SUMMARY_PENDING: SummaryPendingState,
    ContextState.SUMMARIZING: SummarizingState,
    ContextState.ERROR: ErrorState,
}

# Таблица переходов — ЕДИНСТВЕННЫЙ источник правды и наглядная диаграмма.
# Если пары (состояние, событие) здесь нет — ожидаем UnknownContextEvent.
TRANSITIONS: dict[ContextState, dict[ContextEvent, ContextState]] = {
    ContextState.IDLE: {
        ContextEvent.TURN_ADDED: ContextState.TRACKING,
        ContextEvent.DISABLED: ContextState.IDLE,
        ContextEvent.ENABLED: ContextState.IDLE,
        ContextEvent.RESET: ContextState.IDLE,
    },
    ContextState.TRACKING: {
        ContextEvent.TURN_ADDED: ContextState.TRACKING,
        ContextEvent.THRESHOLD_REACHED: ContextState.SUMMARY_PENDING,
        ContextEvent.RESET: ContextState.IDLE,
        ContextEvent.DISABLED: ContextState.IDLE,
    },
    ContextState.SUMMARY_PENDING: {
        ContextEvent.TURN_ADDED: ContextState.SUMMARY_PENDING,
        ContextEvent.SUMMARY_REQUESTED: ContextState.SUMMARIZING,
        ContextEvent.RESET: ContextState.IDLE,
        ContextEvent.DISABLED: ContextState.IDLE,
    },
    ContextState.SUMMARIZING: {
        ContextEvent.SUMMARY_READY: ContextState.TRACKING,
        ContextEvent.SUMMARY_FAILED: ContextState.ERROR,
        # RESET здесь осознанно НЕ описан: полёт прерывать нечем.
    },
    ContextState.ERROR: {
        ContextEvent.TURN_ADDED: ContextState.TRACKING,
        ContextEvent.RESET: ContextState.IDLE,
        ContextEvent.DISABLED: ContextState.IDLE,
    },
}


@pytest.mark.parametrize("state", list(ContextState), ids=lambda s: s.value)
@pytest.mark.parametrize("event", list(ContextEvent), ids=lambda e: e.value)
def test_transition_table(state: ContextState, event: ContextEvent) -> None:
    """Каждая пара «состояние × событие» даёт ровно один результат.

    Есть в таблице — конкретное следующее состояние; нет — UnknownContextEvent,
    и текущее состояние не меняется (никаких «тихих» зависаний).
    """
    machine = ContextMachine(STATE_CLASS_BY_STATE[state]())
    expected = TRANSITIONS.get(state, {}).get(event)

    if expected is None:
        with pytest.raises(UnknownContextEvent):
            machine.dispatch(event)
        assert machine.state.state is state
        return

    result = machine.dispatch(event)
    assert result.state is expected
    assert machine.state.state is expected


def test_all_states_reachable_from_idle() -> None:
    """Каждое состояние достижимо хотя бы одним путём от IdleState() (BFS)."""
    seen = {ContextState.IDLE}
    queue = [ContextState.IDLE]

    while queue:
        current = queue.pop(0)
        for event in ContextEvent:
            nxt = TRANSITIONS.get(current, {}).get(event)
            if nxt is not None and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)

    assert seen == set(ContextState)


def test_dispatch_is_deterministic() -> None:
    """Один и тот же вход дважды даёт один и тот же результат."""
    first = ContextMachine().dispatch(ContextEvent.TURN_ADDED)
    second = ContextMachine().dispatch(ContextEvent.TURN_ADDED)

    assert type(first) is type(second)
    assert first.state is second.state


def test_dispatch_mutates_machine_state() -> None:
    """dispatch запоминает новое состояние и возвращает именно его."""
    machine = ContextMachine()
    assert machine.state.state is ContextState.IDLE

    result = machine.dispatch(ContextEvent.TURN_ADDED)

    assert result is machine.state
    assert machine.state.state is ContextState.TRACKING
    assert machine.state_value() == ContextState.TRACKING.value


def test_full_happy_path_and_error_path() -> None:
    """Сквозной путь: накопление → порог → суммаризация → успех/падение."""
    ok = ContextMachine()
    ok.dispatch(ContextEvent.TURN_ADDED)
    ok.dispatch(ContextEvent.THRESHOLD_REACHED)
    ok.dispatch(ContextEvent.SUMMARY_REQUESTED)
    assert ok.state_value() == ContextState.SUMMARIZING.value
    ok.dispatch(ContextEvent.SUMMARY_READY)
    assert ok.state_value() == ContextState.TRACKING.value

    failed = ContextMachine()
    failed.dispatch(ContextEvent.TURN_ADDED)
    failed.dispatch(ContextEvent.THRESHOLD_REACHED)
    failed.dispatch(ContextEvent.SUMMARY_REQUESTED)
    failed.dispatch(ContextEvent.SUMMARY_FAILED)
    assert failed.state_value() == ContextState.ERROR.value
    failed.dispatch(ContextEvent.TURN_ADDED)  # повтор на следующем ходу
    assert failed.state_value() == ContextState.TRACKING.value


def test_reset_and_is_idle() -> None:
    """reset() возвращает машину в IDLE, is_idle() это отражает."""
    machine = ContextMachine()
    assert machine.is_idle()

    machine.dispatch(ContextEvent.TURN_ADDED)
    assert not machine.is_idle()

    machine.reset()
    assert machine.is_idle()
    assert machine.state_value() == ContextState.IDLE.value


@pytest.mark.parametrize("state", list(ContextState), ids=lambda s: s.value)
def test_state_from_value_restores_each_state(state: ContextState) -> None:
    """state_from_value восстанавливает объект состояния по строковому значению."""
    restored = state_from_value(state.value)

    assert restored.state is state
    assert STATE_BY_VALUE[state.value] is state


def test_state_from_value_unknown_raises() -> None:
    """Неизвестное значение состояния — явный ValueError."""
    with pytest.raises(ValueError):
        state_from_value("нет-такого")


def test_no_side_effects_on_import() -> None:
    """Свежая машина всегда в IDLE, инстансы не влияют друг на друга."""
    first = ContextMachine()
    second = ContextMachine()
    assert first.state_value() == "idle"
    assert second.state_value() == "idle"

    first.dispatch(ContextEvent.TURN_ADDED)

    assert second.state_value() == "idle"
    assert ContextMachine().state_value() == "idle"


def test_unknown_context_event_is_exception_with_readable_message() -> None:
    """UnknownContextEvent — подкласс Exception, текст содержит событие и состояние."""
    assert issubclass(UnknownContextEvent, Exception)

    machine = ContextMachine(SummarizingState())
    with pytest.raises(UnknownContextEvent) as exc_info:
        machine.dispatch(ContextEvent.RESET)

    message = str(exc_info.value)
    assert ContextEvent.RESET.value in message
    assert ContextState.SUMMARIZING.value in message
