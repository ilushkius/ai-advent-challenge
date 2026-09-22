"""Вызов MCP-инструмента: правила допуска и жизненный цикл (день 17).

Два независимых правила в одном модуле — так их читают рядом:

1. **Допуск вызова** (``admission_reason``): можно ли вообще звать инструмент с
   такими аргументами. Порядок проверок — от «нет соединения» к «не тот тип
   аргумента»: чем раньше причина, тем дешевле она для пользователя.
2. **Жизненный цикл** (``MCPToolCallState``/``MCPToolCallFSM``): состояния и
   события одного вызова — ``Enum`` плюс паттерн State, как в
   ``mcp_connection_fsm.py``. Неизвестное событие в состоянии — явная ошибка
   ``UnknownMCPToolCallEvent``, а не «тихое» зависание.

Граф переходов однозначен:

===================================  ==========================================
состояние                            событие → новое состояние
===================================  ==========================================
``IDLE``                             ``PLAN`` → ``PLANNED``
``PLANNED``                          ``INVOKE`` → ``INVOKED``;
                                     ``REJECT`` → ``REJECTED`` (правила не пустили)
``INVOKED``                          ``SUCCEED`` → ``DONE``;
                                     ``FAIL`` → ``FAILED`` (сбой связи или инструмента)
``DONE`` / ``FAILED`` / ``REJECTED`` ``PLAN`` → ``PLANNED`` (следующий вызов)
===================================  ==========================================

Отказ — это данные, а не исключение: причина приходит кодом
(``REASON_NOT_CONNECTED`` и т. д.), тем же кодом пользуются API (HTTP 400/409) и
UI (подпись плашки). Модуль не импортирует MCP SDK, HTTP и Streamlit: правила
тестируются без сети (tests/unit/test_mcp_tool_call.py).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Sequence

from .mcp_tools import MCPToolInfo, MCPToolResult

#: Коды причин отказа — контракт API (400/409) и подписи интерфейса.
REASON_NOT_CONNECTED = "not_connected"
REASON_UNKNOWN_TOOL = "unknown_tool"
REASON_BAD_ARGUMENTS = "bad_arguments"
REASON_TRANSPORT = "transport"
REASON_TOOL_ERROR = "tool_error"

#: Подсказка «что делать», когда аргументов не хватает.
ARGUMENTS_HINT = (
    "Укажите число в запросе (например, «пользователь 3») "
    "или передайте аргументы через POST /mcp/call."
)

#: Тип JSON Schema → тип Python. ``bool`` проверяется отдельно: в Python он
#: подкласс ``int``, поэтому без исключения ``True`` сошёл бы за ``integer``.
JSON_TYPES: dict[str, Any] = {
    "integer": int,
    "number": (int, float),
    "string": str,
    "boolean": bool,
    "array": list,
    "object": dict,
}

#: Подписи типов для сообщений об ошибке (имя типа Python → имя типа JSON Schema).
TYPE_LABELS = {
    "bool": "boolean",
    "int": "integer",
    "float": "number",
    "str": "string",
    "list": "array",
    "dict": "object",
    "NoneType": "null",
}


class MCPToolCallState(enum.Enum):
    """Состояние одного вызова инструмента."""

    IDLE = "idle"
    PLANNED = "planned"
    INVOKED = "invoked"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"


class MCPToolCallEvent(enum.Enum):
    """Событие, которое двигает вызов по графу."""

    PLAN = "plan"
    INVOKE = "invoke"
    SUCCEED = "succeed"
    FAIL = "fail"
    REJECT = "reject"


class UnknownMCPToolCallEvent(Exception):
    """Событие, недопустимое в текущем состоянии вызова."""

    def __init__(self, state: MCPToolCallState, event: MCPToolCallEvent):
        self.state = state
        self.event = event
        allowed = ", ".join(item.value for item in allowed_events(state)) or "—"
        super().__init__(
            f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
            f"допустимы: {allowed}"
        )


class MCPCallStateHandler:
    """Общий интерфейс состояния: одно событие → ровно одно новое состояние."""

    state: ClassVar[MCPToolCallState]
    transitions: ClassVar[dict[MCPToolCallEvent, MCPToolCallState]]

    def handle(self, event: MCPToolCallEvent) -> MCPToolCallState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownMCPToolCallEvent(self.state, event) from None


class IdleState(MCPCallStateHandler):
    """Вызов не начинался: реплика ещё не разобрана."""

    state = MCPToolCallState.IDLE
    transitions = {MCPToolCallEvent.PLAN: MCPToolCallState.PLANNED}


class PlannedState(MCPCallStateHandler):
    """Инструмент выбран: правила допуска решают — вызывать или отклонить."""

    state = MCPToolCallState.PLANNED
    transitions = {
        MCPToolCallEvent.INVOKE: MCPToolCallState.INVOKED,
        MCPToolCallEvent.REJECT: MCPToolCallState.REJECTED,
    }


class InvokedState(MCPCallStateHandler):
    """Запрос ушёл на сервер: ждём результат или сбой."""

    state = MCPToolCallState.INVOKED
    transitions = {
        MCPToolCallEvent.SUCCEED: MCPToolCallState.DONE,
        MCPToolCallEvent.FAIL: MCPToolCallState.FAILED,
    }


class DoneState(MCPCallStateHandler):
    """Инструмент ответил успешно (``is_error`` ложно)."""

    state = MCPToolCallState.DONE
    transitions = {MCPToolCallEvent.PLAN: MCPToolCallState.PLANNED}


class FailedState(MCPCallStateHandler):
    """Вызов провалился: сбой связи (``transport``) или ошибка инструмента."""

    state = MCPToolCallState.FAILED
    transitions = {MCPToolCallEvent.PLAN: MCPToolCallState.PLANNED}


class RejectedState(MCPCallStateHandler):
    """Вызов отклонён правилами допуска — инструмент не вызывался."""

    state = MCPToolCallState.REJECTED
    transitions = {MCPToolCallEvent.PLAN: MCPToolCallState.PLANNED}


#: Обработчик на каждое состояние (паттерн State: состояние — объект с поведением).
HANDLERS: dict[MCPToolCallState, MCPCallStateHandler] = {
    cls.state: cls()
    for cls in (IdleState, PlannedState, InvokedState, DoneState, FailedState,
                RejectedState)
}

#: Граф допуска: состояние → {событие: новое состояние} (для UI, лога и тестов).
ALLOWED_TRANSITIONS: dict[MCPToolCallState, dict[MCPToolCallEvent, MCPToolCallState]] = {
    state: dict(handler.transitions) for state, handler in HANDLERS.items()
}


def allowed_events(state: MCPToolCallState) -> tuple[MCPToolCallEvent, ...]:
    """События, допустимые в состоянии (в порядке объявления ``MCPToolCallEvent``)."""
    transitions = ALLOWED_TRANSITIONS.get(state, {})
    return tuple(event for event in MCPToolCallEvent if event in transitions)


class MCPToolCallFSM:
    """Стейт-машина одного вызова: хранит состояние и делегирует события ему."""

    def __init__(self, state: MCPToolCallState = MCPToolCallState.IDLE):
        self._state = state

    @property
    def state(self) -> MCPToolCallState:
        """Текущее состояние вызова."""
        return self._state

    def handle(self, event: MCPToolCallEvent) -> MCPToolCallState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = HANDLERS[self._state].handle(event)
        return self._state

    def can(self, event: MCPToolCallEvent) -> bool:
        """Допустимо ли событие в текущем состоянии (проверка до вызова)."""
        return event in ALLOWED_TRANSITIONS[self._state]

    def allowed_events(self) -> tuple[MCPToolCallEvent, ...]:
        """События, допустимые в текущем состоянии."""
        return allowed_events(self._state)

    def reset(self) -> None:
        """Возвращает машину в исходное состояние (без событий; для тестов)."""
        self._state = MCPToolCallState.IDLE


# ---------- правила допуска ----------
def find_tool(catalog: Sequence[MCPToolInfo], tool_name: str) -> Optional[MCPToolInfo]:
    """Инструмент каталога по имени (None — такого инструмента нет)."""
    wanted = (tool_name or "").strip()
    for tool in catalog:
        if tool.name == wanted:
            return tool
    return None


def admission_reason(
    tool_name: str,
    arguments: dict[str, Any] | None,
    catalog: Sequence[MCPToolInfo],
    connected: bool,
) -> tuple[Optional[str], Optional[str]]:
    """Можно ли вызвать инструмент: ``(текст отказа, код причины)``.

    ``(None, None)`` — вызов допустим. Проверки идут от дешёвой и очевидной
    причины к тонкой: нет соединения → инструмента нет в каталоге → нет
    обязательного аргумента → лишний аргумент → тип не тот. Порядок важен: при
    отсутствии соединения схема недостоверна (каталога нет), поэтому о ней не
    сообщают. Схема без ``properties``/``required`` ничего не запрещает —
    сервер вправе не описывать аргументы.
    """
    args = dict(arguments or {})
    if not connected:
        return (
            "Вызов инструмента невозможен: соединение с MCP-сервером не установлено. "
            "Подключитесь через POST /mcp/connect.",
            REASON_NOT_CONNECTED,
        )
    tool = find_tool(catalog, tool_name)
    if tool is None:
        names = ", ".join(item.name for item in catalog) or "нет"
        return (
            f"Инструмент «{tool_name}» не найден в каталоге сервера. Доступны: {names}",
            REASON_UNKNOWN_TOOL,
        )
    return _argument_reason(tool, args)


def _argument_reason(tool: MCPToolInfo,
                     args: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Проверка аргументов по ``input_schema`` инструмента."""
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else None
    required = schema.get("required")
    required = [item for item in required if isinstance(item, str)] \
        if isinstance(required, list) else []

    for name in required:
        if name not in args:
            return (
                f"Не указан обязательный аргумент «{name}» инструмента "
                f"«{tool.name}». {ARGUMENTS_HINT}",
                REASON_BAD_ARGUMENTS,
            )
    if properties is None:
        return None, None
    for name in args:
        if name not in properties:
            known = ", ".join(sorted(properties)) or "нет"
            return (
                f"Инструмент «{tool.name}» не принимает аргумент «{name}». "
                f"Доступны: {known}",
                REASON_BAD_ARGUMENTS,
            )
    for name, value in args.items():
        expected = (properties.get(name) or {}).get("type")
        expected_types = _expected_types(expected)
        if not expected_types or _matches(value, expected_types):
            continue
        labels = " | ".join(expected_types)
        return (
            f"Аргумент «{name}» инструмента «{tool.name}» должен быть {labels}, "
            f"получено {_type_label(value)}",
            REASON_BAD_ARGUMENTS,
        )
    return None, None


