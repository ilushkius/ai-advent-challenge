"""Прикладной слой дня 16: сервисы, оркеструющие доменные правила и хранилище.

- ``compressor`` — ``ContextCompressor``: вызов суммаризации и запись конспекта;
- ``task_state`` — ``TaskStateMachine``: переходы состояния задачи (валидация по
  ``backend.domain.task_fsm``, запись через ``backend.storage.task_store``);
- ``invariant_checker`` — ``InvariantChecker``: проверка текста на нарушение
  инвариантов (сначала детерминированные правила, затем — при неоднозначности —
  один вызов DeepSeek);
- ``mcp_client`` — ``MCPClient``: соединение с MCP-сервером (stdio, SSE или
  Streamable HTTP) и список его инструментов (``tools/list``);
- ``mcp_errors`` — ошибки MCP и понятные тексты (их показывают UI, API и скрипт);
- ``mcp_registry`` — ``MCPRegistry``: одно активное MCP-подключение процесса
  (смена соединения, статус, закрытие) — то, чем пользуются роутер и UI.

Сервисы знают про домен и хранилище, но не про HTTP и не про Streamlit.
"""

from . import (
    compressor, invariant_checker, mcp_client, mcp_errors, mcp_registry, task_state,
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
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPNotConnectedError,
    MCPToolsError,
    SUBMIT_GRACE,
)
from .mcp_registry import MCPRegistry, get_mcp_registry
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
    "MCPConnectionError",
    "MCPError",
    "MCPNotConnectedError",
    "MCPRegistry",
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
    "mcp_registry",
    "task_state",
]
