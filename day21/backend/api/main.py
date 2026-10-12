"""
FastAPI-приложение дня 25: память, задача, инварианты, MCP-флот, планировщик, пайплайн,
оркестрация MCP-серверов, индексация документов, расходы на LLM, режим RAG, мини-чат и
удалённая LLM.

Запуск из папки day21/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (``backend/api/lifespan.py``) создаются таблицы SQLite, агенты восстанавливаются
из базы, поднимается планировщик и флот из трёх MCP-серверов (``mcp_servers.json``), читаются
оба индекса FAISS с диска, а модели эмбеддингов и реранкера прогреваются в фоновом потоке;
при остановке планировщик встаёт, индексы пишутся на диск, а соединения флота и MCP закрываются.

Дни 22–24 — режим RAG (``backend/api/rag.py``): поиск по корпусу, ответ с контекстом и без него,
сравнение ответов и режимов отбора, кросс-энкодер с порогом отсечения, обязательные источники
и цитаты, проверка опоры и режим «не знаю». День 25 дал мини-чат (``backend/api/mini_chat.py``):
сессии, ответ с источниками, история; день 30 (``backend/api/remote_llm.py``) — удалённую LLM;
день 31 (``backend/api/dev_assistant.py``) — ассистента разработчика: вопрос ``/help`` отвечает
по документации проекта (RAG) и состоянию репозитория (свой MCP-сервер ``dev_server``).

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к службам — в
``backend/core/dependencies.py``; функции ``get_manager``, ``get_mcp_registry``, ``get_scheduler``,
``get_schedule_service``, ``get_pipeline_service``, ``get_orchestration_service``,
``get_indexing_service``, ``get_index_service``, ``get_embedding_service``, ``get_llm_client``,
``get_rag_service``, ``get_mini_chat_service``, ``get_dev_assistant_service`` и
``get_rerank_service`` импортированы сюда как точки подмены для тестов.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.agent_manager import get_manager
from ..core import config
from ..services.embedding_service import get_embedding_service
from ..services.dev_assistant_service import get_dev_assistant_service
from ..services.index_service import get_index_service
from ..services.indexing_service import get_indexing_service
from ..services.llm_client import get_llm_client
from ..services.mcp_registry import get_mcp_registry
from ..services.mini_chat_service import get_mini_chat_service
from ..services.orchestration_service import get_orchestration_service
from ..services.pipeline_service import get_pipeline_service
from ..services.rag_service import get_rag_service
from ..services.rerank_service import get_rerank_service
from ..services.schedule_service import get_schedule_service
from ..services.scheduler import get_scheduler
from . import (
    agents, context, dev_assistant, indexing, invariants, llm, mcp, mcp_servers,
    memory, mini_chat, orchestration, pipelines, profiles, rag, remote_llm,
    scheduler, tasks,
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

# Пути в роутерах абсолютные (префиксов нет); порядок списка = порядок регистрации.
for _router in (agents, context, dev_assistant, indexing, invariants, llm, mcp,
                mcp_servers, memory, mini_chat, orchestration, pipelines, profiles,
                rag, remote_llm, scheduler, tasks):
    app.include_router(_router.router)
