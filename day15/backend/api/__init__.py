"""FastAPI-слой дня 15: роутеры по доменам и точка сборки приложения.

- ``agents`` / ``context`` / ``invariants`` / ``memory`` / ``profiles`` /
  ``tasks`` — роутеры API с абсолютными путями (префиксов нет);
- ``main`` — сборка ``app`` (FastAPI, CORS, lifespan, ``include_router``);
  запуск: ``uvicorn backend.api.main:app --port 8000``.

``main`` здесь НЕ импортируется: ``backend.core.dependencies.get_manager``
лениво тянет ``api.main`` изнутри функции, и ранний импорт создал бы цикл
(``api`` → ``core`` → ``api``).
"""

from . import agents, context, invariants, memory, profiles, tasks

__all__ = ["agents", "context", "invariants", "memory", "profiles", "tasks"]
