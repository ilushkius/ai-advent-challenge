"""FastAPI-приложение дня 19: память, задача, инварианты, MCP, план и пайплайны.

Запуск из папки day19/:  uvicorn backend.api.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (``backend/api/lifespan.py``) создаются таблицы SQLite, агенты
восстанавливаются из базы и поднимается планировщик фоновых задач; при остановке
планировщик встаёт, а MCP-подключение закрывается.

День 18 добавил **планировщик фоновых задач** (``backend/api/scheduler.py``,
14 эндпоинтов): отложенное и периодическое выполнение трёх MCP-инструментов,
метаданные задач в SQLite и восстановление задач после перезапуска процесса.

День 19 добавляет **декларативный пайплайн MCP-инструментов**
(``backend/api/pipelines.py``, 5 эндпоинтов): шаги описаны данными (поиск →
сводка → файл), данные между шагами передаются маппингом, а каждый шаг логируется
в ``pipeline_steps`` с входом, выходом и временем. Прогон можно запустить фоном —
интерфейс опрашивает статус, показывая прогресс по шагам.

Контракт ошибок:
- 404 — неизвестный agent_id/task_id/invariant_id, номер задачи планировщика или
  номер запуска пайплайна;
- 400 — недопустимый переход задачи, неразобранная цель MCP, негодные аргументы
  инструмента планировщика, его расписание или конфигурация пайплайна;
- 409 — повторный task_id/имя инварианта, обращение к инструментам без соединения,
  пауза не активной задачи и возобновление не стоящей на паузе;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации, недоступный MCP-сервер или оборвавшийся вызов.

Здесь только сборка приложения: эндпоинты живут в ``backend/api/``, доступ к
службам — в ``backend/core/dependencies.py``. Функции ``get_manager`` /
``get_mcp_registry`` / ``get_scheduler`` / ``get_schedule_service`` /
``get_pipeline_service`` импортированы сюда как точки подмены для тестов.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..agents.agent_manager import get_manager
from ..services.mcp_registry import get_mcp_registry
from ..services.pipeline_service import get_pipeline_service
from ..services.schedule_service import get_schedule_service
from ..services.scheduler import get_scheduler
from . import agents, context, invariants, mcp, memory, pipelines, profiles, scheduler, tasks
from .lifespan import lifespan

app = FastAPI(
    title="Агенты DeepSeek + пайплайны MCP-инструментов — День 19",
    description=(
        "FastAPI-бэкенд веб-приложения дня 19: три слоя памяти в SQLite, профиль "
        "пользователя, КОНТРОЛИРУЕМЫЕ ПЕРЕХОДЫ состояния задачи, ИНВАРИАНТЫ, "
        "MCP-ИНСТРУМЕНТЫ, ПЛАНИРОВЩИК ФОНОВЫХ ЗАДАЧ (APScheduler) и ДЕКЛАРАТИВНЫЙ "
        "ПАЙПЛАЙН инструментов композиции: шаги описаны данными (поиск → сводка → "
        "сохранение файла), данные между шагами передаются маппингом, каждый шаг "
        "логируется в SQLite с входом, выходом и временем. Прогон запускается и "
        "фоном: интерфейс опрашивает статус и показывает прогресс по шагам. "
        "Эндпоинты: /mcp/... (6), /scheduler/... (14) и /pipelines/... (5)."
    ),
    version="13.0.0",
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
app.include_router(pipelines.router)
app.include_router(profiles.router)
app.include_router(scheduler.router)
app.include_router(tasks.router)
