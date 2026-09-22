"""Роутер API дня 16: MCP-подключение, статус и список инструментов.

Четыре эндпоинта:

- ``GET  /mcp/status`` — состояние подключения (FSM), сервер, число инструментов;
- ``POST /mcp/connect`` — подключиться к серверу по цели (URL или команда);
- ``POST /mcp/disconnect`` — закрыть соединение;
- ``GET  /mcp/tools`` — список инструментов сервера (``refresh=true`` — заново).

Контракт ошибок: цель не разобрана (пустая строка, неизвестный транспорт) — 400;
сервер недоступен, команда не найдена, таймаут, ошибка ``tools/list`` — 502 с
понятным текстом; запрос инструментов без соединения — 409 (это конфликт
состояний, а не ошибка запроса); невалидное тело — 422 от Pydantic.

Инструменты только ЧИТАЮТСЯ: день 16 показывает каталог возможностей сервера и
не вызывает ни один из них.
"""
from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..domain.mcp_target import MCPTargetError
from ..schemas import (
    MCPConnectIn, MCPStatusResponse, MCPToolSchema, MCPToolsResponse,
)
from ..services.mcp_client import MCPError, MCPNotConnectedError, MCPToolsError

router = APIRouter()


@router.get(
    "/mcp/status",
    response_model=MCPStatusResponse,
    summary="Статус MCP-подключения",
    description=(
        "Текущее состояние подключения процесса к MCP-серверу: `connected`, "
        "состояние FSM (`disconnected` | `connecting` | `connected` | `error`), "
        "цель и транспорт, имя и версия сервера из `initialize`, число "
        "полученных инструментов, текст последней ошибки и события, допустимые "
        "в этом состоянии."
    ),
)
def mcp_status():
    return _status()


@router.post(
    "/mcp/connect",
    response_model=MCPStatusResponse,
    summary="Подключиться к MCP-серверу",
    description=(
        "Открывает соединение с MCP-сервером: `initialize` и согласование "
        "протокола. Цель — URL (`http://` — Streamable HTTP, `sse://` — SSE) или "
        "команда запуска по stdio (`uvx mcp-server-fetch`, "
        "`npx -y @modelcontextprotocol/server-filesystem .`); транспорт можно "
        "задать явно. Прежнее соединение процесса закрывается. Недоступный "
        "сервер — 502 с понятным текстом, неразобранная цель — 400."
    ),
)
def mcp_connect(body: MCPConnectIn):
    registry = dependencies.get_mcp_registry()
    try:
        registry.connect(body.target, body.transport)
    except MCPTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _status()


@router.post(
    "/mcp/disconnect",
    response_model=MCPStatusResponse,
    summary="Отключиться от MCP-сервера",
    description=(
        "Закрывает соединение и останавливает дочерний процесс stdio-сервера. "
        "Повторный вызов без соединения — безопасный no-op (состояние "
        "`disconnected`)."
    ),
)
def mcp_disconnect():
    dependencies.get_mcp_registry().disconnect()
    return _status()


@router.get(
    "/mcp/tools",
    response_model=MCPToolsResponse,
    summary="Список инструментов MCP-сервера",
    description=(
        "Возвращает каталог инструментов подключённого сервера (`tools/list`): "
        "`name`, `description`, `input_schema` и `count`. Список кэшируется до "
        "`refresh=true` — с ним сервер опрашивается заново. Без соединения — 409, "
        "ошибка самого запроса к серверу — 502."
    ),
)
def mcp_tools(refresh: bool = False):
    registry = dependencies.get_mcp_registry()
    try:
        tools = registry.tools(refresh=refresh)
    except MCPNotConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MCPToolsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    status = registry.status()
    return MCPToolsResponse(
        tools=[MCPToolSchema.from_info(tool) for tool in tools],
        count=len(tools),
        target=status["target"],
        transport=status["transport"],
        server_name=status["server_name"],
        server_version=status["server_version"],
    )


def _status() -> MCPStatusResponse:
    """Состояние реестра в схеме ответа (общий ответ connect/disconnect/status)."""
    return MCPStatusResponse(**dependencies.get_mcp_registry().status())
