"""Зависимости API-слоя дня 18: доступ к фоновым службам и помощники роутов.

Менеджер агентов, реестр MCP, планировщик и службы дня резолвятся через атрибуты модуля
``backend.api.main`` В МОМЕНТ ВЫЗОВА: тесты подменяют ровно одну точку на службу —
``monkeypatch.setattr(main, "get_manager", ...)`` (см. tests/e2e/test_api.py,
test_memory_api.py, test_profile_api.py, test_strategy_api.py, test_task_api.py) или
``main.get_scheduler`` / ``main.get_mcp_registry`` (tests/e2e) — и подмену видят
все роутеры вместе с ``lifespan`` без правок тестов.

Импорты служб отложены и нужны только для аннотаций: ``agents`` импортирует
``storage``, а тот — ``core``, поэтому жадный импорт ``agents`` здесь замыкал бы
цикл «core -> agents -> core» при старте с ``import backend.core``.
"""
from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:  # только для аннотаций
    from ..agents.agent_manager import AgentManager
    from ..services.mcp_registry import MCPRegistry
    from ..services.schedule_service import ScheduleService
    from ..services.orchestration_service import OrchestrationService
    from ..services.pipeline_service import PipelineService
    from ..services.scheduler import TaskScheduler


def get_manager() -> "AgentManager":
    """Менеджер агентов процесса (единственный инстанс)."""
    from ..api import main

    return main.get_manager()


def get_mcp_registry() -> "MCPRegistry":
    """Реестр MCP-подключения процесса (единственный инстанс).

    Та же точка подмены, что у менеджера: тесты подменяют
    ``monkeypatch.setattr(main, "get_mcp_registry", ...)`` один раз, и подмену
    видят все роутеры MCP — с фейковой фабрикой клиента настоящий MCP-сервер в
    тестах не поднимается.
    """
    from ..api import main

    return main.get_mcp_registry()


def get_scheduler() -> "TaskScheduler":
    """Планировщик фоновых задач процесса (единственный инстанс, день 18).

    Им пользуются и ``lifespan`` (старт и остановка), и роутер ``/scheduler``.
    Тесты подменяют ``main.get_scheduler`` заглушкой без таймеров, поэтому e2e
    не зависит от реального времени.
    """
    from ..api import main

    return main.get_scheduler()


def get_schedule_service() -> "ScheduleService":
    """Сервис расписаний процесса: создание задач и чтение данных планировщика."""
    from ..api import main

    return main.get_schedule_service()


def get_pipeline_service() -> "PipelineService":
    """Служба пайплайнов процесса (день 19): запуск и история прогонов.

    Та же точка подмены, что у остальных служб: тесты подменяют
    ``monkeypatch.setattr(main, "get_pipeline_service", ...)``, и подмену видят и
    роутер ``/pipelines``, и агент (через свой шаг пайплайна).
    """
    from ..api import main

    return main.get_pipeline_service()


def get_orchestration_service() -> "OrchestrationService":
    """Служба оркестрации процесса (день 20): запуск прогонов и история.

    Та же точка подмены, что у остальных служб: тесты подменяют
    ``monkeypatch.setattr(main, "get_orchestration_service", ...)``, и подмену видят
    и роутер ``/orchestration``, и агент (через свой шаг оркестрации).
    """
    from ..api import main

    return main.get_orchestration_service()


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
