"""Реестр MCP-подключения дня 16: одно активное соединение на процесс.

Роутеры и Streamlit работают не с клиентом напрямую, а с реестром: он держит
текущее подключение (``MCPClient``), при новом ``/mcp/connect`` закрывает
прежнее и открывает новое, отдаёт статус и список инструментов. Так у процесса
ровно один MCP-сервер, а сервер-stdio не плодит дочерний процесс на каждый
запрос списка: ``tools/list`` берётся из открытой сессии (с кэшем до
``refresh=True``).

Отдельного хранилища у реестра нет: подключение живёт в памяти процесса и
переживает запросы API, но не рестарт (это соединение с внешним сервером, а не
данные домена).

Тесты подменяют фабрику клиента (``client_factory``) — реестр тогда работает
на фейке и не поднимает настоящий MCP-сервер.
"""
from __future__ import annotations

from typing import Callable

from shared.logging_utils import get_logger

from ..domain.mcp_target import MCPTransport
from ..domain.mcp_tools import MCPToolInfo
from .mcp_client import MCPClient, MCPNotConnectedError

logger = get_logger(__name__)


class MCPRegistry:
    """Держит текущее MCP-подключение процесса и отвечает за его смену и закрытие."""

    def __init__(self, client_factory: Callable[..., MCPClient] = MCPClient):
        self._client_factory = client_factory
        self._client: MCPClient | None = None

    @property
    def client(self) -> MCPClient | None:
        """Текущий клиент (None, если подключение ещё не пытались открыть)."""
        return self._client

    def connect(self, target: str, transport: MCPTransport | str = MCPTransport.AUTO) -> MCPClient:
        """Открывает новое подключение, закрывая прежнее (ошибка — ``MCPClient`` в ERROR).

        Исключение пробрасывается наружу: роутер переводит его в 400 (не разобрана
        цель) или 502 (сервер недоступен). Клиент при этом остаётся в реестре —
        ``GET /mcp/status`` показывает состояние ``error`` и текст причины, а не
        «нет подключения вообще».
        """
        self._drop()
        client = self._client_factory(target, transport=transport)
        self._client = client
        client.connect()
        return client

    def disconnect(self) -> None:
        """Закрывает текущее подключение (если его нет — безопасный no-op)."""
        self._drop()

    def tools(self, *, refresh: bool = False) -> list[MCPToolInfo]:
        """Список инструментов подключённого сервера (без соединения — исключение)."""
        if self._client is None:
            raise MCPNotConnectedError(
                "Подключение к MCP-серверу не установлено: сначала POST /mcp/connect"
            )
        return self._client.list_tools(refresh=refresh)

    def status(self) -> dict:
        """Состояние подключения для ``GET /mcp/status`` и ответов connect/disconnect."""
        client = self._client
        if client is None:
            return {
                "connected": False,
                "state": "disconnected",
                "target": None,
                "transport": None,
                "transport_label": None,
                "server_name": "",
                "server_version": "",
                "protocol": "",
                "tool_count": 0,
                "error": None,
                "allowed_events": ["connect"],
            }
        server = client.server_info
        return {
            "connected": client.connected,
            "state": client.state.value,
            "target": client.target.label(),
            "transport": client.target.transport.value,
            "transport_label": client.target.transport.label,
            "server_name": server.get("name", ""),
            "server_version": server.get("version", ""),
            "protocol": server.get("protocol", ""),
            "tool_count": len(client.tools),
            "error": client.last_error,
            "allowed_events": [event.value for event in client.allowed_events()],
        }

    def close(self) -> None:
        """Закрывает MCP-подключение при остановке приложения (lifespan)."""
        self._drop()

    def _drop(self) -> None:
        """Закрывает и забывает текущий клиент (общий шаг disconnect/close/connect)."""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001 — закрытие не должно ломать запрос
            logger.error("MCP: не удалось закрыть прошлое соединение: %s", exc)


_registry: MCPRegistry | None = None


def get_mcp_registry() -> MCPRegistry:
    """Единственный реестр MCP процесса (ленивый singleton)."""
    global _registry
    if _registry is None:
        _registry = MCPRegistry()
    return _registry
