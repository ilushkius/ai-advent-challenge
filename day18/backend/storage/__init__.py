"""Слой доступа к БД дня 18: движок, сессии, ORM-таблицы и их хранилища.

- ``database`` — движок и фабрика сессий из ``config.DATABASE_URL``, ``Base`` и
  реэкспорт ORM-классов пакета ``backend.models``; отсюда их импортирует
  остальной код дня;
- ``memory_rows`` — преобразования ORM-строк памяти в словари API/UI;
- ``task_store`` — ``TaskStateStore``: чтение/запись состояния задачи и журнала
  переходов;
- ``invariant_store`` — ``InvariantManager``: CRUD инвариантов проекта;
- ``scheduler_rows`` — ORM-строки планировщика в словари API/UI (день 18);
- ``scheduler_store`` — ``SchedulerStore``: задачи планировщика и журнал запусков;
- ``scheduler_data_store`` — ``SchedulerDataStore``: напоминания, накопленные
  записи, регулярные сводки и очередь уведомлений.
"""

from . import (
    database,
    invariant_store,
    memory_rows,
    scheduler_data_store,
    scheduler_rows,
    scheduler_store,
    task_store,
)
from .database import (
    AgentRecord,
    Base,
    Checkpoint,
    CollectedRecord,
    Fact,
    Invariant,
    LongTermMemory,
    PeriodicSummary,
    Reminder,
    ScheduledTask,
    SchedulerNotification,
    SchedulerTaskRun,
    SessionLocal,
    ShortTermMessage,
    Summary,
    TaskState,
    TaskTransition,
    TokenUsage,
    UserProfile,
    WorkingMemory,
    engine,
    init_db,
    make_engine,
    make_session_factory,
)
from .invariant_store import (
    InvariantExistsError,
    InvariantManager,
    InvariantNotFoundError,
)
from .memory_rows import _long_term_dict, _short_term_dict, _working_dict
from .scheduler_data_store import (
    NotificationNotFoundError,
    ReminderNotFoundError,
    SchedulerDataStore,
)
from .scheduler_rows import (
    as_utc,
    collected_dict,
    jsonable,
    notification_dict,
    reminder_dict,
    run_dict,
    summary_dict,
    task_dict,
)
from .scheduler_store import ScheduledTaskNotFoundError, SchedulerStore
from .task_store import TaskNotFoundError, TaskStateStore

__all__ = [
    "AgentRecord",
    "Base",
    "Checkpoint",
    "CollectedRecord",
    "Fact",
    "Invariant",
    "InvariantExistsError",
    "InvariantManager",
    "InvariantNotFoundError",
    "LongTermMemory",
    "NotificationNotFoundError",
    "PeriodicSummary",
    "Reminder",
    "ReminderNotFoundError",
    "ScheduledTask",
    "ScheduledTaskNotFoundError",
    "SchedulerDataStore",
    "SchedulerNotification",
    "SchedulerStore",
    "SchedulerTaskRun",
    "SessionLocal",
    "ShortTermMessage",
    "Summary",
    "TaskNotFoundError",
    "TaskState",
    "TaskStateStore",
    "TaskTransition",
    "TokenUsage",
    "UserProfile",
    "WorkingMemory",
    "_long_term_dict",
    "_short_term_dict",
    "_working_dict",
    "as_utc",
    "collected_dict",
    "database",
    "engine",
    "init_db",
    "invariant_store",
    "jsonable",
    "make_engine",
    "make_session_factory",
    "memory_rows",
    "notification_dict",
    "reminder_dict",
    "run_dict",
    "scheduler_data_store",
    "scheduler_rows",
    "scheduler_store",
    "summary_dict",
    "task_dict",
    "task_store",
]
