"""Тесты вызова MCP-инструмента (день 17): граф состояний и правила допуска.

Два независимых предмета в одном файле, потому что они про одно и то же действие:
таблица переходов ``MCPToolCallState``/``MCPToolCallEvent`` (паттерн State, как в
``mcp_connection_fsm``) и ``admission_reason`` — можно ли звать инструмент с
такими аргументами. Негативные пары проверяются обязательно: недопустимое событие
— явная ошибка ``UnknownMCPToolCallEvent``, а не «тихое» зависание.
"""
import pytest

from backend.domain.mcp_tool_call import (
    ALLOWED_TRANSITIONS,
    ARGUMENTS_HINT,
    HANDLERS,
    REASON_BAD_ARGUMENTS,
    REASON_NOT_CONNECTED,
    REASON_UNKNOWN_TOOL,
    MCPToolCallEvent,
    MCPToolCallFSM,
    MCPToolCallOutcome,
    MCPToolCallState,
    UnknownMCPToolCallEvent,
    admission_reason,
    allowed_events,
    find_tool,
)
from backend.domain.mcp_tools import MCPToolInfo, MCPToolResult

USER_TOOL = MCPToolInfo(
    name="get_user",
    description="Данные пользователя",
    input_schema={
        "type": "object",
        "properties": {"user_id": {"type": "integer"}},
        "required": ["user_id"],
    },
    output_schema={"type": "object"},
)
POSTS_TOOL = MCPToolInfo(
    name="list_user_posts",
    description="Посты пользователя",
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "integer"},
            "limit": {"type": "integer"},
            "tag": {"type": "string"},
            "verbose": {"type": "boolean"},
            "ids": {"type": "array"},
        },
        "required": ["user_id"],
    },
)
CATALOG = (USER_TOOL, POSTS_TOOL)

#: Все допустимые переходы графа: состояние, событие → новое состояние.
TRANSITIONS = (
    (MCPToolCallState.IDLE, MCPToolCallEvent.PLAN, MCPToolCallState.PLANNED),
    (MCPToolCallState.PLANNED, MCPToolCallEvent.INVOKE, MCPToolCallState.INVOKED),
    (MCPToolCallState.PLANNED, MCPToolCallEvent.REJECT, MCPToolCallState.REJECTED),
    (MCPToolCallState.INVOKED, MCPToolCallEvent.SUCCEED, MCPToolCallState.DONE),
    (MCPToolCallState.INVOKED, MCPToolCallEvent.FAIL, MCPToolCallState.FAILED),
    (MCPToolCallState.DONE, MCPToolCallEvent.PLAN, MCPToolCallState.PLANNED),
    (MCPToolCallState.FAILED, MCPToolCallEvent.PLAN, MCPToolCallState.PLANNED),
    (MCPToolCallState.REJECTED, MCPToolCallEvent.PLAN, MCPToolCallState.PLANNED),
)

#: Недопустимые пары: событие либо не тот шаг, либо уже пройдено.
FORBIDDEN = (
    (MCPToolCallState.IDLE, MCPToolCallEvent.INVOKE),
    (MCPToolCallState.IDLE, MCPToolCallEvent.SUCCEED),
    (MCPToolCallState.IDLE, MCPToolCallEvent.REJECT),
    (MCPToolCallState.PLANNED, MCPToolCallEvent.PLAN),
    (MCPToolCallState.PLANNED, MCPToolCallEvent.SUCCEED),
    (MCPToolCallState.INVOKED, MCPToolCallEvent.INVOKE),
    (MCPToolCallState.INVOKED, MCPToolCallEvent.REJECT),
    (MCPToolCallState.DONE, MCPToolCallEvent.INVOKE),
    (MCPToolCallState.FAILED, MCPToolCallEvent.FAIL),
    (MCPToolCallState.REJECTED, MCPToolCallEvent.REJECT),
)


@pytest.mark.parametrize("state,event,expected", TRANSITIONS)
def test_allowed_transitions(state, event, expected):
    """Каждая допустимая пара переводит машину ровно в одно объявленное состояние."""
    fsm = MCPToolCallFSM(state)
    assert fsm.handle(event) is expected
    assert fsm.state is expected


@pytest.mark.parametrize("state,event", FORBIDDEN)
def test_unknown_event_is_explicit_error(state, event):
    """Недопустимое событие — явная ошибка, состояние не меняется."""
    fsm = MCPToolCallFSM(state)
    with pytest.raises(UnknownMCPToolCallEvent) as exc:
        fsm.handle(event)
    assert fsm.state is state
    assert event.value in str(exc.value)


def test_transition_table_matches_handlers():
    """Таблица допуска — это ровно то, что объявлено в классах состояний."""
    assert set(ALLOWED_TRANSITIONS) == set(MCPToolCallState)
    for state, handler in HANDLERS.items():
        assert ALLOWED_TRANSITIONS[state] == dict(handler.transitions)
        assert handler.state is state


def test_can_and_allowed_events_follow_the_graph():
    """``can``/``allowed_events`` отвечают по графу, а не «на глаз»."""
    fsm = MCPToolCallFSM(MCPToolCallState.PLANNED)
    assert fsm.can(MCPToolCallEvent.INVOKE) and fsm.can(MCPToolCallEvent.REJECT)
    assert not fsm.can(MCPToolCallEvent.PLAN)
    assert fsm.allowed_events() == (MCPToolCallEvent.INVOKE, MCPToolCallEvent.REJECT)
    assert allowed_events(MCPToolCallState.IDLE) == (MCPToolCallEvent.PLAN,)


