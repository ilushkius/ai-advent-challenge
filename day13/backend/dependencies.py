"""Зависимости API-слоя дня 13: доступ к AgentManager и помощники роутов.

Менеджер резолвится через атрибут модуля ``backend.main`` В МОМЕНТ ВЫЗОВА:
тесты подменяют ровно одну точку — ``monkeypatch.setattr(main, "get_manager",
...)`` (см. tests/test_api.py, test_memory_api.py, test_profile_api.py,
test_strategy_api.py, test_task_api.py) — и подмену видят все роутеры без
правок тестов.
"""
from fastapi import HTTPException

from .agent_manager import AgentManager


def get_manager() -> AgentManager:
    """Менеджер агентов процесса (единственный инстанс)."""
    from . import main

    return main.get_manager()


def agent_or_404(agent_id: str):
    """Возвращает агента или бросает HTTPException(404) с понятным текстом."""
    agent = get_manager().get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Агент {agent_id} не найден")
    return agent


def task_or_404(task_id: str):
    """Возвращает состояние задачи или бросает HTTPException(404)."""
    state = get_manager().get_task_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
    return state
