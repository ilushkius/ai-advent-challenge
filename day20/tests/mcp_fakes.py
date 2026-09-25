"""Фейковый MCP-клиент и каталоги инструментов для тестов дня 17.

MCP-фейки живут отдельно от ``support.py`` (там фейк DeepSeek и помощники БД):
``MCPClient`` поднимал бы дочерний процесс или ходил в сеть, поэтому тесты
реестра, раннера, агента и эндпоинтов ``/mcp`` подменяют его этими классами.

Состояние подключения у ``FakeMCPClient`` настоящее — стейт-машина
``backend.domain.mcp_connection_fsm``, поэтому граф проверяется и через API. Вызов
инструмента настраивается ключами ``call_result`` (успех), ``call_error``
(инструмент вернул ошибку) и ``call_fail`` (обрыв связи), а ``call_calls`` хранит
все вызовы — по нему видно, что агент не звал инструмент, когда реплика его не
требует.

Каталогов два: ``FAKE_MCP_TOOLS`` (echo/add — каталог как данные, им пользуются
унаследованные тесты дня 16) и ``FAKE_TOOL_CATALOG`` — инструменты своего сервера
дня 18 (``get_user``, ``get_post``, ``list_user_posts`` и три инструмента
планировщика: ``schedule_reminder``, ``collect_data``, ``generate_summary``) со
схемами аргументов, на которые опираются правила допуска и распознавание реплики.
"""
import json

from backend.domain.mcp_connection_fsm import (
    MCPConnectionEvent,
    MCPConnectionFSM,
    MCPConnectionState,
)
from backend.domain.mcp_target import MCPTransport, parse_target
from backend.domain.mcp_tools import MCPToolInfo, MCPToolResult
from backend.services.mcp_client import MCPConnectionError, MCPNotConnectedError

# ---------- фейковый MCP-клиент (день 16) ----------
#: Инструменты, которые «возвращает» фейковый сервер в тестах.
FAKE_MCP_TOOLS = (
    MCPToolInfo(name="echo", description="Возвращает текст",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}}),
    MCPToolInfo(name="add", description="Складывает числа",
                input_schema={"type": "object", "properties": {"a": {"type": "integer"}}}),
)

#: Ответ ``initialize`` фейкового сервера.
FAKE_MCP_SERVER = {"name": "fake-mcp", "version": "1.0.0", "protocol": "2025-11-25"}

#: Инструменты фейкового сервера дня 17: имена своего MCP-сервера со схемами
#: аргументов и результата. Отдельный каталог, потому что унаследованный
#: ``FAKE_MCP_TOOLS`` (echo/add) проверяет каталог как данные, а этим пользуются
#: правила допуска и распознавание реплики — им нужны ``required`` и типы.
FAKE_TOOL_CATALOG = (
    MCPToolInfo(
        name="get_user",
        description="Данные пользователя по id",
        input_schema={
            "type": "object",
            "properties": {"user_id": {"type": "integer"}},
            "required": ["user_id"],
        },
        output_schema={"type": "object", "properties": {"id": {"type": "integer"},
                                                       "name": {"type": "string"}}},
    ),
    MCPToolInfo(
        name="get_post",
        description="Пост по id",
        input_schema={
            "type": "object",
            "properties": {"post_id": {"type": "integer"}},
            "required": ["post_id"],
        },
        output_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
    ),
    MCPToolInfo(
        name="list_user_posts",
        description="Посты пользователя",
        input_schema={
            "type": "object",
            "properties": {"user_id": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": ["user_id"],
        },
        output_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
    ),
    MCPToolInfo(
        name="schedule_reminder",
        description="Разовое напоминание через delay_seconds секунд (день 18)",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "delay_seconds": {"type": "integer"}},
            "required": ["text", "delay_seconds"],
        },
        output_schema={"type": "object", "properties": {"reminder_id": {"type": "integer"},
                                                       "remind_at": {"type": "string"}}},
    ),
    MCPToolInfo(
        name="collect_data",
        description="Периодический сбор данных по адресу (день 18)",
        input_schema={
            "type": "object",
            "properties": {"source_url": {"type": "string"},
                           "interval_seconds": {"type": "integer"},
                           "name": {"type": "string"}},
            "required": ["source_url", "interval_seconds", "name"],
        },
        output_schema={"type": "object", "properties": {"records_saved": {"type": "integer"}}},
    ),
    MCPToolInfo(
        name="generate_summary",
        description="Регулярная сводка по накопленным данным (день 18)",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "interval_seconds": {"type": "integer"}},
            "required": ["name", "interval_seconds"],
        },
        output_schema={"type": "object", "properties": {"total_records": {"type": "integer"}}},
    ),
)


