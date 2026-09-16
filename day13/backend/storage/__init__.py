"""Слой доступа к БД дня 13: движок, сессии, ORM-таблицы и их хранилища.

- ``database`` — движок и фабрика сессий из ``config.DATABASE_URL``, ``Base`` и
  реэкспорт ORM-классов пакета ``backend.models``; отсюда их импортирует
  остальной код дня;
- ``memory_rows`` — преобразования ORM-строк памяти в словари API/UI;
- ``task_store`` — ``TaskStateStore``: чтение/запись состояния задачи и журнала
  переходов.
"""

from . import database, memory_rows, task_store
from .database import (
    AgentRecord,
    Base,
    Checkpoint,
    Fact,
    LongTermMemory,
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
from .memory_rows import _long_term_dict, _short_term_dict, _working_dict
from .task_store import TaskNotFoundError, TaskStateStore

__all__ = [
    "AgentRecord",
    "Base",
    "Checkpoint",
    "Fact",
    "LongTermMemory",
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
    "database",
    "engine",
    "init_db",
    "make_engine",
    "make_session_factory",
    "memory_rows",
    "task_store",
]
