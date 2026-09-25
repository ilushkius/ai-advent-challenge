"""FastAPI-слой дня 18: роутеры по доменам и точка сборки приложения.

- ``agents`` / ``context`` / ``invariants`` / ``mcp`` / ``mcp_servers`` /
  ``memory`` / ``orchestration`` / ``pipelines`` / ``profiles`` / ``scheduler`` /
  ``tasks`` — роутеры API с абсолютными путями (префиксов нет);
- ``lifespan`` — старт и остановка фоновых служб (таблицы, агенты, планировщик,
  флот MCP-серверов, закрытие соединений);
- ``main`` — сборка ``app`` (FastAPI, CORS, lifespan, ``include_router``);
  запуск: ``uvicorn backend.api.main:app --port 8000``.

Контракт ошибок приложения (коды ответов, которые возвращают роутеры):

- 404 — неизвестный agent_id/task_id/invariant_id, номер задачи планировщика,
  номер запуска пайплайна или оркестрации, неизвестный сервер флота;
- 400 — недопустимый переход задачи, неразобранная цель MCP, негодные аргументы
  инструмента планировщика, конфигурация пайплайна, план оркестрации или статус в
  фильтре запусков;
- 409 — повторный task_id/имя инварианта, обращение к инструментам без соединения,
  пауза не активной задачи и возобновление не стоящей на паузе;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации, недоступный MCP-сервер или оборвавшийся вызов.

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
    mcp_servers,
    memory,
    orchestration,
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
    "mcp_servers",
    "memory",
    "orchestration",
    "pipelines",
    "profiles",
    "scheduler",
    "tasks",
]
