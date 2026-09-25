"""Тесты стейт-машины прогона оркестрации (день 20).

Граф тот же, что у пайплайна дня 19, и это осознанно: «прогон шагов» — один и тот
же процесс независимо от того, один сервер у него или три. Проверяется, что
значения ``enum`` совпадают со статусами ``orchestration_runs.status`` без
маппинга, что запрещённые пары дают явную ошибку с перечнем допустимых событий и
что ``can``/``allowed_events``/``reset`` не расходятся с графом.
"""
import pytest

from backend.domain.orchestration_fsm import (
    ALLOWED_TRANSITIONS,
    HANDLERS,
    OrchestrationEvent,
    OrchestrationFSM,
    OrchestrationState,
    UnknownOrchestrationEvent,
    allowed_events,
)

#: Все допустимые переходы графа: состояние, событие → новое состояние.
TRANSITIONS = (
    (OrchestrationState.IDLE, OrchestrationEvent.START, OrchestrationState.RUNNING),
    (OrchestrationState.RUNNING, OrchestrationEvent.ADVANCE, OrchestrationState.RUNNING),
    (OrchestrationState.RUNNING, OrchestrationEvent.FINISH, OrchestrationState.COMPLETED),
    (OrchestrationState.RUNNING, OrchestrationEvent.STOP, OrchestrationState.STOPPED),
    (OrchestrationState.RUNNING, OrchestrationEvent.FAIL, OrchestrationState.FAILED),
    (OrchestrationState.COMPLETED, OrchestrationEvent.START, OrchestrationState.RUNNING),
    (OrchestrationState.STOPPED, OrchestrationEvent.START, OrchestrationState.RUNNING),
    (OrchestrationState.FAILED, OrchestrationEvent.START, OrchestrationState.RUNNING),
)

#: Запрещённые пары: событие не того шага либо действие после терминального статуса.
FORBIDDEN = (
    (OrchestrationState.IDLE, OrchestrationEvent.ADVANCE),
    (OrchestrationState.IDLE, OrchestrationEvent.FINISH),
    (OrchestrationState.IDLE, OrchestrationEvent.STOP),
    (OrchestrationState.IDLE, OrchestrationEvent.FAIL),
    (OrchestrationState.RUNNING, OrchestrationEvent.START),
    (OrchestrationState.COMPLETED, OrchestrationEvent.ADVANCE),
    (OrchestrationState.COMPLETED, OrchestrationEvent.FINISH),
    (OrchestrationState.COMPLETED, OrchestrationEvent.STOP),
    (OrchestrationState.COMPLETED, OrchestrationEvent.FAIL),
    (OrchestrationState.STOPPED, OrchestrationEvent.ADVANCE),
    (OrchestrationState.STOPPED, OrchestrationEvent.FAIL),
    (OrchestrationState.FAILED, OrchestrationEvent.ADVANCE),
    (OrchestrationState.FAILED, OrchestrationEvent.STOP),
)

#: Значения состояний — ровно статусы запуска в БД (orchestration_runs.status) и API.
STATE_VALUES = (
    (OrchestrationState.IDLE, "idle"),
    (OrchestrationState.RUNNING, "running"),
    (OrchestrationState.COMPLETED, "completed"),
    (OrchestrationState.STOPPED, "stopped"),
    (OrchestrationState.FAILED, "failed"),
)


def test_allowed_transitions_match_expectations():
    """Граф переходов совпадает с таблицей: лишних и пропавших рёбер нет."""
    expected = {}
    for state, event, target in TRANSITIONS:
        expected.setdefault(state, {})[event] = target
    actual = {
        state: dict(transitions) for state, transitions in ALLOWED_TRANSITIONS.items()
    }
    assert actual == expected


@pytest.mark.parametrize("state,event,target", TRANSITIONS)
def test_transition_moves_to_expected_state(state, event, target):
    """Каждое объявленное ребро переводит автомат в ожидаемое состояние."""
    fsm = OrchestrationFSM(state=state)
    assert fsm.can(event) is True
    assert fsm.handle(event) is target
    assert fsm.state is target


@pytest.mark.parametrize("state,event", FORBIDDEN)
def test_forbidden_transition_is_an_explicit_error(state, event):
    """Недопустимое событие — ошибка с перечнем допустимых, а не «тихая» смена."""
    fsm = OrchestrationFSM(state=state)
    assert fsm.can(event) is False
    with pytest.raises(UnknownOrchestrationEvent) as exc:
        fsm.handle(event)
    assert exc.value.state is state
    assert exc.value.event is event
    assert "допустимы:" in str(exc.value)
    assert fsm.state is state, "состояние не должно меняться при отказе"


def test_error_text_lists_allowed_events():
    """Текст ошибки перечисляет ровно допустимые события состояния."""
    with pytest.raises(UnknownOrchestrationEvent) as exc:
        OrchestrationFSM().handle(OrchestrationEvent.FINISH)
    for event in allowed_events(OrchestrationState.IDLE):
        assert event.value in str(exc.value)


@pytest.mark.parametrize("state,value", STATE_VALUES)
def test_state_values_are_run_statuses(state, value):
    """Значение состояния совпадает со статусом строки запуска в БД и API."""
    assert state.value == value


def test_handlers_and_allowed_events_are_consistent():
    """На каждое состояние есть обработчик, и его переходы — это граф допуска."""
    assert set(HANDLERS) == set(OrchestrationState)
    for state, handler in HANDLERS.items():
        assert handler.state is state
        assert dict(handler.transitions) == ALLOWED_TRANSITIONS[state]
        assert allowed_events(state) == tuple(
            event for event in OrchestrationEvent if event in handler.transitions
        )


def test_fsm_walks_the_full_happy_path_and_resets():
    """Полный путь прогона: старт → шаги → завершение; ``reset`` возвращает в начало."""
    fsm = OrchestrationFSM()
    assert fsm.handle(OrchestrationEvent.START) is OrchestrationState.RUNNING
    assert fsm.handle(OrchestrationEvent.ADVANCE) is OrchestrationState.RUNNING
    assert fsm.handle(OrchestrationEvent.FINISH) is OrchestrationState.COMPLETED
    assert fsm.allowed_events() == (OrchestrationEvent.START,)
    assert fsm.reset() is OrchestrationState.IDLE
    assert fsm.state is OrchestrationState.IDLE
