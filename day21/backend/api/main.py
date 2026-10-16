"""
FastAPI-приложение дня 25: память, задача, инварианты, MCP-флот, планировщик, пайплайн,
оркестрация MCP-серверов, индексация документов, расходы на LLM, режим RAG, мини-чат,
удалённая LLM и ассистенты дней 31–34.

Запуск из папки day21/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (``backend/api/lifespan.py``) создаются таблицы SQLite, агенты восстанавливаются
из базы, поднимается планировщик и флот из трёх MCP-серверов (``mcp_servers.json``), читаются
оба индекса FAISS с диска, а модели эмбеддингов и реранкера прогреваются в фоновом потоке;
при остановке планировщик встаёт, индексы пишутся на диск, а соединения флота и MCP закрываются.

Дни 22–25 — режим RAG (``backend/api/rag.py``), последний день дал мини-чат
(``mini_chat.py``): поиск по корпусу, цитаты, режим «не знаю» и история сессий; день 30
(``remote_llm.py``) — удалённую LLM в Colab. Дни 31–35 поднимают СВОИ MCP-серверы вне
флота: ассистент разработчика (``dev_assistant.py``), AI-ревью PR (``code_review.py``),
поддержка по FAQ и тикетам (``support.py``) и ассистент файлов (``file_assistant.py``) —
цель пользователя превращается в план шагов, а шаги читают и меняют файлы папки дня;
день 35 (``release.py``) — подготовка релиза: теги, авто-версия, CHANGELOG и проверки.

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к службам — в
``backend/core/dependencies.py``; функции ``get_manager``, ``get_mcp_registry``, ``get_scheduler``,
``get_schedule_service``, ``get_pipeline_service``, ``get_orchestration_service``,
``get_indexing_service``, ``get_index_service``, ``get_embedding_service``, ``get_llm_client``,
``get_rag_service``, ``get_mini_chat_service``, ``get_dev_assistant_service``,
``get_code_review_service``, ``get_support_service``, ``get_file_assistant_service``,
``get_release_service`` и ``get_rerank_service`` импортированы сюда как точки подмены
для тестов.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.agent_manager import get_manager
from ..core import config
from ..services.code_review_service import get_code_review_service
from ..services.embedding_service import get_embedding_service
from ..services.dev_assistant_service import get_dev_assistant_service
from ..services.file_assistant_service import get_file_assistant_service
from ..services.index_service import get_index_service
from ..services.indexing_service import get_indexing_service
from ..services.llm_client import get_llm_client
from ..services.mcp_registry import get_mcp_registry
from ..services.mini_chat_service import get_mini_chat_service
from ..services.orchestration_service import get_orchestration_service
from ..services.pipeline_service import get_pipeline_service
from ..services.rag_service import get_rag_service
from ..services.release_service import get_release_service
from ..services.rerank_service import get_rerank_service
from ..services.schedule_service import get_schedule_service
from ..services.scheduler import get_scheduler
from ..services.support_service import get_support_service
from . import (
    agents, code_review, context, dev_assistant, file_assistant, indexing, invariants, llm,
    mcp, mcp_servers, memory, mini_chat, orchestration, pipelines, profiles, rag,
    release, remote_llm, scheduler, support, tasks,
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
for _router in (agents, code_review, context, dev_assistant, file_assistant, indexing,
                invariants, llm, mcp, mcp_servers, memory, mini_chat, orchestration,
                pipelines, profiles, rag, release, remote_llm, scheduler, support, tasks):
    app.include_router(_router.router)
