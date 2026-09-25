"""Pydantic-схемы API флота MCP-серверов (день 20).

``GET /mcp/servers`` теперь отдаёт не каталог «известных серверов для сравнения»
(как в дне 16), а РЕАЛЬНЫЙ состав флота из ``mcp_servers.json``: имя, команду
запуска, описание, число инструментов и состояние подключения каждого сервера.
Поэтому ``connected`` — не «какой сервер выбран пользователем», а «этот сервер
подключён прямо сейчас»: соединений у процесса столько, сколько серверов в файле.

Схемы повторяют форму словаря ``MCPServerSpec.to_status`` и ответа
``registry.fleet_status()``: роутер переупаковывает только ``tools`` (доменную
``MCPToolInfo`` в ``MCPToolSchema``, см. ``backend/schemas/mcp.py``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .mcp import MCPToolSchema


class MCPServerInfo(BaseModel):
    """Сервер флота: как его запустить и подключён ли он сейчас."""

    name: str = Field(..., description="Имя сервера из mcp_servers.json")
    command: str = Field(..., description="Команда запуска сервера (обычно uv)")
    args: List[str] = Field(
        default_factory=list, description="Аргументы команды: относительный путь server.py и его ключи"
    )
    description: str = Field("", description="Что умеет сервер и какие инструменты публикует")
    target: str = Field(..., description="Цель подключения одной строкой (команда с аргументами)")
    transport: str = Field("stdio", description="Транспорт подключения: stdio")
    connected: bool = Field(False, description="Открыто ли соединение с этим сервером прямо сейчас")
    state: str = Field(
        "disconnected", description="Состояние подключения: disconnected | connecting | connected | error"
    )
    tool_count: int = Field(
        0, description="Сколько инструментов у сервера (из tools/list или из кэша файла)"
    )
    error: Optional[str] = Field(None, description="Текст последней ошибки подключения этого сервера")


class MCPServersResponse(BaseModel):
    """GET /mcp/servers — состав флота и состояние подключений."""

    servers: List[MCPServerInfo] = Field(
        default_factory=list, description="Серверы в порядке файла конфигурации"
    )
    count: int = Field(0, description="Сколько серверов в флоте")
    connected: int = Field(0, description="Сколько серверов подключено прямо сейчас")
    total_tools: int = Field(0, description="Сколько инструментов публикует флот целиком")


class MCPServerToolsResponse(BaseModel):
    """GET /mcp/servers/{name}/tools — инструменты одного сервера флота."""

    server: str = Field(..., description="Имя сервера")
    tools: List[MCPToolSchema] = Field(
        default_factory=list, description="Инструменты сервера с описанием и схемами"
    )
    count: int = Field(0, description="Сколько инструментов вернул сервер")
    cached: bool = Field(
        False, description="Отдан ли каталог из кэша файла (сервер не подключён или каталог не читался)"
    )


class MCPRefreshResponse(BaseModel):
    """POST /mcp/servers/refresh — обновлённый кэш инструментов всего флота."""

    servers: List[MCPServerInfo] = Field(
        default_factory=list, description="Серверы после обновления кэша"
    )
    count: int = Field(0, description="Сколько серверов в флоте")
    total_tools: int = Field(0, description="Сколько инструментов получилось всего")
    refreshed_at: str = Field("", description="Момент обновления (ISO-8601, UTC)")


class MCPToolInfoPayload(BaseModel):
    """Инструмент флота словарём (для отчётов и отладки): поля как у ``MCPToolInfo``."""

    name: str = Field(..., description="Имя инструмента")
    description: str = Field("", description="Описание для модели")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="Схема аргументов")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="Схема результата")
