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
  сервером, инструментом, входом, выходом и временем).

ORM-классы реэкспортируются через ``backend.storage.database`` (``Base``,
``AgentRecord``, ``ShortTermMessage``, ``Summary``, ``TokenUsage``, ``Fact``,
``WorkingMemory``, ``LongTermMemory``, ``Checkpoint``, ``UserProfile``,
``TaskState``, ``TaskTransition``, ``Invariant``, ``ScheduledTask``,
``SchedulerTaskRun``, ``Reminder``, ``SchedulerNotification``, ``CollectedRecord``,
``PeriodicSummary``, ``PipelineRun``, ``PipelineStep``, ``OrchestrationRun``,
``OrchestrationStep``), поэтому остальной код дня
импортирует их оттуда, а не отсюда. Импорт всех модулей пакета — он же и
регистрация таблиц в ``Base.metadata``, по которой ``init_db`` создаёт схему.

Pydantic-схемы API — отдельный пакет ``backend/schemas/``.
"""

from .agent import AgentRecord
from .context import Checkpoint, Fact, Summary, TokenUsage
from .invariant import Invariant
from .memory import LongTermMemory, WorkingMemory
from .message import ShortTermMessage
from .orchestration import OrchestrationRun, OrchestrationStep
from .pipeline import PipelineRun, PipelineStep
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
    "Fact",
    "Invariant",
    "LongTermMemory",
    "OrchestrationRun",
    "OrchestrationStep",
    "PeriodicSummary",
    "PipelineRun",
    "PipelineStep",
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
