"""FastAPI-приложение дня 12: агенты DeepSeek с тремя слоями памяти и профилем.

Запуск из папки day12/:  .venv/Scripts/python -m uvicorn backend.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с диалогом активной сессии, рабочей и долговременной памятью.
День 12 добавляет персонализацию:

- профиль пользователя в таблице ``user_profiles`` (preferences, constraints,
  custom_instructions) и CRUD ``/users``, ``/users/{user_id}/profile``;
- агент создаётся с ``user_id`` (PATCH /agents/{id} переключает пользователя);
- POST /agents/{agent_id}/generate возвращает ``profile`` (какие элементы
  профиля применены и что они добавили) и ``system_prompt`` (итоговое
  системное сообщение запроса);
- GET /agents/{agent_id}/profile — профиль агента и его вклад в промпт.

Слои памяти дня 11 остаются: POST /agents/{id}/memory/session,
PUT /agents/{id}/memory/task и CRUD по /memory/short-term, /memory/working,
/memory/long-term.

Контракт ошибок (как в день 6):
- 404 — неизвестный agent_id (и запись долговременной памяти у DELETE);
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации: тело {status:"error", messages: <текущий диалог>, ...}
  без traceback.

Здесь остаётся только сборка приложения: эндпоинты живут в ``backend/routers/``
(agents, context, memory, profiles), а доступ к менеджеру агентов — в
``backend/dependencies.py``.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging_utils import get_logger

from . import database
from .agent_manager import get_manager
from .routers import agents, context, memory, profiles

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app):
    """Старт приложения: создание таблиц + восстановление агентов с историей."""
    database.init_db()
    get_manager().restore_from_db()
    logger.debug("Старт бэкенда: таблицы созданы, агенты восстановлены")
    yield


app = FastAPI(
    title="Агенты DeepSeek с профилем пользователя — День 12",
    description=(
        "FastAPI-бэкенд веб-приложения: у каждого агента три явных слоя памяти "
        "в SQLite — краткосрочная (short_term_messages, привязана к сессии), "
        "рабочая (working_memory, привязана к задаче) и долговременная "
        "(long_term_memory: profile/preference/decision/knowledge), а к "
        "системному промпту КАЖДОГО запроса подключается профиль пользователя "
        "(user_profiles: tone/verbosity/language/format, ограничения и "
        "произвольные инструкции). Контекст для DeepSeek собирает одна из "
        "четырёх стратегий дня 11: sliding_window, sticky_facts, branching или "
        "summary (сжатие дня 9)."
    ),
    version="6.0.0",
    lifespan=_lifespan,
)

# CORS для браузерных клиентов Streamlit (серверный `requests` CORS не требует).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Пути в роутерах абсолютные (префиксов нет) — набор эндпоинтов как был.
app.include_router(agents.router)
app.include_router(context.router)
app.include_router(memory.router)
app.include_router(profiles.router)
