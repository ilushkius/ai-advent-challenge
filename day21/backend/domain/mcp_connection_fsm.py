"""FSM подключения к MCP-серверу (день 16): состояния, события, переходы.

Состояния и события — члены ``enum.Enum`` (значения читаемые: попадают в API и
в лог без маппинга), переходы — паттерном State: у каждого состояния свой класс
с ``handle(event)``, а ``MCPConnectionFSM`` хранит текущее состояние и
делегирует ему обработку. Неизвестное событие в состоянии — явная ошибка
``UnknownMCPConnectionEvent``, а не «тихое» зависание.

Граф переходов однозначен:

===================================  ==========================================
состояние                            событие → новое состояние
===================================  ==========================================
``DISCONNECTED``                     ``CONNECT`` → ``CONNECTING``;
                                     ``DISCONNECT`` → ``DISCONNECTED`` (идемпотентно)
``CONNECTING``                       ``CONNECTED`` → ``CONNECTED``;
                                     ``FAIL`` → ``ERROR``;
                                     ``DISCONNECT`` → ``DISCONNECTED`` (отмена)
``CONNECTED``                        ``DISCONNECT`` → ``DISCONNECTED``;
                                     ``FAIL`` → ``ERROR`` (обрыв связи)
``ERROR``                            ``CONNECT`` → ``CONNECTING`` (повтор);
                                     ``DISCONNECT`` → ``DISCONNECTED`` (сброс ошибки)
===================================  ==========================================

Остальные пары (``DISCONNECTED`` + ``CONNECTED``, ``CONNECTED`` + ``CONNECT``,
``ERROR`` + ``FAIL`` и т. п.) — ошибка: состояние подключения меняется только
пройденным шагом. Повторное подключение к уже подключённому серверу — это два
события (``DISCONNECT``, затем ``CONNECT``), а не одно: так в журнале видно, что
старое соединение закрыто, а не потеряно.

Модуль не знает ни про MCP SDK, ни про HTTP, ни про Streamlit: это чистые
правила, которые тестируются без сети (tests/unit/test_mcp_connection_fsm.py).
"""
from __future__ import annotations

import enum
from typing import ClassVar


class MCPConnectionState(enum.Enum):
    """Состояние подключения к MCP-серверу."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class MCPConnectionEvent(enum.Enum):
    """Событие, которое двигает подключение по графу."""

    CONNECT = "connect"
    CONNECTED = "connected"
    FAIL = "fail"
    DISCONNECT = "disconnect"


class UnknownMCPConnectionEvent(Exception):
    """Событие, недопустимое в текущем состоянии подключения."""

    def __init__(self, state: MCPConnectionState, event: MCPConnectionEvent):
        self.state = state
        self.event = event
        allowed = ", ".join(e.value for e in allowed_events(state)) or "—"
        super().__init__(
            f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
            f"допустимы: {allowed}"
        )


class MCPStateHandler:
    """Общий интерфейс состояния: одно событие → ровно одно новое состояние."""

    state: ClassVar[MCPConnectionState]
    transitions: ClassVar[dict[MCPConnectionEvent, MCPConnectionState]]

    def handle(self, event: MCPConnectionEvent) -> MCPConnectionState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownMCPConnectionEvent(self.state, event) from None


class DisconnectedState(MCPStateHandler):
    """Соединения нет: подключение открыто, повторное закрытие — no-op."""

    state = MCPConnectionState.DISCONNECTED
    transitions = {
        MCPConnectionEvent.CONNECT: MCPConnectionState.CONNECTING,
        MCPConnectionEvent.DISCONNECT: MCPConnectionState.DISCONNECTED,
    }


class ConnectingState(MCPStateHandler):
    """Идёт установка соединения: успех, ошибка или отмена."""

    state = MCPConnectionState.CONNECTING
    transitions = {
        MCPConnectionEvent.CONNECTED: MCPConnectionState.CONNECTED,
        MCPConnectionEvent.FAIL: MCPConnectionState.ERROR,
        MCPConnectionEvent.DISCONNECT: MCPConnectionState.DISCONNECTED,
    }


class ConnectedState(MCPStateHandler):
    """Соединение открыто: закрытие вручную или обрыв связи."""

    state = MCPConnectionState.CONNECTED
    transitions = {
        MCPConnectionEvent.DISCONNECT: MCPConnectionState.DISCONNECTED,
        MCPConnectionEvent.FAIL: MCPConnectionState.ERROR,
    }


class ErrorState(MCPStateHandler):
    """Последняя попытка подключения или обращения закончилась ошибкой."""

    state = MCPConnectionState.ERROR
    transitions = {
        MCPConnectionEvent.CONNECT: MCPConnectionState.CONNECTING,
        MCPConnectionEvent.DISCONNECT: MCPConnectionState.DISCONNECTED,
    }


#: Обработчик на каждое состояние (паттерн State: состояние — объект с поведением).
HANDLERS: dict[MCPConnectionState, MCPStateHandler] = {
    cls.state: cls()
    for cls in (DisconnectedState, ConnectingState, ConnectedState, ErrorState)
}

#: Граф допуска: состояние → {событие: новое состояние} (для UI, лога и тестов).
ALLOWED_TRANSITIONS: dict[MCPConnectionState, dict[MCPConnectionEvent, MCPConnectionState]] = {
    state: dict(handler.transitions) for state, handler in HANDLERS.items()
}


def allowed_events(state: MCPConnectionState) -> tuple[MCPConnectionEvent, ...]:
    """События, допустимые в состоянии (в порядке объявления ``MCPConnectionEvent``)."""
    transitions = ALLOWED_TRANSITIONS.get(state, {})
    return tuple(event for event in MCPConnectionEvent if event in transitions)


class MCPConnectionFSM:
    """Стейт-машина подключения: хранит состояние и делегирует события ему."""

    def __init__(self, state: MCPConnectionState = MCPConnectionState.DISCONNECTED):
        self._state = state

    @property
    def state(self) -> MCPConnectionState:
        """Текущее состояние подключения."""
        return self._state

    def handle(self, event: MCPConnectionEvent) -> MCPConnectionState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = HANDLERS[self._state].handle(event)
        return self._state

    def can(self, event: MCPConnectionEvent) -> bool:
        """Допустимо ли событие в текущем состоянии (проверка до вызова)."""
        return event in ALLOWED_TRANSITIONS[self._state]

    def allowed_events(self) -> tuple[MCPConnectionEvent, ...]:
        """События, допустимые в текущем состоянии."""
        return allowed_events(self._state)

    def reset(self) -> None:
        """Возвращает машину в исходное состояние (без событий; для тестов и close)."""
        self._state = MCPConnectionState.DISCONNECTED
