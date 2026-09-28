"""Роутер API дня 20: флот MCP-серверов из ``mcp_servers.json``.

Три эндпоинта:

- ``GET /mcp/servers`` — состав флота и состояние подключений: имя, команда запуска,
  описание, число инструментов, `connected`/`state` и текст ошибки у того сервера,
  который не поднялся. Это НЕ «одно активное соединение» дня 16: соединений столько,
  сколько серверов в конфигурации (за активное соединение раздела «🔌 MCP» отвечает
  ``GET /mcp/status``);
- ``GET /mcp/servers/{name}/tools`` — каталог инструментов одного сервера с
  описанием, `input_schema` и `output_schema`. Неизвестное имя сервера — 404 с
  перечнем известных;
- ``POST /mcp/servers/refresh`` — перечитать ``tools/list`` у каждого подключённого
  сервера и записать кэш в ``mcp_servers.json``. Ответ 200 всегда: сбой отдельного
  сервера — это данные его записи (`error`, `state`), а не отказ всего запроса.

Каталог отдаётся из памяти подключения, а когда сервер не подключён — из кэша файла
(``tools_cache``), и только тогда `cached` истинно: интерфейс так отличает «каталог
прочитан сейчас» от «показан последний известный».
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..schemas import (
    MCPRefreshResponse,
    MCPServerToolsResponse,
    MCPServersResponse,
    MCPToolSchema,
)
from ..services.mcp_errors import MCPUnknownServerError

router = APIRouter()


@router.get(
    "/mcp/servers",
    response_model=MCPServersResponse,
    summary="Серверы флота MCP",
    description=(
        "Состав флота из `mcp_servers.json`: имя, команда запуска, описание, число "
        "инструментов, состояние подключения (`disconnected` | `connecting` | "
        "`connected` | `error`) и текст ошибки у сервера, который не поднялся. "
        "Реестр держит соединение с КАЖДЫМ сервером флота, поэтому `connected` у "
        "нескольких записей может быть истинным одновременно."
    ),
)
def fleet_servers():
    """Состав флота и состояние подключений."""
    return MCPServersResponse(**dependencies.get_mcp_registry().fleet_status())


@router.get(
    "/mcp/servers/{name}/tools",
    response_model=MCPServerToolsResponse,
    summary="Инструменты сервера флота",
    description=(
        "Инструменты одного сервера флота с описанием, `input_schema` и "
        "`output_schema`. Каталог берётся из подключения, а если сервер не "
        "подключён — из кэша файла конфигурации, и тогда `cached` истинно. "
        "Неизвестное имя сервера — 404 с перечнем известных."
    ),
)
def server_tools(name: str):
    """Инструменты одного сервера флота (из соединения или из кэша файла)."""
    registry = dependencies.get_mcp_registry()
    try:
        tools = registry.tools_of(name)
    except MCPUnknownServerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MCPServerToolsResponse(
        server=name,
        tools=[MCPToolSchema.from_info(tool) for tool in tools],
        count=len(tools),
        cached=not registry.connected(name),
    )


@router.post(
    "/mcp/servers/refresh",
    response_model=MCPRefreshResponse,
    summary="Обновить кэш инструментов флота",
    description=(
        "Перечитывает `tools/list` у каждого подключённого сервера и записывает "
        "результат в `tools_cache` файла `mcp_servers.json`. Ответ 200 всегда: "
        "сбой отдельного сервера виден в его записи (`error`, `state`), потому что "
        "один упавший сервер не должен отменять обновление остальных."
    ),
)
def refresh_tools():
    """Обновляет кэш инструментов всего флота и возвращает новое состояние."""
    registry = dependencies.get_mcp_registry()
    registry.refresh_tools()
    status = registry.fleet_status()
    return MCPRefreshResponse(
        **status,
        refreshed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
