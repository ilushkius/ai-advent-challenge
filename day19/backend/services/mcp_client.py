"""MCP-клиент дня 17: соединение с MCP-сервером, каталог и вызов инструментов.

Три транспорта MCP SDK выбираются по виду цели (``backend/domain/mcp_target``):

- **stdio** — сервер запускается дочерним процессом (``npx -y
  @modelcontextprotocol/server-filesystem .``, ``uvx mcp-server-fetch``); обмен
  сообщениями JSON-RPC идёт по stdin/stdout процесса;
- **Streamable HTTP** — один HTTP-эндпоинт (``http://host:port/mcp``);
- **SSE** — ранний HTTP-транспорт (``sse://host:port/sse``).

Сам транспорт создаётся в ``backend/services/mcp_transport.py`` (там же — разбор
объектов SDK: ``InitializeResult`` и ``CallToolResult``): клиент остаётся про
протокол и жизненный цикл, а знание классов MCP SDK живёт в одном модуле.

Жизненный цикл подключения описан стейт-машиной
(``backend/domain/mcp_connection_fsm``): состояние видно в ``/mcp/status``, а
недопустимый шаг — ошибка, а не «тихое» зависание.

Почему клиент синхронный и с собственным циклом событий. MCP SDK асинхронный, а
его транспорты и сессия держат соединение в ``AsyncExitStack``, то есть внутри
task-group anyio. Такой контекст обязан войти и выйти в ОДНОЙ задаче одного
цикла событий: FastAPI-роуты и Streamlit синхронные, поэтому клиент владеет
отдельным потоком с циклом событий и долгоживущей задачей ``_serve`` — она
открывает контексты, держит их до события ``shutdown`` и закрывает в том же
месте. ``connect()``, ``list_tools()`` и ``disconnect()`` — обычные блокирующие
методы; ``list_tools`` выполняется отдельной задачей того же цикла (запрос
``tools/list`` не привязан к задаче-владельцу контекстов). Экземпляр
потокобезопасен (``RLock``): запросы к серверу могут приходить из разных потоков.

Вызов инструментов. День 17 не только читает каталог (``tools/list``), но и
вызывает инструмент (``tools/call``): ``call_tool(name, arguments)`` возвращает
``MCPToolResult``. Ошибка самого инструмента приходит ДАННЫМИ
(``result.is_error``), а исключениями — только отказы транспорта: нет
соединения (``MCPNotConnectedError``), обрыв или таймаут (``MCPCallError``).
Так же устроен протокол MCP: «сервер ответил ошибкой» — это ответ, а «сервер не
ответил» — сбой связи.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
import time
from typing import Any

from mcp import ClientSession
from mcp.types import PaginatedRequestParams

from shared.logging_utils import get_logger

from ..core import config
from ..domain.mcp_connection_fsm import (
    MCPConnectionEvent,
    MCPConnectionFSM,
    MCPConnectionState,
)
from ..domain.mcp_target import MCPTarget, MCPTransport, parse_target
from ..domain.mcp_tools import MCPToolInfo, MCPToolResult, make_tool_info
from .mcp_errors import (
    MCPCallError,
    MCPConnectionError,
    MCPError,
    MCPNotConnectedError,
    MCPToolsError,
    error_message,
)
from .mcp_loop import SUBMIT_GRACE, MCPEventLoop
from .mcp_transport import raw_parts, server_info, transport_context

logger = get_logger(__name__)

#: Какую ошибку отдаёт неудачное обращение к серверу (``_abort``).
_ERROR_BY_ACTION = {
    "tools": MCPToolsError,
    "call": MCPCallError,
}


class MCPClient:
    """Соединение с одним MCP-сервером: connect → list_tools → disconnect.

    Пример::

        client = MCPClient("uvx mcp-server-fetch")
        with client:
            for tool in client.list_tools():
                print(tool.name, tool.input_schema)

    ``close()`` (и выход из контекстного менеджера) закрывают соединение и
    останавливают служебный цикл событий — так сервер-stdio не остаётся висеть
    отдельным процессом.
    """

    def __init__(
        self,
        target: str | MCPTarget,
        *,
        transport: MCPTransport | str = MCPTransport.AUTO,
        timeout: float | None = None,
    ):
        self._target = target if isinstance(target, MCPTarget) else parse_target(target, transport)
        self._timeout = config.MCP_TIMEOUT if timeout is None else float(timeout)
        self._fsm = MCPConnectionFSM()
        self._lock = threading.RLock()
        self._events = MCPEventLoop(f"mcp-{self._target.transport.value}")
        self._shutdown: asyncio.Event | None = None
        self._serving: concurrent.futures.Future | None = None
        self._session: ClientSession | None = None
        self._ready = threading.Event()
        self._open_error: BaseException | None = None
        self._detached = False
        self._tools: tuple[MCPToolInfo, ...] = ()
        self._last_error: str | None = None
        self._server_info: dict[str, str] = {}

    # ---------- состояние ----------
    @property
    def target(self) -> MCPTarget:
        """Разобранная цель подключения (транспорт, URL или команда)."""
        return self._target

    @property
    def state(self) -> MCPConnectionState:
        """Состояние стейт-машины подключения."""
        return self._fsm.state

    @property
    def connected(self) -> bool:
        """Открыто ли соединение прямо сейчас."""
        return self._fsm.state is MCPConnectionState.CONNECTED

    @property
    def tools(self) -> tuple[MCPToolInfo, ...]:
        """Последний полученный список инструментов (пустой до первого запроса)."""
        return self._tools

    @property
    def last_error(self) -> str | None:
        """Текст последней ошибки соединения (None, если ошибок не было)."""
        return self._last_error

    @property
    def server_info(self) -> dict[str, str]:
        """Имя, версия и протокол сервера из ``initialize`` (пусто до подключения)."""
        return dict(self._server_info)

    def allowed_events(self) -> tuple[MCPConnectionEvent, ...]:
        """События, допустимые в текущем состоянии (для UI и лога)."""
        return self._fsm.allowed_events()

    # ---------- жизненный цикл ----------
    def connect(self) -> "MCPClient":
        """Открывает соединение: ``initialize`` и параметры сервера."""
        with self._lock:
            if self._fsm.state is not MCPConnectionState.DISCONNECTED:
                # Граф не знает «CONNECTED + CONNECT»: переподключение — это
                # закрытие старого соединения и открытие нового, два шага.
                self.disconnect()
            self._fsm.handle(MCPConnectionEvent.CONNECT)
            self._detached = False
            logger.info("MCP: подключаюсь к %s [%s]",
                        self._target.label(), self._target.transport.label)
            try:
                self._spawn()
            except MCPError as exc:
                self._fsm.handle(MCPConnectionEvent.FAIL)
                self._last_error = str(exc)
                logger.error("MCP: %s", self._last_error)
                raise
            self._last_error = None
            self._fsm.handle(MCPConnectionEvent.CONNECTED)
            logger.info("MCP: соединение открыто — сервер %s %s",
                        self._server_info.get("name", "?"),
                        self._server_info.get("version", ""))
            return self

    def list_tools(self, *, refresh: bool = False) -> list[MCPToolInfo]:
        """Возвращает список инструментов сервера (``refresh`` — запросить заново).

        Без соединения метод падает с ``MCPNotConnectedError``: «пустой список»
        и «нет соединения» — разные состояния и в UI, и в API.
        """
        with self._lock:
            self._ready_or_raise("tools")
            if self._tools and not refresh:
                return list(self._tools)
            try:
                tools = self._submit(self._fetch_tools())
            except MCPError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._abort("tools", exc) from exc
            self._tools = tuple(tools)
            self._last_error = None
            logger.info("MCP: получено инструментов — %d", len(self._tools))
            return list(self._tools)

    def call_tool(self, tool_name: str,
                  arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """Вызывает инструмент сервера (``tools/call``) и возвращает его результат.

        Без соединения — ``MCPNotConnectedError``; обрыв/таймаут — ``MCPCallError``
        с понятным текстом; ошибка самого инструмента приходит данными
        (``result.is_error``), а не исключением.
        """
        with self._lock:
            self._ready_or_raise("call")
            started = time.perf_counter()
            args = dict(arguments or {})
            try:
                raw = self._submit(self._invoke_tool(tool_name, args))
            except MCPError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._abort("call", exc) from exc
            structured, text, is_error = raw_parts(raw)
            logger.info("MCP: инструмент %s вызван (ошибка инструмента: %s)",
                        tool_name, is_error)
            return MCPToolResult(
                tool=tool_name,
                arguments=args,
                structured=structured,
                text=text,
                is_error=is_error,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def disconnect(self) -> None:
        """Закрывает соединение (повторный вызов без соединения — безопасный no-op)."""
        with self._lock:
            shutdown, serving = self._shutdown, self._serving
            self._shutdown, self._serving = None, None
            self._tools = ()
            if serving is not None:
                if shutdown is not None:
                    self._events.call_soon(shutdown.set)
                # Ошибку обрыва/закрытия логирует и переводит FSM сам _await_close.
                self._await_close(serving)
            self._session = None
            self._detached = False
            self._open_error = None
            self._fsm.handle(MCPConnectionEvent.DISCONNECT)

    def close(self) -> None:
        """Закрывает соединение и останавливает служебный цикл событий."""
        self.disconnect()
        self._events.stop(self._limit())

    def __enter__(self) -> "MCPClient":
        return self.connect()

    def __exit__(self, *_exc_info) -> None:
        self.close()

    # ---------- внутреннее: запуск и остановка соединения ----------
    def _ready_or_raise(self, action: str = "tools") -> None:
        """Общая проверка готовности соединения (``list_tools`` и ``call_tool``).

        Порядок важен: «не подключено» — это состояние FSM (пользователь ещё не
        нажимал «Подключиться»), а «соединение оборвалось» — уже ошибка связи,
        и тексты у них разные (``_not_connected_message`` и ``_abort``).
        """
        if not self.connected:
            raise MCPNotConnectedError(self._not_connected_message())
        if self._detached:
            raise self._abort(action)

    def _spawn(self) -> None:
        """Поднимает задачу соединения и ждёт готовности сессии в этом же цикле."""
        self._ready.clear()
        self._open_error = None
        self._shutdown = asyncio.Event()
        try:
            self._serving = self._events.spawn(self._serve(self._shutdown, self._ready))
            if not self._ready.wait(timeout=self._limit()):
                raise MCPConnectionError(
                    f"MCP-сервер не ответил за {self._limit():.0f} с: {self._target.label()}"
                )
            if self._open_error is not None:
                raise MCPConnectionError(error_message(
                    self._open_error, self._target, self._timeout, "connect"
                ))
        except MCPConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MCPConnectionError(error_message(
                exc, self._target, self._timeout, "connect"
            )) from exc

    async def _serve(self, shutdown: asyncio.Event, ready: threading.Event) -> None:
        """Долгоживущая задача: открывает контексты и закрывает их в этой же задаче.

        Транспорт и сессия MCP SDK живут в task-group anyio, поэтому войти в них
        и выйти из них обязан один и тот же task. Пока соединение нужно, задача
        ждёт ``shutdown``; ``connect()`` в другом потоке узнаёт о готовности по
        ``threading.Event``.
        """
        failure: BaseException | None = None
        try:
            async with contextlib.AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(
                    transport_context(self._target)
                )
                session = ClientSession(read, write, read_timeout_seconds=self._timeout)
                await stack.enter_async_context(session)
                init = await asyncio.wait_for(session.initialize(), timeout=self._timeout)
                self._session = session
                self._server_info = server_info(init)
                ready.set()  # connect() в другом потоке видит готовую сессию
                await shutdown.wait()
        except BaseException as exc:  # noqa: BLE001 — ошибку передаём в connect/list_tools
            failure = exc
        finally:
            self._session = None
            self._open_error = failure
            self._detached = failure is not None
            ready.set()

    def _await_close(self, serving: concurrent.futures.Future) -> bool:
        """Ждёт завершения задачи соединения; True — закрылась без ошибок."""
        try:
            serving.result(timeout=self._limit())
        except Exception as exc:  # noqa: BLE001
            self._note_failure(f"Ошибка закрытия соединения MCP: {exc}")
            return False
        if self._open_error is not None:
            self._note_failure(error_message(
                self._open_error, self._target, self._timeout, "serve"
            ))
            return False
        logger.info("MCP: соединение закрыто (%s)", self._target.label())
        return True

    def _note_failure(self, message: str) -> None:
        """Запоминает ошибку соединения и переводит FSM в ``ERROR``, если можно."""
        self._last_error = message
        logger.error("MCP: %s", message)
        if self._fsm.can(MCPConnectionEvent.FAIL):
            self._fsm.handle(MCPConnectionEvent.FAIL)

    def _abort(self, action: str, exc: BaseException | None = None) -> MCPError:
        """Ошибка оборвавшегося соединения: текст, FSM ``ERROR`` и класс исключения."""
        cause = exc if exc is not None else self._open_error
        message = error_message(cause, self._target, self._timeout, action)
        self._note_failure(message)
        return _ERROR_BY_ACTION.get(action, MCPConnectionError)(message)

    def _not_connected_message(self) -> str:
        """Текст отказа «нет соединения»: состояние и последняя ошибка."""
        message = (
            f"Соединение с MCP-сервером не установлено (состояние {self.state.value}). "
            "Вызовите POST /mcp/connect с целью подключения."
        )
        return f"{message} Последняя ошибка: {self._last_error}" if self._last_error else message

    # ---------- асинхронная часть (выполняется в служебном цикле) ----------
    async def _fetch_tools(self) -> list[MCPToolInfo]:
        """Читает ``tools/list`` постранично (курсор — часть протокола MCP)."""
        collected: list[MCPToolInfo] = []
        cursor: str | None = None
        for _ in range(config.MCP_MAX_TOOL_PAGES):
            params = PaginatedRequestParams(cursor=cursor) if cursor else None
            result = await self._session.list_tools(params=params)
            collected.extend(
                make_tool_info(tool.name, tool.description, tool.input_schema,
                               tool.output_schema)
                for tool in result.tools
            )
            cursor = result.next_cursor
            if not cursor:
                break
        return collected

    async def _invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Вызов ``tools/call``: возвращает ``CallToolResult`` SDK без разбора."""
        return await self._session.call_tool(tool_name, arguments)

    # ---------- служебный цикл событий ----------
    def _submit(self, coro: Any) -> Any:
        """Выполняет корутину в служебном цикле и ждёт результат из этого потока."""
        return self._events.submit(coro, self._limit(), self._timeout_error)

    def _limit(self) -> float:
        """Предел ожидания служебного цикла: таймаут SDK плюс запас на закрытие."""
        return self._timeout + 2 * SUBMIT_GRACE

    def _timeout_error(self) -> MCPError:
        """Ошибка «сервер не ответил»: текст собирается здесь, а не в цикле событий."""
        return MCPConnectionError(
            f"MCP-сервер не ответил за {self._limit():.0f} с: {self._target.label()}"
        )
