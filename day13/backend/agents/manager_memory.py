"""Миксин трёх слоёв памяти (день 11): сессия, задача и CRUD по слоям.

Часть ``AgentManager`` (``backend/agent_manager.py``): тонкие обёртки над
``Agent``/``MemoryManager`` для API-слоя.
"""
from typing import Optional

from .memory import AVAILABLE_CATEGORIES


class MemoryOpsMixin:
    """Сессия, активная задача и CRUD трёх слоёв памяти."""

    # --- слои памяти (день 11) ---
    def new_session(self, agent_id: str) -> dict:
        """Начинает новую сессию агента (краткосрочный слой старой очищается)."""
        return self.require_agent(agent_id).new_session()

    def set_task(self, agent_id: str, task_id: str) -> dict:
        """Переключает активную задачу агента (рабочая память фильтруется)."""
        return self.require_agent(agent_id).set_task(task_id)

    def get_memory_state(self, agent_id: str) -> dict:
        """Сводка трёх слоёв: сессия, задача, счётчики и токены по слоям."""
        return self.require_agent(agent_id).memory_state()

    def add_short_term(self, agent_id: str, role: str, content: str) -> dict:
        """Добавляет реплику в краткосрочный слой текущей сессии."""
        return self.require_agent(agent_id).add_short_term(role, content)

    def get_short_term(self, agent_id: str, session_id: Optional[str] = None,
                       limit: Optional[int] = None) -> dict:
        """Реплики краткосрочного слоя сессии (по умолчанию — текущей)."""
        agent = self.require_agent(agent_id)
        target = session_id or agent.session_id
        return {
            "agent_id": agent_id,
            "session_id": target,
            "messages": agent.short_term_rows(target, limit=limit),
        }

    def clear_short_term(self, agent_id: str,
                         session_id: Optional[str] = None) -> dict:
        """Очищает краткосрочный слой сессии; возвращает число удалённых реплик."""
        agent = self.require_agent(agent_id)
        target = session_id or agent.session_id
        return {
            "agent_id": agent_id,
            "session_id": target,
            "deleted": agent.clear_short_term(target),
        }

    def add_working(self, agent_id: str, key: str, value: str,
                    task_id: Optional[str] = None) -> dict:
        """Upsert записи рабочей памяти (по умолчанию — активной задачи)."""
        return self.require_agent(agent_id).add_working(key, value, task_id=task_id)

    def get_working(self, agent_id: str, task_id: Optional[str] = None) -> dict:
        """Записи рабочей памяти задачи + список задач агента (для UI)."""
        agent = self.require_agent(agent_id)
        target = task_id or agent.task_id
        return {
            "agent_id": agent_id,
            "task_id": target,
            "entries": agent.working_rows(target),
            "tasks": agent.memory.list_tasks(agent_id),
        }

    def add_long_term(self, agent_id: str, category: str, key: str, value: str,
                      confidence: float = 1.0) -> dict:
        """Upsert записи долговременной памяти."""
        return self.require_agent(agent_id).add_long_term(
            category, key, value, confidence=confidence
        )

    def get_long_term(self, agent_id: str, category: Optional[str] = None) -> dict:
        """Записи долговременной памяти + список категорий (для UI)."""
        agent = self.require_agent(agent_id)
        return {
            "agent_id": agent_id,
            "category": category,
            "entries": agent.long_term_rows(category),
            "categories": list(AVAILABLE_CATEGORIES),
        }

    def delete_long_term(self, agent_id: str, entry_id: int) -> bool:
        """Удаляет запись долговременной памяти (False — записи не было)."""
        return self.require_agent(agent_id).delete_long_term(entry_id)
