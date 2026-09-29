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
- ``mcp_registry`` — ``MCPRegistry``: активное MCP-подключение процесса плюс ФЛОТ
  серверов из ``mcp_servers.json`` (маршрутизация вызова, каталоги, состояния) —
  то, чем пользуются роутер, оркестратор и UI;
- ``mcp_fleet_state`` — ``FleetMember``: состояние одного сервера флота
  (конфигурация, соединение, каталог инструментов, текст ошибки);
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
  создание задачи, пауза, возобновление, удаление, чтение данных планировщика;
- ``off_peak`` — ``shift_to_off_peak``: перенос первого запуска задачи в
  непиковое окно DeepSeek при флаге ``prefer_off_peak`` (день 21);
- ``pipeline`` — ``Pipeline``: прогон декларативного пайплайна MCP-инструментов
  (маппинг данных между шагами, условия перехода, журнал шагов в SQLite);
- ``pipeline_service`` — ``PipelineService``: запуск пайплайна (фоном или
  синхронно), история запусков и чтение их шагов (день 19);
- ``orchestration_planner`` — ``OrchestrationPlanner``: план шагов от модели
  DeepSeek по каталогу флота (любая неудача — ``None``, план соберёт эвристика);
- ``orchestrator`` — ``Orchestrator``: построение плана, прогон шагов по серверам
  флота и журнал в SQLite (день 20);
- ``orchestration_service`` — ``OrchestrationService``: запуск оркестрации (фоном
  или синхронно), демо-сценарий, история, статистика и удаление запусков;
- ``chunker`` — ``FixedSizeChunker``/``StructuralChunker``: две стратегии чанкинга
  документов (окно по токенам с перекрытием и секции документа, день 21);
- ``embedding_service`` — ``EmbeddingService``: модель sentence-transformers,
  ленивая загрузка, батчи и нормализованные векторы (день 21);
- ``index_service`` — ``IndexService``: векторный индекс FAISS плюс метаданные
  чанков в SQLite — построение, поиск, файлы индекса и статистика (день 21);
- ``document_loader`` — ``DocumentLoader``: сборка документов из источников
  репозитория в ``documents/`` и их манифест (день 21);
- ``index_runner`` — ``IndexRunner``: этапы прогона индексации по FSM с журналом
  прогресса (день 21);
- ``index_comparison`` — сборка метрик сравнения стратегий (день 21);
- ``indexing_service`` — ``IndexingService``: запуск прогонов (фоном или
  синхронно), прогресс, поиск, статистика и очистка индекса (день 21);
- ``rag_corpus_loader`` — ``RagCorpusLoader``: корпус режима RAG дня 22 — файлы
  дня 21 в ``documents/rag_corpus/``, объём в страницах и проверка состава;
- ``rag_service`` — ``RAGService``: режим RAG дня 22 — поиск по корпусу, ответ с
  контекстом и без него, бюджет контекста, откат и оценка опоры на фрагменты.

Сервисы знают про домен и хранилище, но не про HTTP и не про Streamlit.
"""

from . import (
    apscheduler_bridge, chunker, compressor, document_loader, embedding_service,
    index_comparison, index_runner, index_service, indexing_service,
    invariant_checker, mcp_client, mcp_errors,
    mcp_fleet_state, mcp_loop, mcp_registry, mcp_tool_runner, mcp_transport,
    off_peak, orchestration_planner,
    orchestration_service, orchestrator, pipeline, pipeline_service,
    schedule_service, scheduled_jobs, scheduler, source_fetch, task_state,
    rag_corpus_loader,
    rag_service,
)
from .apscheduler_bridge import RECONCILE_JOB_ID, TASK_JOB_PREFIX
from .compressor import SUMMARY_SYSTEM_PROMPT, CompressionError, ContextCompressor
from .chunker import Chunk, FixedSizeChunker, StructuralChunker, chunk_document
from .document_loader import DocumentLoader, get_document_loader
from .embedding_service import EmbeddingError, EmbeddingService, get_embedding_service
from .index_service import IndexNotBuiltError, IndexService, get_index_service
from .indexing_service import (
    IndexingRejected,
    IndexingService,
    REASON_BAD_QUERY,
    REASON_BAD_STRATEGY,
    REASON_INDEX_EMPTY,
    REASON_NO_DOCUMENTS,
    REASON_RUN_NOT_FOUND,
    get_indexing_service,
)
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
from .mcp_errors import MCPUnknownServerError, MCPUnknownToolError
from .mcp_loop import SUBMIT_GRACE, MCPEventLoop
from .mcp_registry import MCPRegistry, get_mcp_registry
from .mcp_tool_runner import MCPToolRunner
from .orchestration_planner import OrchestrationPlanner
from .orchestration_service import OrchestrationService, get_orchestration_service
from .orchestrator import Orchestrator
from .pipeline import Pipeline
from .pipeline_service import PipelineService, get_pipeline_service
from .rag_corpus_loader import RagCorpusLoader, get_rag_corpus_loader
from .rag_service import (
    RAGError,
    RAGRejected,
    RAGService,
    RAGUpstreamError,
    get_rag_service,
)
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
    "REASON_BAD_QUERY",
    "REASON_BAD_STRATEGY",
    "REASON_CREATED",
    "REASON_DEFAULT",
    "REASON_DONE",
    "REASON_INDEX_EMPTY",
    "REASON_NEXT_STEP",
    "REASON_NO_DOCUMENTS",
    "REASON_PAUSE",
    "REASON_RESUME",
    "REASON_ROLLBACK",
    "REASON_RUN_NOT_FOUND",
    "RECONCILE_JOB_ID",
    "START_STAGES",
    "SUMMARY_SYSTEM_PROMPT",
    "TASK_JOB_PREFIX",
    "Chunk",
    "CompressionError",
    "ContextCompressor",
    "DocumentLoader",
    "EmbeddingError",
    "EmbeddingService",
    "FixedSizeChunker",
    "IndexNotBuiltError",
    "IndexService",
    "IndexingRejected",
    "IndexingService",
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
    "MCPUnknownServerError",
    "MCPUnknownToolError",
    "OrchestrationPlanner",
    "OrchestrationService",
    "Orchestrator",
    "Pipeline",
    "PipelineService",
    "RAGError",
    "RAGRejected",
    "RAGService",
    "RAGUpstreamError",
    "RagCorpusLoader",
    "SUBMIT_GRACE",
    "ScheduleService",
    "SourceFetchError",
    "TaskExistsError",
    "TaskNotFoundError",
    "TaskScheduler",
    "TaskStateMachine",
    "apscheduler_bridge",
    "chunker",
    "compressor",
    "document_loader",
    "embedding_service",
    "fetch_json",
    "get_document_loader",
    "get_embedding_service",
    "get_index_service",
    "get_indexing_service",
    "get_mcp_registry",
    "get_orchestration_service",
    "get_pipeline_service",
    "get_rag_corpus_loader",
    "get_rag_service",
    "get_schedule_service",
    "get_scheduler",
    "index_service",
    "indexing_service",
    "invariant_checker",
    "make_checker_client",
    "mcp_client",
    "mcp_errors",
    "mcp_loop",
    "mcp_registry",
    "mcp_tool_runner",
    "mcp_transport",
    "pipeline",
    "pipeline_service",
    "rag_corpus_loader",
    "rag_service",
    "prepare",
    "schedule_service",
    "scheduled_jobs",
    "scheduler",
    "source_fetch",
    "task_state",
    "tick",
    "tool_names",
]
