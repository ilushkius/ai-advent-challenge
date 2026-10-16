"""SQLAlchemy-модели дня 19, разложенные по доменам.

Модули:

- ``agent.py`` — ``agents`` (AgentRecord): конфигурация агента и его связи;
- ``message.py`` — ``short_term_messages`` (ShortTermMessage): диалог сессии;
- ``memory.py`` — ``working_memory`` / ``long_term_memory``: рабочая и
  долговременная память;
- ``context.py`` — ``summaries`` / ``token_usage`` / ``facts`` / ``checkpoints``:
  конспекты, метрики, факты и ветки;
- ``user_profile.py`` — ``user_profiles`` (UserProfile): персонализация;
- ``task_state.py`` — ``task_states`` / ``task_transitions``: состояние задачи;
- ``invariant.py`` — ``invariants`` (Invariant): правила проекта (день 14);
- ``scheduler.py`` — таблицы планировщика дня 18: ``scheduled_tasks``,
  ``task_runs``, ``reminders``, ``notifications``, ``collected_data``,
  ``periodic_summaries``;
- ``pipeline.py`` — таблицы пайплайна дня 19: ``pipeline_runs`` (запуск) и
  ``pipeline_steps`` (шаг прогона с входом, выходом и временем);
- ``orchestration.py`` — таблицы оркестрации дня 20: ``orchestration_runs``
  (запуск с планом и списком серверов) и ``orchestration_steps`` (шаг прогона с
  сервером, инструментом, входом, выходом и временем);
- ``indexing.py`` — таблицы индексации дня 21: ``document_chunks`` (чанк с
  метаданными, текстом и id вектора в FAISS) и ``index_runs`` (запуск с этапом,
  счётчиками, метриками сравнения стратегий и ошибкой);
- ``llm_usage.py`` — журнал расходов дня 21: ``llm_usage`` (запрос к модели с
  токенами, разметкой кэша, оценкой стоимости и типом задачи);
- ``file_assistant.py`` — таблица дня 34: ``file_assistant_runs`` (цель, план шагов,
  журнал выполненных шагов, прочитанные/изменённые/созданные файлы, diff, статус);
- ``release.py`` — таблица дня 35: ``release_runs`` (диапазон тегов, версия с причиной
  выбора, тексты раздела CHANGELOG и заметок о релизе, признак пройденных проверок,
  записанные файлы, статус).

ORM-классы реэкспортируются через ``backend.storage.database`` (``Base``,
``AgentRecord``, ``ShortTermMessage``, ``Summary``, ``TokenUsage``, ``Fact``,
``WorkingMemory``, ``LongTermMemory``, ``Checkpoint``, ``UserProfile``,
``TaskState``, ``TaskTransition``, ``Invariant``, ``ScheduledTask``,
``SchedulerTaskRun``, ``Reminder``, ``SchedulerNotification``, ``CollectedRecord``,
``PeriodicSummary``, ``PipelineRun``, ``PipelineStep``, ``OrchestrationRun``,
``OrchestrationStep``, ``LLMUsage``, ``FileAssistantRun``, ``ReleaseRun``), поэтому
остальной код дня
импортирует их оттуда, а не отсюда. Импорт всех модулей пакета — он же и
регистрация таблиц в ``Base.metadata``, по которой ``init_db`` создаёт схему.

Pydantic-схемы API — отдельный пакет ``backend/schemas/``.
"""

from .agent import AgentRecord
from .context import Checkpoint, Fact, Summary, TokenUsage
from .file_assistant import FileAssistantRun
from .indexing import DocumentChunk, IndexRun
from .invariant import Invariant
from .llm_usage import LLMUsage
from .memory import LongTermMemory, WorkingMemory
from .message import ShortTermMessage
from .orchestration import OrchestrationRun, OrchestrationStep
from .pipeline import PipelineRun, PipelineStep
from .release import ReleaseRun
from .scheduler import (
    CollectedRecord,
    PeriodicSummary,
    Reminder,
    ScheduledTask,
    SchedulerNotification,
    SchedulerTaskRun,
)
from .task_state import TaskState, TaskTransition
from .user_profile import UserProfile

__all__ = [
    "AgentRecord",
    "Checkpoint",
    "CollectedRecord",
    "DocumentChunk",
    "Fact",
    "FileAssistantRun",
    "IndexRun",
    "Invariant",
    "LLMUsage",
    "LongTermMemory",
    "OrchestrationRun",
    "OrchestrationStep",
    "PeriodicSummary",
    "PipelineRun",
    "PipelineStep",
    "ReleaseRun",
    "Reminder",
    "ScheduledTask",
    "SchedulerNotification",
    "SchedulerTaskRun",
    "ShortTermMessage",
    "Summary",
    "TaskState",
    "TaskTransition",
    "TokenUsage",
    "UserProfile",
    "WorkingMemory",
]
