"""Прикладной слой дня 18: сервисы, оркеструющие доменные правила и хранилище.

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
  одним исходом (домен встречается с реестром только здесь);
- ``source_fetch`` — ``fetch_json``: единственное место, где фон ходит в сеть;
- ``scheduled_jobs`` — действия трёх инструментов планировщика: ``prepare``
  (немедленно при регистрации) и ``tick`` (по расписанию);
- ``apscheduler_bridge`` — мост к APScheduler: триггеры, имена job'ов, создание и
  остановка планировщика (единственное место, знающее его классы);
- ``scheduler`` — ``TaskScheduler``: сверка БД с планировщиком, постановка и снятие
  задач, исполнение тика одним путём (день 18);
- ``schedule_service`` — ``ScheduleService``: операции уровня инструментов —
  создание задачи, пауза, возобновление, удаление, чтение данных планировщика.

Сервисы знают про домен и хранилище, но не про HTTP и не про Streamlit.
"""

from . import (
    apscheduler_bridge, compressor, invariant_checker, mcp_client, mcp_errors,
    mcp_loop, mcp_registry, mcp_tool_runner, mcp_transport, schedule_service,
    scheduled_jobs, scheduler, source_fetch, task_state,
)
from .apscheduler_bridge import RECONCILE_JOB_ID, TASK_JOB_PREFIX
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
from .schedule_service import ScheduleService, get_schedule_service
from .scheduled_jobs import prepare, tick, tool_names
from .scheduler import TaskScheduler, get_scheduler
from .source_fetch import SourceFetchError, fetch_json
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
    "RECONCILE_JOB_ID",
    "START_STAGES",
    "SUMMARY_SYSTEM_PROMPT",
    "TASK_JOB_PREFIX",
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
    "ScheduleService",
    "SourceFetchError",
    "TaskExistsError",
    "TaskNotFoundError",
    "TaskScheduler",
    "TaskStateMachine",
    "apscheduler_bridge",
    "compressor",
    "fetch_json",
    "get_mcp_registry",
    "get_schedule_service",
    "get_scheduler",
    "invariant_checker",
    "make_checker_client",
    "mcp_client",
    "mcp_errors",
    "mcp_loop",
    "mcp_registry",
    "mcp_tool_runner",
    "mcp_transport",
    "prepare",
    "schedule_service",
    "scheduled_jobs",
    "scheduler",
    "source_fetch",
    "task_state",
    "tick",
    "tool_names",
]
