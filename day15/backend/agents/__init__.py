"""Слой агентов дня 15: агент, его память, профиль, состояние задачи и менеджер пула.

- ``agent`` — класс ``Agent`` (память, токены, контекст, стратегии, факты,
  ветки, профиль, состояние задачи, инварианты);
- ``memory`` — ``MemoryManager``: хранение трёх слоёв памяти;
- ``profile_store`` — чтение/запись профиля пользователя в SQLite;
- ``agent_manager`` — ``AgentManager`` (синглтон, пул, стратегии, ветки);
- ``manager_agents`` / ``manager_context`` / ``manager_invariants`` /
  ``manager_memory`` / ``manager_profiles`` / ``manager_tasks`` /
  ``manager_usage`` — миксины ``AgentManager`` по доменам.
"""

from . import agent, agent_manager, memory, profile_store
from .agent import Agent, AgentError, MemoryContext, PayloadPlan
from .agent_manager import AgentManager, get_manager
from .manager_agents import AgentNotFoundError, AgentPoolMixin
from .manager_context import ContextOpsMixin
from .manager_invariants import InvariantOpsMixin
from .manager_memory import MemoryOpsMixin
from .manager_profiles import ProfileOpsMixin
from .manager_tasks import TaskOpsMixin
from .manager_usage import UsageOpsMixin
from .memory import MemoryManager
from .profile_store import (
    ProfileData,
    ProfileExistsError,
    ProfileNotFoundError,
    ProfileStore,
    empty_profile,
)

__all__ = [
    "Agent",
    "AgentError",
    "AgentManager",
    "AgentNotFoundError",
    "AgentPoolMixin",
    "ContextOpsMixin",
    "InvariantOpsMixin",
    "MemoryContext",
    "MemoryManager",
    "MemoryOpsMixin",
    "PayloadPlan",
    "ProfileData",
    "ProfileExistsError",
    "ProfileNotFoundError",
    "ProfileOpsMixin",
    "ProfileStore",
    "TaskOpsMixin",
    "UsageOpsMixin",
    "agent",
    "agent_manager",
    "empty_profile",
    "get_manager",
    "memory",
    "profile_store",
]
