"""FastAPI-приложение дня 18: память, задача, инварианты, MCP и планировщик.

Запуск из папки day18/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (``backend/api/lifespan.py``) создаются таблицы SQLite, агенты
восстанавливаются из базы и поднимается планировщик фоновых задач; при остановке
планировщик встаёт, а MCP-подключение закрывается.

День 18 добавляет **планировщик фоновых задач** (``backend/api/scheduler.py``,
14 эндпоинтов): три MCP-инструмента с отложенным и периодическим выполнением,
метаданные задач в SQLite и восстановление задач после перезапуска процесса.

Контракт ошибок:
- 404 — неизвестный agent_id/task_id/invariant_id или номер задачи планировщика;
- 400 — недопустимый переход задачи, неразобранная цель MCP, негодные аргументы
  инструмента планировщика или его расписание;
- 409 — повторный task_id/имя инварианта, обращение к инструментам без соединения,
  пауза не активной задачи и возобновление не стоящей на паузе;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации, недоступный MCP-сервер или оборвавшийся вызов.

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к
менеджеру агентов, реестру MCP и планировщику — в ``backend/core/dependencies.py``.
Функции ``get_manager`` / ``get_mcp_registry`` / ``get_scheduler`` /
``get_schedule_service`` импортированы сюда как точки подмены для тестов.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.agent_manager import get_manager
from ..services.mcp_registry import get_mcp_registry
from ..services.schedule_service import get_schedule_service
from ..services.scheduler import get_scheduler
from . import agents, context, invariants, mcp, memory, profiles, scheduler, tasks
from .lifespan import lifespan

app = FastAPI(
    title="Агенты DeepSeek + планировщик задач — День 18",
    description=(
        "FastAPI-бэкенд веб-приложения дня 18: три слоя памяти в SQLite, профиль "
        "пользователя, КОНТРОЛИРУЕМЫЕ ПЕРЕХОДЫ состояния задачи, ИНВАРИАНТЫ, "
        "MCP-ИНСТРУМЕНТЫ и ПЛАНИРОВЩИК ФОНОВЫХ ЗАДАЧ (APScheduler): напоминание, "
        "периодический сбор данных из внешнего API и регулярная сводка по "
        "накопленным данным. Метаданные задач лежат в SQLite, поэтому задачи "
        "переживают перезапуск приложения. Эндпоинты: /mcp/... (6) и "
        "/scheduler/... (14)."
    ),
    version="12.0.0",
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
app.include_router(memory.router)
app.include_router(profiles.router)
app.include_router(scheduler.router)
app.include_router(tasks.router)