class FakeMCPClient:
    """MCP-клиент без транспорта: настоящая FSM подключения, вместо сессии — список.

    Повторяет публичный контракт ``MCPClient`` (``target``, ``state``,
    ``connected``, ``tools``, ``server_info``, ``last_error``, ``allowed_events``,
    ``connect``, ``list_tools``, ``call_tool``, ``close``). ``fail`` задаёт
    сценарий «сервер недоступен»: ``connect`` уходит в ``error`` и падает с
    ``MCPConnectionError`` — так проверяются 502 у ``/mcp/connect`` и состояние
    ``error`` у статуса.

    Вызов инструмента настраивается тремя ключами: ``call_result`` — что вернуть
    в ``structured_content``, ``call_error`` — ответ инструмента с ``is_error``,
    ``call_fail`` — сбой связи (исключение). Все вызовы записываются в
    ``call_calls``, поэтому тест видит, что агент действительно не вызывал
    инструмент, когда реплика его не требует.
    """

    def __init__(self, target, *, transport=MCPTransport.AUTO, timeout=None,
                 cwd=None, fail: str | None = None, tools=None,
                 call_result: dict | None = None, call_error: str | None = None,
                 call_fail: str | None = None):
        self._target = parse_target(target, transport)
        self._fsm = MCPConnectionFSM()
        self._tools = tuple(FAKE_MCP_TOOLS if tools is None else tools)
        self._fail = fail
        self._call_result = call_result
        self._call_error = call_error
        self._call_fail = call_fail
        self._last_error: str | None = None
        self._listed = False
        self.closed = False
        self.list_calls = 0
        self.call_calls: list[dict] = []

    @property
    def target(self):
        return self._target

    @property
    def state(self) -> MCPConnectionState:
        return self._fsm.state

    @property
    def connected(self) -> bool:
        return self._fsm.state is MCPConnectionState.CONNECTED

    @property
    def tools(self):
        """Как у настоящего клиента: пусто до первого ``list_tools``."""
        return self._tools if self._listed else ()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def server_info(self) -> dict:
        return dict(FAKE_MCP_SERVER) if self.connected else {}

    def allowed_events(self):
        return self._fsm.allowed_events()

    def connect(self) -> "FakeMCPClient":
        self._fsm.handle(MCPConnectionEvent.CONNECT)
        if self._fail:
            self._fsm.handle(MCPConnectionEvent.FAIL)
            self._last_error = self._fail
            raise MCPConnectionError(self._fail)
        self._fsm.handle(MCPConnectionEvent.CONNECTED)
        return self

    def list_tools(self, *, refresh: bool = False):
        if not self.connected:
            raise MCPNotConnectedError(
                f"Соединение с MCP-сервером не установлено (состояние {self.state.value})"
            )
        self.list_calls += 1
        self._listed = True
        return list(self._tools)

    def call_tool(self, tool_name: str, arguments=None):
        """Фейковый ``tools/call``: сценарий задан ``call_fail``/``call_error``.

        Без соединения — как настоящий клиент — ``MCPNotConnectedError``: иначе
        тесты раннера и агента не отличали бы «нет соединения» от «инструмент
        ответил».
        """
        if not self.connected:
            raise MCPNotConnectedError(
                f"Соединение с MCP-сервером не установлено (состояние {self.state.value})"
            )
        args = dict(arguments or {})
        self.call_calls.append({"tool": tool_name, "arguments": args})
        if self._call_fail:
            raise MCPConnectionError(self._call_fail)
        if self._call_error:
            return MCPToolResult(tool=tool_name, arguments=args, text=self._call_error,
                                 is_error=True, duration_ms=1)
        structured = self._call_result if self._call_result is not None else {
            "tool": tool_name, **args,
        }
        return MCPToolResult(
            tool=tool_name, arguments=args, structured=structured,
            text=json.dumps(structured, ensure_ascii=False), duration_ms=1,
        )

    def close(self) -> None:
        self.closed = True
        if self._fsm.can(MCPConnectionEvent.DISCONNECT):
            self._fsm.handle(MCPConnectionEvent.DISCONNECT)


def make_mcp_factory(**client_kwargs):
    """Фабрика фейковых клиентов: ``factory.created`` — все созданные экземпляры.

    Реестр зовёт фабрику как ``MCPClient(target, transport=...)`` и как фабрику
    флота (``timeout=..., cwd=...``), поэтому сигнатура совпадает с настоящим
    клиентом; список ``created`` нужен тестам, чтобы убедиться, что прежнее
    соединение закрыто, а не забыто.
    """
    created: list[FakeMCPClient] = []

    def factory(target, *, transport=MCPTransport.AUTO, timeout=None, cwd=None):
        client = FakeMCPClient(target, transport=transport, timeout=timeout,
                               cwd=cwd, **client_kwargs)
        created.append(client)
        return client

    factory.created = created
    return factory


