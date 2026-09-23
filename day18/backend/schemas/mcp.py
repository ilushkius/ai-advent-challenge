"""Схемы API дня 17: MCP-подключение, инструменты, их вызов и каталог серверов.

Поля ответа ``GET /mcp/tools`` — ровно контракт задания дня: ``name``,
``description``, ``input_schema``, ``output_schema`` плюс ``count`` (сколько
инструментов вернул сервер). Схема собирается из доменной структуры
``MCPToolInfo`` методом ``from_info``: поля контракта описаны в одном месте
(``backend/domain/mcp_tools.py``), а не дублируются в двух модулях.
``output_schema`` приходит не от всякого сервера — тогда поле остаётся пустым
словарём, а инструмент работает.

``POST /mcp/call`` отвечает ``MCPCallResponse``, а то же в сокращённом виде
попадает в генерацию как поле ``mcp`` (``MCPCallReportOut``): по нему видно,
какой инструмент был вызван агентом, с какими аргументами и ушли ли данные в
промпт. ``GET /mcp/servers`` отдаёт каталог известных серверов
(``MCPServerSchema``) — это не список открытых соединений: подключение у
процесса одно.

Транспорт в теле запроса — enum ``MCPTransport``: значение вне списка ловит
Pydantic (422), поэтому сервис получает уже проверенную цель.
"""
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..domain.mcp_target import MCPTransport
from ..domain.mcp_tools import MCPToolInfo


class MCPToolSchema(BaseModel):
    """Инструмент MCP-сервера: имя, описание и JSON Schema аргументов и результата."""

    name: str = Field(..., description="Имя инструмента, как его зовёт сервер")
    description: str = Field("", description="Описание инструмента (может быть пустым)")
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema аргументов инструмента (inputSchema из MCP)",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema структурированного результата инструмента (outputSchema из MCP)",
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


class MCPCallIn(BaseModel):
    """Тело POST /mcp/call — имя инструмента и его аргументы."""

    tool: str = Field(
        ...,
        min_length=1,
        max_length=config.MCP_TOOL_NAME_MAX,
        description="Имя инструмента из GET /mcp/tools",
        examples=["get_user"],
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Аргументы инструмента по его input_schema",
        examples=[{"user_id": 1}],
    )


class MCPCallResponse(BaseModel):
    """POST /mcp/call — что произошло с вызовом инструмента.

    Одна схема описывает четыре случая, и ``state`` говорит, какой именно:
    ``done`` — результат есть; ``failed`` — сбой связи (``reason_code =
    transport``) или ошибка инструмента (``tool_error``); ``rejected`` — правила
    допуска не пустили (в ``reason_code`` — почему, в ``error`` — текст).
    ``rejected`` приходит с HTTP 400/409, остальные — с 200.
    """

    accepted: bool = Field(..., description="Прошли ли аргументы проверку по input_schema")
    state: str = Field(
        ...,
        description="Состояние вызова: idle | planned | invoked | done | failed | rejected",
    )
    detected: bool = Field(True, description="Распознан ли вызов по реплике/запросу")
    connected: bool = Field(..., description="Было ли соединение на момент вызова")
    called: bool = Field(..., description="Ушёл ли запрос инструмента на сервер")
    tool: Optional[str] = Field(None, description="Имя вызванного инструмента")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Аргументы, с которыми шёл вызов",
    )
    result: Optional[Any] = Field(
        None, description="Результат инструмента (structured + text + duration_ms)"
    )
    is_error: bool = Field(
        False, description="Вернул ли инструмент ошибку (сбой связи — false)"
    )
    reason_code: Optional[str] = Field(
        None,
        description="Причина: not_connected | unknown_tool | bad_arguments | transport | tool_error",
    )
    error: Optional[str] = Field(None, description="Текст причины отказа или сбоя")
    duration_ms: int = Field(0, description="Длительность вызова, мс")
    allowed_events: List[str] = Field(
        default_factory=list,
        description="События FSM вызова, допустимые в этом состоянии",
    )


class MCPCallReportOut(MCPCallResponse):
    """Поле ``mcp`` ответа генерации: то же плюс вклад вызова в промпт."""

    used_in_prompt: bool = Field(
        False, description="Ушли ли данные инструмента в системный промпт этого запроса"
    )
    added_tokens: int = Field(0, description="Сколько токенов добавил блок данных")


class MCPServerSchema(BaseModel):
    """Сервер каталога ``GET /mcp/servers``: цель, подпись и состояние."""

    key: str = Field(..., description="Ключ сервера: day18-jsonplaceholder | fetch | filesystem")
    label: str = Field(..., description="Человекочитаемое имя сервера")
    target: str = Field(..., description="Цель подключения (команда запуска или URL)")
    description: str = Field("", description="Что умеет сервер и что ему нужно для запуска")
    connected: bool = Field(False, description="Открыто ли соединение именно с этим сервером")
    tool_count: int = Field(
        0, description="Сколько инструментов получено (0 — не подключён или список не запрашивали)"
    )


class MCPServersResponse(BaseModel):
    """GET /mcp/servers — каталог известных серверов и текущее подключение."""

    servers: List[MCPServerSchema] = Field(
        default_factory=list, description="Серверы в объявленном порядке"
    )
    count: int = Field(0, description="Сколько серверов в каталоге")
    connected_target: Optional[str] = Field(
        None, description="Цель открытого соединения (None — не подключено)"
    )
    connected_key: Optional[str] = Field(
        None, description="Ключ подключённого сервера из каталога (None — совпадений нет)"
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
