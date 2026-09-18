"""Движок, сессии и начальная схема БД дня 15 (SQLAlchemy/SQLite).

ORM-таблицы дня описаны в ``backend/models/*.py`` (``agent``, ``message``,
``memory``, ``context``, ``user_profile``, ``task_state``, ``invariant``) и
реэкспортируются отсюда (``Base``, ``AgentRecord``, ``ShortTermMessage``,
``Summary``, ``TokenUsage``, ``Fact``, ``WorkingMemory``, ``LongTermMemory``,
``Checkpoint``, ``UserProfile``, ``TaskState``, ``TaskTransition``,
``Invariant``), поэтому остальной код дня по-прежнему импортирует их из
``backend.storage.database``.

Импорт моделей здесь не только для реэкспорта: он регистрирует их таблицы в
metadata ``Base``, поэтому ``init_db`` создаёт всю схему.

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

from ..core import config
from ..models.agent import AgentRecord
from ..models.context import Checkpoint, Fact, Summary, TokenUsage
from ..models.invariant import Invariant
from ..models.memory import LongTermMemory, WorkingMemory
from ..models.message import ShortTermMessage
from ..models.task_state import TaskState, TaskTransition
from ..models.user_profile import UserProfile

# Движок и фабрика сессий приложения (база day15/agents.db, см. config).
engine = make_engine(config.DATABASE_URL)
SessionLocal = make_session_factory(engine)


def init_db(engine_: Optional[Engine] = None) -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте бэкенда."""
    create_tables(engine_ or engine)
