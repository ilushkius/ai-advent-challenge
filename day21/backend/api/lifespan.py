"""Жизненный цикл приложения дня 20: старт и остановка фоновых служб.

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
   перезапуск именно здесь);
4. **флот MCP-серверов** — ``get_mcp_registry().connect_all()`` поднимает по
   соединению на каждый сервер из ``mcp_servers.json`` и читает их каталоги.
   Сбой отдельного сервера не мешает старту: он виден в своей записи
   (``GET /mcp/servers``) как ``error``, а остальные работают.
5. **индексы документов** — ``get_index_service().load_all()`` читает
   ``index/fixed.index`` и ``index/structural.index`` с диска, поэтому поиск по
   документам работает сразу после перезапуска, без повторной индексации;
6. **прогрев модели эмбеддингов** — ``get_embedding_service().warmup()`` в
   ДЕМОН-ПОТОКЕ. Блокирующий прогрев занял бы десятки секунд, а на первой загрузке
   — минуты (скачивание весов в ``index/models``), и бэкенд всё это время не отвечал
   бы; неудача прогрева видна как ``failed`` первого прогона индексации.

Останавливаются службы в обратном порядке: сначала планировщик (чтобы фон не
трогал БД на выходе), затем MCP-подключения — ``close()`` закрывает и активное
соединение, и весь флот (серверы stdio иначе остались бы висеть дочерними
процессами). Индексы перед этим записываются на диск (``save_all``): в памяти они
могли измениться после последней записи файла.

Функции берутся через ``backend.core.dependencies``, а не импортируются напрямую:
``dependencies`` резолвит их по атрибутам ``backend.api.main`` в момент вызова,
поэтому тесты подменяют ``main.get_manager`` / ``main.get_scheduler`` /
``main.get_mcp_registry`` одной строкой и подмену видят все, включая lifespan.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from shared.logging_utils import get_logger

from ..core import dependencies
from ..storage import database

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app):
    """Старт: таблицы, агенты, планировщик, флот и индексы; остановка: всё обратно."""
    database.init_db()
    dependencies.get_manager().restore_from_db()
    dependencies.get_scheduler().start()
    dependencies.get_mcp_registry().connect_all()
    dependencies.get_index_service().load_all()
    threading.Thread(target=dependencies.get_embedding_service().warmup,
                     daemon=True, name="embedding-warmup").start()
    logger.debug(
        "Старт бэкенда: таблицы созданы, агенты и планировщик восстановлены, "
        "флот MCP-серверов подключён, индексы документов прочитаны, "
        "прогрев модели эмбеддингов запущен"
    )
    yield
    dependencies.get_scheduler().shutdown()
    dependencies.get_index_service().save_all()
    dependencies.get_mcp_registry().close()
    logger.debug(
        "Остановка бэкенда: планировщик остановлен, индексы записаны, "
        "соединения MCP закрыты"
    )
