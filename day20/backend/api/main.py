"""
FastAPI-приложение дня 20: память, задача, инварианты, MCP-флот, планировщик,
пайплайн и оркестрация MCP-серверов.

Запуск из папки day20/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (``backend/api/lifespan.py``) создаются таблицы SQLite, агенты
восстанавливаются из базы, поднимается планировщик и ФЛОТ из трёх MCP-серверов
(``mcp_servers.json``); при остановке планировщик встаёт, а соединения флота и
активное MCP-подключение закрываются.

Новое в дне 20 — оркестрация (``backend/api/orchestration.py``, 6 эндпоинтов) и
каталог флота (``backend/api/mcp_servers.py``, 3 эндпоинта); пайплайн дня 19 и
планировщик дня 18 остаются на месте. Контракт ошибок приложения — в
``backend/api/__init__.py``.

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к
службам — в ``backend/core/dependencies.py``. Функции ``get_manager`` /
``get_mcp_registry`` / ``get_scheduler`` / ``get_schedule_service`` /
``get_pipeline_service`` / ``get_orchestration_service`` импортированы сюда как
точки подмены для тестов.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.agent_manager import get_manager
from ..core import config
from ..services.mcp_registry import get_mcp_registry
from ..services.orchestration_service import get_orchestration_service
from ..services.pipeline_service import get_pipeline_service
from ..services.schedule_service import get_schedule_service
from ..services.scheduler import get_scheduler
from . import (
    agents, context, invariants, mcp, mcp_servers, memory, orchestration, pipelines,
    profiles, scheduler, tasks,
)
from .lifespan import lifespan

app = FastAPI(
    title=config.API_TITLE,
    description=config.API_DESCRIPTION,
    version=config.API_VERSION,
    lifespan=lifespan,
)

# CORS для браузерных клиентов Streamlit (серверный `requests` CORS не требует).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Пути в роутерах абсолютные (префиксов нет).
app.include_router(agents.router)
app.include_router(context.router)
app.include_router(invariants.router)
app.include_router(mcp.router)
app.include_router(mcp_servers.router)
app.include_router(memory.router)
app.include_router(orchestration.router)
app.include_router(pipelines.router)
app.include_router(profiles.router)
app.include_router(scheduler.router)
app.include_router(tasks.router)
