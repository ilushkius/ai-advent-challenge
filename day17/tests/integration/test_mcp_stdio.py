"""Интеграционный тест MCP-клиента на настоящем stdio-сервере (без сети).

Сервер — ``tests/mcp_echo_server.py`` (``mcp.server.mcpserver.MCPServer`` с двумя
инструментами), запускается тем же интерпретатором, что и тесты: проверяется
весь путь целиком — выбор транспорта, запуск дочернего процесса, ``initialize``,
``tools/list``, кэш списка, закрытие соединения и FSM подключения. Ни сети, ни
установки пакетов тесту не нужно.

Тест медленнее юнит-тестов (поднимается процесс на каждый клиент), поэтому
клиент в фикстуре один на тест и всегда закрывается в ``finally``.
"""
import sys
from pathlib import Path

import pytest

from backend.domain.mcp_connection_fsm import MCPConnectionEvent, MCPConnectionState
from backend.domain.mcp_target import MCPTransport
from backend.services.mcp_client import MCPClient, MCPNotConnectedError

SERVER = Path(__file__).resolve().parents[1] / "mcp_echo_server.py"


@pytest.fixture
def client():
    """Клиент на тестовом stdio-сервере: цель — команда запуска файла."""
    instance = MCPClient(f'{sys.executable} "{SERVER}"', timeout=30.0)
    yield instance
    instance.close()


def test_lists_tools_from_real_stdio_server(client):
    """Соединение устанавливается, а список инструментов приходит непустым."""
    client.connect()
    assert client.state is MCPConnectionState.CONNECTED
    assert client.target.transport is MCPTransport.STDIO
    assert client.server_info["name"] == "day17-echo-server"

    tools = client.list_tools()
    assert {tool.name for tool in tools} == {"add", "echo"}
    echo = next(tool for tool in tools if tool.name == "echo")
    assert echo.description
    assert "text" in echo.input_schema.get("properties", {})
    assert echo.input_schema.get("required") == ["text"]


def test_repeated_and_refreshed_lists_agree(client):
    """Кэш и повторный запрос к серверу дают тот же каталог инструментов."""
    client.connect()
    first = client.list_tools()
    assert client.list_tools() == first            # из кэша
    assert client.list_tools(refresh=True) == first  # реальный повторный tools/list
    assert client.tools == tuple(first)


def test_tools_require_connection(client):
    """Без соединения список инструментов недоступен (явная ошибка, не пустота)."""
    with pytest.raises(MCPNotConnectedError):
        client.list_tools()


def test_disconnect_closes_and_allows_reconnect(client):
    """После отключения состояние сбрасывается, повторное подключение работает."""
    client.connect()
    assert client.list_tools()
    client.disconnect()
    assert client.state is MCPConnectionState.DISCONNECTED
    assert client.tools == ()
    with pytest.raises(MCPNotConnectedError):
        client.list_tools()

    client.connect()
    assert client.state is MCPConnectionState.CONNECTED
    assert client.list_tools()
    assert MCPConnectionEvent.CONNECT not in client.allowed_events()


def test_context_manager_closes_connection():
    """Контекстный менеджер закрывает соединение и останавливает служебный цикл."""
    with MCPClient(f'{sys.executable} "{SERVER}"', timeout=30.0) as client:
        assert client.list_tools()
    assert client.state is MCPConnectionState.DISCONNECTED
