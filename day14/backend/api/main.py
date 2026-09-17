"""FastAPI-приложение дня 14: агенты с памятью, состоянием задачи и инвариантами.

Запуск из папки day14/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с диалогом, слоями памяти и состоянием задачи.

День 14 добавляет **инварианты** — правила, которые агент не имеет права
нарушать: таблица ``invariants``, блок активных инвариантов в системном промпте
каждого запроса и проверка предложения (детерминированные правила, при
неоднозначности — вызов LLM, ``backend/services/invariant_checker.py``) с отказом
при нарушении hard-инварианта. Эндпоинты — в ``backend/api/invariants.py``.

Контракт ошибок:
- 404 — неизвестный agent_id/task_id/invariant_id;
- 400 — недопустимый переход состояния задачи;
- 409 — повторный task_id или имя инварианта;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации: тело {status:"error", messages: <текущий диалог>, ...}
  без traceback.

Здесь остаётся только сборка приложения: эндпоинты живут в ``backend/api/``
(agents, context, invariants, memory, profiles, tasks), а доступ к менеджеру
агентов — в ``backend/core/dependencies.py``.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.logging_utils import get_logger

from ..storage import database
from ..agents.agent_manager import get_manager
from . import agents, context, invariants, memory, profiles, tasks

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app):
    """Старт приложения: создание таблиц + восстановление агентов с историей."""
    database.init_db()
    get_manager().restore_from_db()
    logger.debug("Старт бэкенда: таблицы созданы, агенты восстановлены")
    yield


app = FastAPI(
    title="Агенты DeepSeek с инвариантами — День 14",
    description=(
        "FastAPI-бэкенд веб-приложения: три слоя памяти в SQLite, профиль "
        "пользователя, состояние задачи как конечный автомат и ИНВАРИАНТЫ — "
        "правила (таблица invariants), которые агент не имеет права нарушать: "
        "они встраиваются в системный промпт каждого запроса, а предложение "
        "проверяется детерминированными правилами и, при неоднозначности, "
        "вызовом LLM; нарушение hard-инварианта превращается в отказ. "
        "Эндпоинты инвариантов — /invariants и /invariants/check."
    ),
    version="8.0.0",
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
app.include_router(memory.router)
app.include_router(profiles.router)
app.include_router(tasks.router)
