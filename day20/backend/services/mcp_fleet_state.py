"""Состояние одного сервера флота в памяти реестра (день 20).

Запись сервера — это конфигурация из ``mcp_servers.json`` плюс то, что реестр узнал о
нём в рантайме: соединение, прочитанный каталог инструментов и текст последней
ошибки. Вынесено из ``mcp_registry.py`` отдельным модулем, потому что реестр
подошёл к лимиту 400 строк, а состояние сервера — самостоятельная единица: его
читает API (``GET /mcp/servers``), по нему решается маршрутизация (есть ли у сервера
такой инструмент) и подстановка кэша (``tools_cache`` из файла).

Почему каталог может прийти из ФАЙЛА. Сервер — отдельный процесс: пока он не
поднялся, его ``tools/list`` неизвестен. Кэш из конфигурации закрывает эту дыру —
интерфейс и планировщик шагов видят состав флота даже тогда, когда сервер упал, а
живой каталог (если он прочитан) всегда важнее кэша.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.mcp_server_spec import MCPServerSpec
from ..domain.mcp_tools import MCPToolInfo, make_tool_infos
from .mcp_client import MCPClient


@dataclass
class FleetMember:
    """Сервер флота: конфигурация, соединение, каталог инструментов и ошибка."""

    spec: MCPServerSpec
    client: MCPClient | None = None
    tools: list[MCPToolInfo] = field(default_factory=list)
    error: str | None = None

    @property
    def name(self) -> str:
        """Имя сервера (оно же — ключ записи в файле конфигурации)."""
        return self.spec.name

    @property
    def connected(self) -> bool:
        """Открыто ли соединение с этим сервером прямо сейчас."""
        return self.client is not None and self.client.connected

    @property
    def state(self) -> str:
        """Состояние подключения (FSM клиента, а без клиента — ``disconnected``)."""
        return "disconnected" if self.client is None else self.client.state.value

    def catalog(self) -> list[MCPToolInfo]:
        """Каталог сервера: живой список инструментов, иначе кэш из файла конфигурации."""
        if self.tools:
            return list(self.tools)
        return make_tool_infos([dict(tool) for tool in self.spec.tools_cache])
