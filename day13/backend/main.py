"""FastAPI-приложение дня 13: агенты DeepSeek с состоянием задачи и памятью.

Запуск из папки day13/:  uvicorn backend.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с диалогом, слоями памяти и состоянием задачи.

Что появилось в дне 13 — **состояние задачи** как конечный автомат: этапы
planning → execution → validation → done, шаги внутри этапа, ожидаемое действие
и пауза с продолжением с того же места. Состояние живёт в таблицах task_states
и task_transitions, подключается блоком к системному промпту КАЖДОГО запроса
(агенту не нужно объяснять, где он остановился) и обновляется по реплике
пользователя. Эндпоинты — в ``backend/routers/tasks.py``.

Контракт ошибок:
- 404 — неизвестный agent_id/task_id;
- 400 — недопустимый переход состояния задачи;
- 409 — повторный task_id;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации: тело {status:"error", messages: <текущий диалог>, ...}
  без traceback.

Здесь остаётся только сборка приложения: эндпоинты живут в ``backend/routers/``
(agents, context, memory, profiles, tasks), а доступ к менеджеру агентов — в
``backend/dependencies.py``.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging_utils import get_logger

from . import database
from .agent_manager import get_manager
from .routers import agents, context, memory, profiles, tasks

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app):
    """Старт приложения: создание таблиц + восстановление агентов с историей."""
    database.init_db()
    get_manager().restore_from_db()
    logger.debug("Старт бэкенда: таблицы созданы, агенты восстановлены")
    yield


app = FastAPI(
    title="Агенты DeepSeek с состоянием задачи — День 13",
    description=(
        "FastAPI-бэкенд веб-приложения: у каждого агента три слоя памяти в "
        "SQLite (short_term_messages — сессия, working_memory — задача, "
        "long_term_memory — профиль/предпочтения/решения/знания), профиль "
        "пользователя (user_profiles) и СОСТОЯНИЕ ЗАДАЧИ как конечный автомат "
        "(task_states/task_transitions: этапы planning → execution → validation "
        "→ done, шаги внутри этапа, пауза и продолжение с того же места). "
        "Эндпоинты состояния задачи — /agents/{agent_id}/tasks и "
        "/tasks/{task_id}/...; контекст собирает одна из четырёх стратегий."
    ),
    version="7.0.0",
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
app.include_router(tasks.router)
