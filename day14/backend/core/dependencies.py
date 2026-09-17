"""Зависимости API-слоя дня 14: доступ к AgentManager и помощники роутов.

Менеджер резолвится через атрибут модуля ``backend.api.main`` В МОМЕНТ ВЫЗОВА:
тесты подменяют ровно одну точку — ``monkeypatch.setattr(main, "get_manager",
...)`` (см. tests/e2e/test_api.py, test_memory_api.py, test_profile_api.py,
test_strategy_api.py, test_task_api.py) — и подмену видят все роутеры без
правок тестов.

Оба импорта менеджера отложены и нужны только для аннотаций: ``agents``
импортирует ``storage``, а тот — ``core``, поэтому жадный импорт ``agents``
здесь замыкал бы цикл «core -> agents -> core» при старте с ``import backend.core``.
"""
from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:  # только для аннотаций
    from ..agents.agent_manager import AgentManager


def get_manager() -> "AgentManager":
    """Менеджер агентов процесса (единственный инстанс)."""
    from ..api import main

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


def invariant_or_404(invariant_id: int) -> dict:
    """Возвращает инвариант или бросает HTTPException(404) с понятным текстом.

    Роутеры правки и удаления читают строку до операции: так 404 приходит с
    описанием «инвариант N не найден», а не как «False» из хранилища.
    """
    invariant = get_manager().get_invariant(invariant_id)
    if invariant is None:
        raise HTTPException(status_code=404, detail=f"Инвариант {invariant_id} не найден")
    return invariant
