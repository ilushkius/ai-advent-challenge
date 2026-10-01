"""
FastAPI-приложение дня 21: память, задача, инварианты, MCP-флот, планировщик,
пайплайн, оркестрация MCP-серверов, ИНДЕКСАЦИЯ документов, РАСХОДЫ на LLM и RAG.

Запуск из папки day21/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (``backend/api/lifespan.py``) создаются таблицы SQLite, агенты
восстанавливаются из базы, поднимается планировщик и ФЛОТ из трёх MCP-серверов
(``mcp_servers.json``), читаются оба индекса FAISS с диска, а модели эмбеддингов
и реранкера прогреваются в фоновом потоке; при остановке планировщик встаёт,
индексы пишутся на диск, а соединения флота и активное MCP-подключение закрываются.

Новое в дне 22 — режим RAG (``backend/api/rag.py``): поиск по корпусу документов,
ответ с контекстом и без него, сравнение двух ответов. День 23 добавил второй этап
отбора — переформулировку вопроса, кросс-энкодер и порог отсечения, а вместе с ним
сравнение режимов отбора (``POST /rag/compare_modes``, 4 эндпоинта). Роутеры дня 21
остаются на месте. Контракт ошибок приложения — в ``backend/api/__init__.py``.

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к
службам — в ``backend/core/dependencies.py``. Функции ``get_manager`` /
``get_mcp_registry`` / ``get_scheduler`` / ``get_schedule_service`` /
``get_pipeline_service`` / ``get_orchestration_service`` / ``get_indexing_service`` /
``get_index_service`` / ``get_embedding_service`` / ``get_llm_client`` /
``get_rag_service`` / ``get_rerank_service`` импортированы сюда как точки подмены
для тестов.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.agent_manager import get_manager
from ..core import config
from ..services.embedding_service import get_embedding_service
from ..services.index_service import get_index_service
from ..services.indexing_service import get_indexing_service
from ..services.llm_client import get_llm_client
from ..services.mcp_registry import get_mcp_registry
from ..services.orchestration_service import get_orchestration_service
from ..services.pipeline_service import get_pipeline_service
from ..services.rag_service import get_rag_service
from ..services.rerank_service import get_rerank_service
from ..services.schedule_service import get_schedule_service
from ..services.scheduler import get_scheduler
from . import (
    agents, context, indexing, invariants, llm, mcp, mcp_servers, memory,
    orchestration, pipelines, profiles, rag, scheduler, tasks,
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
app.include_router(indexing.router)
app.include_router(llm.router)
app.include_router(invariants.router)
app.include_router(mcp.router)
app.include_router(mcp_servers.router)
app.include_router(memory.router)
app.include_router(orchestration.router)
app.include_router(pipelines.router)
app.include_router(profiles.router)
app.include_router(rag.router)
app.include_router(scheduler.router)
app.include_router(tasks.router)
