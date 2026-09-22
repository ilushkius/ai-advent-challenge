"""Схемы API дня 16: MCP-подключение, статус и список инструментов.

Поля ответа ``GET /mcp/tools`` — ровно контракт задания дня: ``name``,
``description``, ``input_schema`` плюс ``count`` (сколько инструментов вернул
сервер). Схема собирается из доменной структуры ``MCPToolInfo`` методом
``from_info``: поля контракта описаны в одном месте
(``backend/domain/mcp_tools.py``), а не дублируются в двух модулях.

Транспорт в теле запроса — enum ``MCPTransport``: значение вне списка ловит
Pydantic (422), поэтому сервис получает уже проверенную цель.
"""
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..domain.mcp_target import MCPTransport
from ..domain.mcp_tools import MCPToolInfo


class MCPToolSchema(BaseModel):
    """Инструмент MCP-сервера: имя, описание и JSON Schema аргументов."""

    name: str = Field(..., description="Имя инструмента, как его зовёт сервер")
    description: str = Field("", description="Описание инструмента (может быть пустым)")
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema аргументов инструмента (inputSchema из MCP)",
    )

    @classmethod
    def from_info(cls, tool: MCPToolInfo) -> "MCPToolSchema":
        """Собирает схему из доменной структуры инструмента."""
        return cls(**tool.to_dict())


class MCPConnectIn(BaseModel):
    """Тело POST /mcp/connect — цель подключения и, при необходимости, транспорт."""

    target: str = Field(
        ...,
        min_length=1,
        max_length=config.MCP_TARGET_MAX,
        description=(
            "URL MCP-сервера (http:// — Streamable HTTP, sse:// — SSE) или "
            "команда запуска по stdio, например 'uvx mcp-server-fetch'"
        ),
        examples=["uvx mcp-server-fetch", "npx -y @modelcontextprotocol/server-filesystem ."],
    )
    transport: MCPTransport = Field(
        MCPTransport.AUTO,
        description=(
            "Транспорт: auto (по виду цели) | stdio | sse | http. "
            "Явное значение сильнее автоопределения."
        ),
    )


class MCPStatusResponse(BaseModel):
    """GET /mcp/status — состояние подключения процесса к MCP-серверу."""

    connected: bool = Field(..., description="Открыто ли соединение прямо сейчас")
    state: str = Field(..., description="Состояние FSM: disconnected | connecting | connected | error")
    target: Optional[str] = Field(None, description="Цель подключения (URL или команда)")
    transport: Optional[str] = Field(None, description="Транспорт: stdio | sse | http")
    transport_label: Optional[str] = Field(None, description="Человекочитаемое имя транспорта")
    server_name: str = Field("", description="Имя сервера из initialize (пусто без соединения)")
    server_version: str = Field("", description="Версия сервера из initialize")
    protocol: str = Field("", description="Версия протокола MCP, согласованная при initialize")
    tool_count: int = Field(0, description="Сколько инструментов получено (0 — список не запрашивали)")
    error: Optional[str] = Field(None, description="Текст последней ошибки соединения")
    allowed_events: List[str] = Field(
        default_factory=list,
        description="События FSM, допустимые в текущем состоянии (граф допуска)",
    )


class MCPToolsResponse(BaseModel):
    """GET /mcp/tools — каталог инструментов подключённого MCP-сервера."""

    tools: List[MCPToolSchema] = Field(default_factory=list, description="Инструменты сервера")
    count: int = Field(0, description="Количество инструментов в списке")
    target: Optional[str] = Field(None, description="Цель, у которой запрошен список")
    transport: Optional[str] = Field(None, description="Транспорт подключения")
    server_name: str = Field("", description="Имя сервера из initialize")
    server_version: str = Field("", description="Версия сервера из initialize")