def test_reset_returns_to_idle():
    """``reset`` возвращает машину в исходное состояние (для тестов и повторного хода)."""
    fsm = MCPToolCallFSM()
    fsm.handle(MCPToolCallEvent.PLAN)
    fsm.handle(MCPToolCallEvent.INVOKE)
    fsm.reset()
    assert fsm.state is MCPToolCallState.IDLE


def test_find_tool_by_name():
    """Инструмент ищется по имени; чужая цель — None, а не исключение."""
    assert find_tool(CATALOG, "get_post") is None
    assert find_tool(CATALOG, " get_user ") is USER_TOOL
    assert find_tool(CATALOG, "") is None


def test_admission_without_connection_says_what_to_do():
    """Без соединения вызов невозможен: причина называет код и следующий шаг."""
    reason, code = admission_reason("get_user", {"user_id": 1}, CATALOG, False)
    assert code == REASON_NOT_CONNECTED
    assert "не установлено" in reason and "POST /mcp/connect" in reason


def test_admission_rejects_unknown_tool_with_catalog():
    """Инструмента нет в каталоге: текст перечисляет доступные имена."""
    reason, code = admission_reason("no_such", {}, CATALOG, True)
    assert code == REASON_UNKNOWN_TOOL
    assert "no_such" in reason and "get_user" in reason and "list_user_posts" in reason


def test_admission_unknown_tool_with_empty_catalog():
    """Пустой каталог не оставляет список пустым в тексте (иначе «Доступны: »)."""
    reason, code = admission_reason("get_user", {}, (), True)
    assert code == REASON_UNKNOWN_TOOL
    assert "нет" in reason


def test_admission_requires_mandatory_argument():
    """Обязательный аргумент не указан: причина называет его и подсказывает формат."""
    reason, code = admission_reason("get_user", {}, CATALOG, True)
    assert code == REASON_BAD_ARGUMENTS
    assert "user_id" in reason and ARGUMENTS_HINT in reason


def test_admission_rejects_unknown_argument():
    """Лишний аргумент — отказ: сервер такого параметра не знает."""
    reason, code = admission_reason("get_user", {"user_id": 1, "city": "X"}, CATALOG, True)
    assert code == REASON_BAD_ARGUMENTS
    assert "city" in reason and "user_id" in reason


@pytest.mark.parametrize("value", ["1", "1.5", None, [1], {"id": 1}])
def test_admission_rejects_wrong_types(value):
    """Тип аргумента проверяется по схеме: ``integer`` не принимает строку и список."""
    reason, code = admission_reason("get_user", {"user_id": value}, CATALOG, True)
    assert code == REASON_BAD_ARGUMENTS
    assert "должен быть integer" in reason


def test_admission_rejects_bool_as_integer():
    """``True`` — это ``boolean``, а не ``integer`` (в Python bool — подкласс int)."""
    reason, code = admission_reason("get_user", {"user_id": True}, CATALOG, True)
    assert code == REASON_BAD_ARGUMENTS
    assert "получено boolean" in reason


def test_admission_accepts_declared_types():
    """Значения объявленных типов проходят: строки, флаги и списки — по схеме."""
    reason, code = admission_reason(
        "list_user_posts",
        {"user_id": 1, "limit": 5, "tag": "x", "verbose": True, "ids": [1, 2]},
        CATALOG, True,
    )
    assert (reason, code) == (None, None)


def test_admission_allows_unknown_schema():
    """Схема без ``properties``/``required`` ничего не запрещает."""
    tool = MCPToolInfo(name="echo")
    assert admission_reason("echo", {"whatever": 1}, (tool,), True) == (None, None)


@pytest.mark.parametrize("state,called", [
    (MCPToolCallState.IDLE, False),
    (MCPToolCallState.PLANNED, False),
    (MCPToolCallState.REJECTED, False),
    (MCPToolCallState.INVOKED, True),
    (MCPToolCallState.DONE, True),
    (MCPToolCallState.FAILED, True),
])
def test_outcome_reports_whether_request_left(state, called):
    """``called`` различает «инструмент не вызывался» и «запрос ушёл, ответ плохой»."""
    outcome = MCPToolCallOutcome(state=state, tool="get_user")
    assert outcome.to_dict()["called"] is called


def test_outcome_reports_tool_error_separately():
    """Ошибка инструмента и сбой связи различаются в словаре отчёта."""
    failed_tool = MCPToolCallOutcome(
        state=MCPToolCallState.FAILED, tool="get_user",
        result=MCPToolResult(tool="get_user", text="нет такого", is_error=True),
        reason_code="tool_error", error="нет такого",
    )
    failed_transport = MCPToolCallOutcome(
        state=MCPToolCallState.FAILED, tool="get_user",
        reason_code="transport", error="сервер не ответил",
    )
    assert failed_tool.to_dict()["is_error"] is True
    assert failed_transport.to_dict()["is_error"] is False
    assert failed_transport.to_dict()["result"] is None


def test_outcome_dict_has_contract_fields():
    """Словарь отчёта содержит все поля контракта (поле ``mcp`` ответа API)."""
    payload = MCPToolCallOutcome(
        state=MCPToolCallState.DONE, detected=True, connected=True, accepted=True,
        tool="get_user", arguments={"user_id": 1},
        result=MCPToolResult(tool="get_user", structured={"id": 1}, duration_ms=3),
        duration_ms=3,
    ).to_dict()
    assert set(payload) == {
        "state", "detected", "connected", "called", "accepted", "tool", "arguments",
        "result", "is_error", "reason_code", "error", "duration_ms",
    }
    assert payload["state"] == "done" and payload["arguments"] == {"user_id": 1}
    assert payload["result"]["structured"] == {"id": 1}
