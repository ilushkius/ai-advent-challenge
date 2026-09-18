"""SQLAlchemy-модели дня 15, разложенные по доменам.

Модули:

- ``agent.py`` — ``agents`` (AgentRecord): конфигурация агента и его связи;
- ``message.py`` — ``short_term_messages`` (ShortTermMessage): диалог сессии;
- ``memory.py`` — ``working_memory`` / ``long_term_memory``: рабочая и
  долговременная память;
- ``context.py`` — ``summaries`` / ``token_usage`` / ``facts`` / ``checkpoints``:
  конспекты, метрики, факты и ветки;
- ``user_profile.py`` — ``user_profiles`` (UserProfile): персонализация;
- ``task_state.py`` — ``task_states`` / ``task_transitions``: состояние задачи;
- ``invariant.py`` — ``invariants`` (Invariant): правила проекта (день 14).

ORM-классы реэкспортируются через ``backend.storage.database`` (``Base``,
``AgentRecord``, ``ShortTermMessage``, ``Summary``, ``TokenUsage``, ``Fact``,
``WorkingMemory``, ``LongTermMemory``, ``Checkpoint``, ``UserProfile``,
``TaskState``, ``TaskTransition``, ``Invariant``), поэтому остальной код дня
импортирует их оттуда, а не отсюда. Импорт всех модулей пакета — он же и
регистрация таблиц в ``Base.metadata``, по которой ``init_db`` создаёт схему.

Pydantic-схемы API — отдельный пакет ``backend/schemas/``.
"""

from .agent import AgentRecord
from .context import Checkpoint, Fact, Summary, TokenUsage
from .invariant import Invariant
from .memory import LongTermMemory, WorkingMemory
from .message import ShortTermMessage
from .task_state import TaskState, TaskTransition
from .user_profile import UserProfile

__all__ = [
    "AgentRecord",
    "Checkpoint",
    "Fact",
    "Invariant",
    "LongTermMemory",
    "ShortTermMessage",
    "Summary",
    "TaskState",
    "TaskTransition",
    "TokenUsage",
    "UserProfile",
    "WorkingMemory",
]
