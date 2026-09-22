"""Тесты ошибок подключения MCP-клиента (день 16): понятный текст вместо traceback.

Три сценария из задания дня проверяются офлайн: неверная команда запуска,
недоступный HTTP-адрес и разбор цели до подключения. Каждый обязан дать
``MCPConnectionError`` с человекочитаемым текстом (что делали, что случилось,
что проверить), перевести FSM в ``error`` и не оставить после себя соединения.
"""
import pytest

from backend.domain.mcp_connection_fsm import MCPConnectionState
from backend.domain.mcp_target import MCPTargetError, MCPTransport
from backend.services.mcp_client import (
    MCPClient,
    MCPConnectionError,
    MCPNotConnectedError,
)


def test_missing_command_reports_not_found():
    """Команды нет в PATH: текст называет команду и подсказывает про npx/uvx."""
    client = MCPClient("day17-no-such-mcp-command --serve", timeout=10.0)
    try:
        with pytest.raises(MCPConnectionError) as exc:
            client.connect()
        message = str(exc.value)
        assert "day17-no-such-mcp-command" in message
        assert "не найдена" in message
        assert client.state is MCPConnectionState.ERROR
        assert client.last_error == message
        with pytest.raises(MCPNotConnectedError):
            client.list_tools()
    finally:
        client.close()


def test_unreachable_http_endpoint_reports_url_hint():
    """HTTP-сервер не поднят: текст говорит про URL, а не про внутренности SDK."""
    client = MCPClient("http://127.0.0.1:9/mcp", transport=MCPTransport.STREAMABLE_HTTP,
                       timeout=5.0)
    try:
        with pytest.raises(MCPConnectionError) as exc:
            client.connect()
        message = str(exc.value)
        assert "127.0.0.1:9/mcp" in message
        assert "URL" in message
        assert client.state is MCPConnectionState.ERROR
    finally:
        client.close()


def test_unparsable_target_fails_before_connecting():
    """Неразобранная цель — ошибка разбора, состояние остаётся ``disconnected``."""
    with pytest.raises(MCPTargetError):
        MCPClient("")


def test_reconnect_after_error_is_allowed():
    """После ошибки клиент не «залипает»: повтор разрешён и снова даёт ошибку."""
    client = MCPClient("day17-no-such-mcp-command --serve", timeout=10.0)
    try:
        with pytest.raises(MCPConnectionError):
            client.connect()
        assert client.state is MCPConnectionState.ERROR
        assert {event.value for event in client.allowed_events()} == {"connect", "disconnect"}
        with pytest.raises(MCPConnectionError):
            client.connect()  # второй раз — снова понятная ошибка, а не зависание
        assert client.state is MCPConnectionState.ERROR
    finally:
        client.close()
