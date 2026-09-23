"""Роутер API дня 17: MCP-подключение, инструменты, вызов и каталог серверов.

Шесть эндпоинтов:

- ``GET  /mcp/status`` — состояние подключения (FSM), сервер, число инструментов;
- ``POST /mcp/connect`` — подключиться к серверу по цели (URL или команда);
- ``POST /mcp/disconnect`` — закрыть соединение;
- ``GET  /mcp/tools`` — список инструментов сервера (``refresh=true`` — заново);
- ``POST /mcp/call`` — вызвать инструмент с аргументами;
- ``GET  /mcp/servers`` — каталог известных серверов и кто из них подключён.

Контракт ошибок ``POST /mcp/call``: инструмент не найден в каталоге или
аргументы не подходят по ``input_schema`` — 400; соединения нет — 409;
соединение оборвалось и ответа не получено — 502. Ошибка самого инструмента
(например, «пользователя с id=999 нет») — это ОТВЕТ сервера, а не отказ запроса:
она приходит с 200 и ``is_error: true``, потому что модель и пользователь должны
видеть текст причины, а не HTTP-код.

Остальные коды: цель подключения не разобрана — 400, сервер недоступен — 502,
невалидное тело (нет ``tool``, слишком длинное имя, неизвестный транспорт) — 422.
"""
from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..domain.mcp_servers import server_records
from ..domain.mcp_target import MCPTargetError
from ..domain.mcp_tool_call import (
    REASON_NOT_CONNECTED,
    REASON_TRANSPORT,
    MCPToolCallState,
    allowed_events,
)
from ..schemas import (
    MCPCallIn, MCPCallResponse, MCPConnectIn, MCPServersResponse, MCPStatusResponse,
    MCPToolSchema, MCPToolsResponse,
)
from ..services.mcp_client import MCPError, MCPNotConnectedError, MCPToolsError
from ..services.mcp_tool_runner import MCPToolRunner

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


@router.post(
    "/mcp/call",
    response_model=MCPCallResponse,
    summary="Вызвать инструмент MCP-сервера",
    description=(
        "Проверяет аргументы по `input_schema` инструмента и вызывает его "
        "(`tools/call`) на подключённом сервере. Успех — 200 с `result` "
        "(структурированный ответ и текст). Инструмент не найден в каталоге или "
        "аргументы не подходят — 400; соединения нет — 409; соединение "
        "оборвалось — 502. Ошибка самого инструмента приходит с 200 и "
        "`is_error: true`: это ответ сервера, а не отказ запроса."
    ),
)
def mcp_call(body: MCPCallIn):
    runner = MCPToolRunner(dependencies.get_mcp_registry())
    outcome = runner.call(body.tool, body.arguments)
    if outcome.state is MCPToolCallState.REJECTED:
        code = 409 if outcome.reason_code == REASON_NOT_CONNECTED else 400
        raise HTTPException(status_code=code, detail=outcome.error)
    if outcome.state is MCPToolCallState.FAILED and outcome.reason_code == REASON_TRANSPORT:
        raise HTTPException(status_code=502, detail=outcome.error)
    payload = outcome.to_dict()
    payload["allowed_events"] = [event.value for event in allowed_events(outcome.state)]
    return MCPCallResponse(**payload)


@router.get(
    "/mcp/servers",
    response_model=MCPServersResponse,
    summary="Доступные MCP-серверы",
    description=(
        "Каталог известных MCP-серверов: свой сервер дня (jsonplaceholder) и два "
        "сервера официального набора — с целью подключения и описанием. "
        "`connected` истинно ровно у одного сервера — того, с которым открыто "
        "соединение процесса (`tool_count` тогда показывает число его "
        "инструментов). Это НЕ список одновременных подключений: у процесса одно "
        "соединение (см. `GET /mcp/status`)."
    ),
)
def mcp_servers():
    status = dependencies.get_mcp_registry().status()
    records = server_records(status["target"], status["tool_count"])
    return MCPServersResponse(
        servers=records,
        count=len(records),
        connected_target=status["target"],
        connected_key=next((item["key"] for item in records if item["connected"]), None),
    )


def _status() -> MCPStatusResponse:
    """Состояние реестра в схеме ответа (общий ответ connect/disconnect/status)."""
    return MCPStatusResponse(**dependencies.get_mcp_registry().status())
