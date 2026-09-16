"""Движок, сессии и начальная схема БД дня 13 (SQLAlchemy/SQLite).

ORM-таблицы дня описаны в ``backend/tables.py`` (агенты, память, профили) и
``backend/tables_task.py`` (состояние задачи) и реэкспортируются отсюда
(``Base``, ``AgentRecord``, ``ShortTermMessage``, ``Summary``, ``TokenUsage``,
``Fact``, ``WorkingMemory``, ``LongTermMemory``, ``Checkpoint``, ``UserProfile``,
``TaskState``, ``TaskTransition``), поэтому остальной код дня по-прежнему
импортирует их из ``backend.database``.

Импорт ``tables_task`` здесь не только для реэкспорта: он регистрирует таблицы
состояния задачи в metadata ``Base``, поэтому ``init_db`` создаёт и их.

Движок и фабрика сессий создаются из ``config.DATABASE_URL`` общими помощниками
``shared/db_base.py`` (``make_engine`` / ``init_db`` / ``make_session_factory``).
Для офлайн-проверок (временный файл/in-memory) используется ``make_engine(url)``
+ ``init_db(engine)`` + своя sessionmaker — фабрика передаётся в Agent/AgentManager.
"""
from typing import Optional

from sqlalchemy.engine import Engine

from shared.db_base import (
    Base,
    init_db as create_tables,
    make_engine,
    make_session_factory,
)

from . import config
from .tables import (
    AgentRecord, Checkpoint, Fact, LongTermMemory, ShortTermMessage, Summary,
    TokenUsage, UserProfile, WorkingMemory,
)
from .tables_task import TaskState, TaskTransition


# Движок и фабрика сессий приложения (база day13/agents.db, см. config).
engine = make_engine(config.DATABASE_URL)
SessionLocal = make_session_factory(engine)


def init_db(engine_: Optional[Engine] = None) -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте бэкенда."""
    create_tables(engine_ or engine)
