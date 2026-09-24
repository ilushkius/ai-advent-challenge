"""Тесты раннера вызова MCP-инструмента (день 17).

Раннер — единственное место, где правила допуска встречаются с реестром, поэтому
здесь проверяются все четыре исхода: успех, ошибка инструмента, сбой связи и отказ
правил (нет соединения, неизвестный инструмент, плохие аргументы). Плюс главное
поведение дня: по реплике с ключевыми словами инструмент вызывается, по реплике без
них — нет, и клиент при этом не трогают вовсе.
"""
import pytest

from backend.domain.mcp_tool_call import (
    REASON_BAD_ARGUMENTS,
    REASON_NOT_CONNECTED,
    REASON_TOOL_ERROR,
    REASON_TRANSPORT,
    REASON_UNKNOWN_TOOL,
    MCPToolCallState,
)
from backend.services.mcp_registry import MCPRegistry
from backend.services.mcp_tool_runner import MCPToolRunner

from mcp_fakes import FAKE_TOOL_CATALOG, make_mcp_factory

USER = {"id": 1, "name": "Leanne Graham", "city": "Gwenborough"}


def _runner(factory) -> MCPToolRunner:
    """Раннер на реестре с фейковой фабрикой (настоящий сервер не поднимается)."""
    return MCPToolRunner(MCPRegistry(client_factory=factory))


@pytest.fixture
def factory():
    """Фабрика клиентов с каталогом своего сервера дня."""
    return make_mcp_factory(tools=FAKE_TOOL_CATALOG, call_result=USER)


def test_successful_call_reports_structured_result(factory):
    """Успешный вызов: состояние ``done``, структура, длительность и аргументы."""
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call("get_user", {"user_id": 1})
    assert outcome.state is MCPToolCallState.DONE
    assert outcome.accepted is True and outcome.called is True
    assert outcome.result.structured == USER
    assert outcome.arguments == {"user_id": 1}
    assert outcome.reason_code is None and outcome.error is None
    assert outcome.duration_ms >= 0
    assert factory.created[0].call_calls == [{"tool": "get_user",
                                             "arguments": {"user_id": 1}}]


def test_tool_error_is_not_a_transport_failure():
    """Ошибка инструмента приходит исходом ``failed`` с кодом ``tool_error``."""
    factory = make_mcp_factory(tools=FAKE_TOOL_CATALOG, call_error="нет такого id")
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call("get_user", {"user_id": 999})
    assert outcome.state is MCPToolCallState.FAILED
    assert outcome.reason_code == REASON_TOOL_ERROR
    assert outcome.error == "нет такого id"
    assert outcome.is_error is True and outcome.called is True


def test_transport_failure_has_its_own_code():
    """Обрыв связи — ``failed`` с кодом ``transport`` и текстом ошибки соединения."""
    factory = make_mcp_factory(tools=FAKE_TOOL_CATALOG, call_fail="сервер оборвался")
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call("get_user", {"user_id": 1})
    assert outcome.state is MCPToolCallState.FAILED
    assert outcome.reason_code == REASON_TRANSPORT
    assert "сервер оборвался" in outcome.error
    assert outcome.is_error is False


def test_call_without_connection_is_rejected():
    """Без соединения вызов отклонён, и инструмент не вызывается вовсе."""
    factory = make_mcp_factory(tools=FAKE_TOOL_CATALOG)
    runner = _runner(factory)

    outcome = runner.call("get_user", {"user_id": 1})
    assert outcome.state is MCPToolCallState.REJECTED
    assert outcome.reason_code == REASON_NOT_CONNECTED
    assert outcome.accepted is False and outcome.called is False
    assert outcome.connected is False
    assert factory.created == []


def test_unknown_tool_is_rejected_with_catalog_list(factory):
    """Неизвестный инструмент: отказ с перечнем доступных имён."""
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call("no_such_tool", {})
    assert outcome.state is MCPToolCallState.REJECTED
    assert outcome.reason_code == REASON_UNKNOWN_TOOL
    assert "get_user" in outcome.error and "no_such_tool" in outcome.error
    assert factory.created[0].call_calls == []


def test_bad_arguments_are_rejected_by_schema(factory):
    """Аргументы проверяются по ``input_schema``: строка вместо числа — отказ."""
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call("get_user", {"user_id": "один"})
    assert outcome.state is MCPToolCallState.REJECTED
    assert outcome.reason_code == REASON_BAD_ARGUMENTS
    assert "integer" in outcome.error
    assert factory.created[0].call_calls == []


def test_call_for_prompt_calls_tool_on_keywords(factory):
    """Реплика про пользователя сама приводит к вызову ``get_user`` с номером."""
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call_for_prompt("Найди информацию о пользователе с ID 1")
    assert outcome.detected is True and outcome.called is True
    assert outcome.tool == "get_user" and outcome.arguments == {"user_id": 1}
    assert outcome.result.structured == USER


def test_call_for_prompt_does_nothing_without_keywords(factory):
    """Реплика без ключевых слов: инструмент не вызывается, клиент не трогается."""
    runner = _runner(factory)
    runner.registry.connect("uvx mcp-server-fetch")

    outcome = runner.call_for_prompt("Сколько будет 2+2?")
    assert outcome.detected is False
    assert outcome.state is MCPToolCallState.IDLE
    assert outcome.connected is True
    assert factory.created[0].call_calls == []


def test_call_for_prompt_without_connection_stays_idle():
    """Без соединения каталога нет: реплика не превращается в вызов."""
    runner = _runner(make_mcp_factory(tools=FAKE_TOOL_CATALOG))

    outcome = runner.call_for_prompt("Найди информацию о пользователе с ID 1")
    assert outcome.detected is False and outcome.connected is False
    assert outcome.state is MCPToolCallState.IDLE


def test_status_and_catalog_delegate_to_registry(factory):
    """Раннер не дублирует реестр: статус и каталог берутся у него."""
    runner = _runner(factory)
    assert runner.connected() is False
    assert runner.available_tools() == []

    runner.registry.connect("uvx mcp-server-fetch")
    assert runner.connected() is True
    assert [tool.name for tool in runner.available_tools()] == [
        tool.name for tool in FAKE_TOOL_CATALOG
    ]
    assert runner.status()["connected"] is True
