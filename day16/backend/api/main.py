"""FastAPI-приложение дня 16: память, задача, инварианты, переходы и MCP.

Запуск из папки day16/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с диалогом, слоями памяти и состоянием задачи; при остановке
закрывается MCP-подключение — иначе сервер-stdio остался бы висеть процессом.

День 16 добавляет **MCP-клиент** (``backend/api/mcp.py``): подключение к
внешнему MCP-серверу (stdio, SSE или Streamable HTTP) и список его инструментов —
эндпоинты ``/mcp/connect``, ``/mcp/disconnect``, ``/mcp/status``, ``/mcp/tools``.
День 15 добавил контролируемые переходы состояния задачи, день 14 — инварианты.

Контракт ошибок:
- 404 — неизвестный agent_id/task_id/invariant_id;
- 400 — недопустимый переход задачи или неразобранная цель MCP-подключения;
- 409 — повторный task_id/имя инварианта, запрос инструментов без соединения;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации или недоступный MCP-сервер: тело без traceback.

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к
менеджеру агентов и MCP-реестру — в ``backend/core/dependencies.py``.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging_utils import get_logger

from ..agents.agent_manager import get_manager
from ..services.mcp_registry import get_mcp_registry
from ..storage import database
from . import agents, context, invariants, mcp, memory, profiles, tasks

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app):
    """Старт: таблицы и агенты из базы; остановка: закрытие MCP-подключения."""
    database.init_db()
    get_manager().restore_from_db()
    logger.debug("Старт бэкенда: таблицы созданы, агенты восстановлены")
    yield
    get_mcp_registry().close()


app = FastAPI(
    title="Агенты DeepSeek + MCP — День 16",
    description=(
        "FastAPI-бэкенд веб-приложения: три слоя памяти в SQLite, профиль "
        "пользователя, состояние задачи с КОНТРОЛИРУЕМЫМИ ПЕРЕХОДАМИ, "
        "ИНВАРИАНТЫ (таблица invariants) и MCP-КЛИЕНТ: подключение к внешнему "
        "MCP-серверу (/mcp/connect, /mcp/disconnect, /mcp/status) и каталог его "
        "инструментов (/mcp/tools: name, description, input_schema)."
    ),
    version="10.0.0",
    lifespan=_lifespan,
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
app.include_router(memory.router)
app.include_router(profiles.router)
app.include_router(tasks.router)
