"""Прикладной слой дня 17: сервисы, оркеструющие доменные правила и хранилище.

- ``compressor`` — ``ContextCompressor``: вызов суммаризации и запись конспекта;
- ``task_state`` — ``TaskStateMachine``: переходы состояния задачи (валидация по
  ``backend.domain.task_fsm``, запись через ``backend.storage.task_store``);
- ``invariant_checker`` — ``InvariantChecker``: проверка текста на нарушение
  инвариантов (сначала детерминированные правила, затем — при неоднозначности —
  один вызов DeepSeek);
- ``mcp_client`` — ``MCPClient``: соединение с MCP-сервером (stdio, SSE или
  Streamable HTTP), список его инструментов (``tools/list``) и вызов инструмента
  (``tools/call``);
- ``mcp_loop`` — ``MCPEventLoop``: цикл событий в отдельном потоке (мост между
  синхронным кодом дня и асинхронным MCP SDK);
- ``mcp_transport`` — адаптеры MCP SDK: транспорт по цели, разбор ``InitializeResult``
  и ``CallToolResult`` (единственное место, знающее про классы SDK);
- ``mcp_errors`` — ошибки MCP и понятные тексты (их показывают UI, API и скрипт);
- ``mcp_registry`` — ``MCPRegistry``: одно активное MCP-подключение процесса
  (смена соединения, статус, каталог, вызов) — то, чем пользуются роутер и UI;
- ``mcp_tool_runner`` — ``MCPToolRunner``: правила допуска плюс вызов инструмента
  одним исходом (домен встречается с реестром только здесь).

Сервисы знают про домен и хранилище, но не про HTTP и не про Streamlit.
"""

from . import (
    compressor, invariant_checker, mcp_client, mcp_errors, mcp_loop, mcp_registry,
    mcp_tool_runner, mcp_transport, task_state,
)
from .compressor import SUMMARY_SYSTEM_PROMPT, CompressionError, ContextCompressor
from .invariant_checker import (
    INVARIANT_CHECK_SYSTEM_PROMPT,
    InvariantCheckResult,
    InvariantChecker,
    InvariantViolation,
    make_checker_client,
)
from .mcp_client import (
    MCPCallError,
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPNotConnectedError,
    MCPToolsError,
)
from .mcp_loop import SUBMIT_GRACE, MCPEventLoop
from .mcp_registry import MCPRegistry, get_mcp_registry
from .mcp_tool_runner import MCPToolRunner
from .task_state import (
    REASON_CREATED,
    REASON_DEFAULT,
    REASON_DONE,
    REASON_NEXT_STEP,
    REASON_PAUSE,
    REASON_RESUME,
    REASON_ROLLBACK,
    START_STAGES,
    TaskExistsError,
    TaskNotFoundError,
    TaskStateMachine,
)

__all__ = [
    "INVARIANT_CHECK_SYSTEM_PROMPT",
    "REASON_CREATED",
    "REASON_DEFAULT",
    "REASON_DONE",
    "REASON_NEXT_STEP",
    "REASON_PAUSE",
    "REASON_RESUME",
    "REASON_ROLLBACK",
    "START_STAGES",
    "SUMMARY_SYSTEM_PROMPT",
    "CompressionError",
    "ContextCompressor",
    "InvariantCheckResult",
    "InvariantChecker",
    "InvariantViolation",
    "MCPClient",
    "MCPCallError",
    "MCPConnectionError",
    "MCPError",
    "MCPEventLoop",
    "MCPNotConnectedError",
    "MCPRegistry",
    "MCPToolRunner",
    "MCPToolsError",
    "SUBMIT_GRACE",
    "TaskExistsError",
    "TaskNotFoundError",
    "TaskStateMachine",
    "compressor",
    "get_mcp_registry",
    "invariant_checker",
    "make_checker_client",
    "mcp_client",
    "mcp_errors",
    "mcp_loop",
    "mcp_registry",
    "mcp_tool_runner",
    "mcp_transport",
    "task_state",
]