def _expected_types(expected: Any) -> tuple[str, ...]:
    """Типы из ``type`` схемы: строка, список или ничего."""
    if isinstance(expected, str):
        return (expected,)
    if isinstance(expected, list):
        return tuple(item for item in expected if isinstance(item, str))
    return ()


def _matches(value: Any, expected_types: tuple[str, ...]) -> bool:
    """Подходит ли значение хотя бы одному из объявленных типов схемы."""
    for name in expected_types:
        python_type = JSON_TYPES.get(name)
        if python_type is None:
            continue
        if isinstance(value, bool) and name in ("integer", "number"):
            continue
        if isinstance(value, python_type):
            return True
    return False


def _type_label(value: Any) -> str:
    """Имя фактического типа значения для сообщения (``1`` → ``integer``)."""
    name = type(value).__name__
    return TYPE_LABELS.get(name, name)


# ---------- исход вызова ----------
@dataclass(frozen=True, slots=True)
class MCPToolCallOutcome:
    """Что произошло с вызовом: состояние, причина отказа и результат.

    Одна и та же структура описывает четыре разных случая, и поле ``state``
    говорит, какой именно:

    - ``IDLE`` — вызов не планировался (``detected=False``);
    - ``REJECTED`` — правила допуска не пустили (``reason_code``, ``error``);
    - ``FAILED`` — сервер не ответил или инструмент вернул ошибку;
    - ``DONE`` — результат есть, ``result.structured`` ушёл в промпт.
    """

    state: MCPToolCallState = MCPToolCallState.IDLE
    detected: bool = False
    connected: bool = False
    accepted: bool = False
    tool: Optional[str] = None
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Optional[MCPToolResult] = None
    reason_code: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0

    @property
    def called(self) -> bool:
        """Ушёл ли запрос на сервер (даже если тот ответил ошибкой)."""
        return self.state in (MCPToolCallState.INVOKED, MCPToolCallState.DONE,
                              MCPToolCallState.FAILED)

    @property
    def is_error(self) -> bool:
        """Вернул ли инструмент ошибку (для ``FAILED`` по транспорту — нет).

        Сбой связи (``reason_code="transport"``) и ошибка инструмента
        (``"tool_error"``) — разные вещи: первый означает, что ответа не было,
        второй — что сервер ответил «не получилось», и это данные ответа.
        """
        return bool(self.result is not None and self.result.is_error)

    def to_dict(self) -> dict[str, Any]:
        """Плоский словарь отчёта: он же — поле ``mcp`` ответа API."""
        return {
            "state": self.state.value,
            "detected": self.detected,
            "connected": self.connected,
            "called": self.called,
            "accepted": self.accepted,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "result": self.result.to_dict() if self.result is not None else None,
            "is_error": self.is_error,
            "reason_code": self.reason_code,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }
