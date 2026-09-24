"""FastAPI-слой дня 18: роутеры по доменам и точка сборки приложения.

- ``agents`` / ``context`` / ``invariants`` / ``mcp`` / ``memory`` /
  ``pipelines`` / ``profiles`` / ``scheduler`` / ``tasks`` — роутеры API с
  абсолютными путями (префиксов нет);
- ``lifespan`` — старт и остановка фоновых служб (таблицы, агенты, планировщик,
  закрытие MCP);
- ``main`` — сборка ``app`` (FastAPI, CORS, lifespan, ``include_router``);
  запуск: ``uvicorn backend.api.main:app --port 8000``.

``main`` здесь НЕ импортируется: ``backend.core.dependencies.get_manager``
лениво тянет ``api.main`` изнутри функции, и ранний импорт создал бы цикл
(``api`` → ``core`` → ``api``).
"""

from . import (
    agents,
    context,
    invariants,
    lifespan,
    mcp,
    memory,
    pipelines,
    profiles,
    scheduler,
    tasks,
)

__all__ = [
    "agents",
    "context",
    "invariants",
    "lifespan",
    "mcp",
    "memory",
    "pipelines",
    "profiles",
    "scheduler",
    "tasks",
]
