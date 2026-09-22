"""Тесты реестра MCP-подключения (день 16): смена соединения, статус, закрытие.

Клиент подменён фейком (``support.make_mcp_factory``), а поведение настоящий
рейла: одно активное подключение на процесс, прежнее при ``connect`` закрывается,
``tools`` без соединения — ошибка, провалившаяся попытка остаётся видимой в
статусе (состояние ``error`` и текст причины), ``close`` закрывает клиент.
"""
import pytest

from backend.domain.mcp_target import MCPTransport
from backend.services.mcp_client import MCPConnectionError, MCPNotConnectedError
from backend.services.mcp_registry import MCPRegistry

from support import FAKE_MCP_SERVER, FAKE_MCP_TOOLS, make_mcp_factory


@pytest.fixture
def factory():
    """Фабрика фейковых MCP-клиентов с записью созданных экземпляров."""
    return make_mcp_factory()


@pytest.fixture
def registry(factory):
    """Реестр на фейковой фабрике (настоящий сервер не поднимается)."""
    return MCPRegistry(client_factory=factory)


def test_status_without_connection_describes_project_state(registry):
    """До подключения статус явно говорит «не подключено» и что делать дальше."""
    status = registry.status()
    assert status["connected"] is False
    assert status["state"] == "disconnected"
    assert status["target"] is None and status["tool_count"] == 0
    assert status["allowed_events"] == ["connect"]


def test_tools_without_connection_raises(registry):
    """Список инструментов без соединения — ошибка, а не пустой ответ."""
    with pytest.raises(MCPNotConnectedError):
        registry.tools()


def test_connect_fills_status_with_server_and_tools(registry, factory):
    """После подключения статус описывает сервер, транспорт и число инструментов."""
    registry.connect("uvx mcp-server-fetch")
    client = factory.created[0]
    status = registry.status()
    assert status["connected"] is True
    assert status["state"] == "connected"
    assert status["target"] == "uvx mcp-server-fetch"
    assert status["transport"] == MCPTransport.STDIO.value
    assert status["server_name"] == FAKE_MCP_SERVER["name"]
    assert status["protocol"] == FAKE_MCP_SERVER["protocol"]
    assert status["tool_count"] == 0          # список ещё не запрашивали
    assert set(status["allowed_events"]) == {"disconnect", "fail"}

    tools = registry.tools()
    assert [tool.name for tool in tools] == [tool.name for tool in FAKE_MCP_TOOLS]
    assert registry.status()["tool_count"] == len(FAKE_MCP_TOOLS)
    assert client.list_calls == 1


def test_reconnect_closes_previous_connection(registry, factory):
    """Новое подключение закрывает прежнее: два stdio-процесса не живут вместе."""
    registry.connect("uvx mcp-server-fetch")
    registry.connect("http://127.0.0.1:9000/mcp", MCPTransport.STREAMABLE_HTTP)
    first, second = factory.created
    assert first.closed is True
    assert second.closed is False
    status = registry.status()
    assert status["transport"] == MCPTransport.STREAMABLE_HTTP.value
    assert status["target"] == "http://127.0.0.1:9000/mcp"


def test_disconnect_closes_client_and_resets_status(registry, factory):
    """Отключение закрывает соединение; повторное — безопасный no-op."""
    registry.connect("uvx mcp-server-fetch")
    registry.disconnect()
    assert factory.created[0].closed is True
    assert registry.status()["state"] == "disconnected"
    registry.disconnect()  # повторный вызов ничего не ломает
    assert len(factory.created) == 1


def test_failed_connect_propagates_and_stays_visible(factory):
    """Неудачное подключение: ошибка наружу, состояние ``error`` в статусе."""
    registry = MCPRegistry(client_factory=make_mcp_factory(fail="Сервер недоступен"))
    with pytest.raises(MCPConnectionError) as exc:
        registry.connect("http://127.0.0.1:9/mcp", MCPTransport.STREAMABLE_HTTP)
    assert "Сервер недоступен" in str(exc.value)
    status = registry.status()
    assert status["connected"] is False
    assert status["state"] == "error"
    assert status["error"] == "Сервер недоступен"
    assert status["allowed_events"] == ["connect", "disconnect"]


def test_close_closes_current_client(registry, factory):
    """``close`` (остановка приложения) закрывает текущее соединение."""
    registry.connect("uvx mcp-server-fetch")
    registry.close()
    assert factory.created[0].closed is True
    assert registry.client is None
    assert registry.status()["connected"] is False
