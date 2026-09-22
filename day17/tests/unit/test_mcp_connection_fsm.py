"""Тесты FSM подключения к MCP-серверу (день 16): таблица переходов и негативы.

Первая часть — параметризованная таблица пар (состояние, событие) → ожидаемое
состояние; она же сверяется с графом ``ALLOWED_TRANSITIONS`` (его читают
``/mcp/status`` и UI, поэтому таблица и граф не имеют права разойтись).
Вторая — негативный сценарий: событие, недопустимое в состоянии (например,
``CONNECTED`` + ``CONNECT``), падает с ``UnknownMCPConnectionEvent`` и НЕ меняет
состояние.
"""
import pytest

from backend.domain.mcp_connection_fsm import (
    ALLOWED_TRANSITIONS,
    MCPConnectionEvent,
    MCPConnectionFSM,
    MCPConnectionState,
    UnknownMCPConnectionEvent,
    allowed_events,
)

S = MCPConnectionState
E = MCPConnectionEvent

#: Таблица переходов: (состояние, событие) → новое состояние.
TRANSITIONS = [
    (S.DISCONNECTED, E.CONNECT, S.CONNECTING),
    (S.DISCONNECTED, E.DISCONNECT, S.DISCONNECTED),
    (S.CONNECTING, E.CONNECTED, S.CONNECTED),
    (S.CONNECTING, E.FAIL, S.ERROR),
    (S.CONNECTING, E.DISCONNECT, S.DISCONNECTED),
    (S.CONNECTED, E.DISCONNECT, S.DISCONNECTED),
    (S.CONNECTED, E.FAIL, S.ERROR),
    (S.ERROR, E.CONNECT, S.CONNECTING),
    (S.ERROR, E.DISCONNECT, S.DISCONNECTED),
]

#: Пары, которых в графе нет: событие в этом состоянии — ошибка.
UNKNOWN = [
    (S.DISCONNECTED, E.CONNECTED),
    (S.DISCONNECTED, E.FAIL),
    (S.CONNECTING, E.CONNECT),
    (S.CONNECTED, E.CONNECT),
    (S.CONNECTED, E.CONNECTED),
    (S.ERROR, E.CONNECTED),
    (S.ERROR, E.FAIL),
]


@pytest.mark.parametrize("state,event,expected", TRANSITIONS)
def test_transition_table(state, event, expected):
    """Событие переводит состояние ровно в одно объявленное состояние."""
    assert MCPConnectionFSM(state).handle(event) is expected
    assert ALLOWED_TRANSITIONS[state][event] is expected


@pytest.mark.parametrize("state,event", UNKNOWN)
def test_unknown_event_raises_and_keeps_state(state, event):
    """Недопустимое событие — явная ошибка; состояние не меняется."""
    fsm = MCPConnectionFSM(state)
    with pytest.raises(UnknownMCPConnectionEvent) as exc:
        fsm.handle(event)
    assert (exc.value.state, exc.value.event) == (state, event)
    assert fsm.state is state
    assert event.value in str(exc.value) or state.value in str(exc.value)


def test_error_message_lists_allowed_events():
    """Текст отказа перечисляет, что в этом состоянии допустимо."""
    with pytest.raises(UnknownMCPConnectionEvent) as exc:
        MCPConnectionFSM(S.CONNECTED).handle(E.CONNECT)
    assert "disconnect" in str(exc.value)
    assert "fail" in str(exc.value)


def test_repeated_disconnect_is_idempotent():
    """Повторное закрытие уже закрытого соединения — не ошибка (безопасный no-op)."""
    fsm = MCPConnectionFSM()
    assert fsm.handle(E.DISCONNECT) is S.DISCONNECTED
    assert fsm.handle(E.DISCONNECT) is S.DISCONNECTED


def test_success_path_and_failure_path():
    """Полный путь: подключение → работа → закрытие; обрыв ведёт в ERROR."""
    fsm = MCPConnectionFSM()
    assert fsm.handle(E.CONNECT) is S.CONNECTING
    assert fsm.handle(E.CONNECTED) is S.CONNECTED
    assert fsm.handle(E.DISCONNECT) is S.DISCONNECTED

    broken = MCPConnectionFSM()
    broken.handle(E.CONNECT)
    assert broken.handle(E.FAIL) is S.ERROR
    assert broken.handle(E.CONNECT) is S.CONNECTING  # повтор после ошибки разрешён


def test_can_and_allowed_events_agree_with_graph():
    """``can`` и ``allowed_events`` — та же таблица, что у графа."""
    for state in S:
        events = allowed_events(state)
        assert events == tuple(e for e in E if e in ALLOWED_TRANSITIONS[state])


def test_can_rejects_foreign_event():
    """``can`` не пропускает событие, которого нет в состоянии."""
    fsm = MCPConnectionFSM(S.DISCONNECTED)
    assert fsm.can(E.CONNECT) and not fsm.can(E.CONNECTED)
    assert allowed_events(S.CONNECTED) == (E.FAIL, E.DISCONNECT)


def test_reset_returns_to_disconnected():
    """``reset`` — служебный сброс без событий (нужен для тестов и ``close``)."""
    fsm = MCPConnectionFSM(S.ERROR)
    fsm.reset()
    assert fsm.state is S.DISCONNECTED
