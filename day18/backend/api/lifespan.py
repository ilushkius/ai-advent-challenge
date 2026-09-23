"""Жизненный цикл приложения дня 18: старт и остановка фоновых служб.

Вынесен из ``main.py`` отдельным модулем, потому что ``main.py`` держит лимит 80
строк, а порядок старта здесь содержательный и его хочется читать целиком:

1. **таблицы** — ``database.init_db()`` создаёт схему SQLite, если её ещё нет.
   Вызов идёт атрибутом модуля (``database.init_db``), а не импортированной
   функцией: на этом приёме держится скрипт прогона
   (``scripts/video_scenario_server.py``, ``scripts/scheduler_stand.py``) —
   он подменяет ``database.init_db`` и не даёт тестовому стенду трогать рабочую БД;
2. **агенты** — ``restore_from_db()`` поднимает диалоги, слои памяти и состояние
   задач, накопленные предыдущими запусками;
3. **планировщик** — ``get_scheduler().start()`` запускает APScheduler в текущем
   цикле событий и ставит задачи из ``scheduled_tasks`` (задачи переживают
   перезапуск именно здесь).

Останавливаются службы в обратном порядке: сначала планировщик (чтобы фон не
трогал БД на выходе), затем MCP-подключение (сервер stdio иначе остался бы висеть
дочерним процессом).

Функции берутся через ``backend.core.dependencies``, а не импортируются напрямую:
``dependencies`` резолвит их по атрибутам ``backend.api.main`` в момент вызова,
поэтому тесты подменяют ``main.get_manager`` / ``main.get_scheduler`` /
``main.get_mcp_registry`` одной строкой и подмену видят все, включая lifespan.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from shared.logging_utils import get_logger

from ..core import dependencies
from ..storage import database

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app):
    """Старт: таблицы, агенты и планировщик; остановка: планировщик и MCP."""
    database.init_db()
    dependencies.get_manager().restore_from_db()
    dependencies.get_scheduler().start()
    logger.debug("Старт бэкенда: таблицы созданы, агенты и планировщик восстановлены")
    yield
    dependencies.get_scheduler().shutdown()
    dependencies.get_mcp_registry().close()
    logger.debug("Остановка бэкенда: планировщик остановлен, MCP-соединение закрыто")
