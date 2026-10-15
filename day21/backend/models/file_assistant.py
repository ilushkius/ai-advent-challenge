"""ORM-таблица запусков ассистента файлов (день 34).

Одна таблица — ``file_assistant_runs``: одна строка на прогон «цель → план → шаги».
Колонки выбраны ровно из требований дня, без запаса:

- ``goal`` — цель пользователя («найди все места, где используется ``IndexService``»);
  это то, что человек ввёл, и по нему история читается без расшифровки плана;
- ``plan`` — валидированный план шагов (данные, а не ссылка): видно, что именно
  ассистент СОБИРАЛСЯ сделать, даже если прогон остановился на втором шаге;
- ``steps`` — журнал ВЫПОЛНЕННЫХ шагов со статусом, временем, аргументами и
  результатом: «каждый шаг логировать» здесь означает «строка журнала в БД», а не
  строку лога процесса, которая не переживёт рестарт;
- ``files_read``/``files_modified``/``files_created`` — что ассистент тронул; три
  разные колонки, потому что это три разных действия, и вердикт дня («цель
  достигнута») проверяется именно по изменённым и созданным файлам;
- ``diff`` — unified diff изменений прогона в режиме ``Text``, а не ``JSON``: это
  текст, его читают глазами в разделе интерфейса и в отчёте;
- ``status`` — ``running``/``completed``/``failed``/``dry_run`` со ``index``: прогон
  читается из другого потока и процесса, пока идёт.

Почему нет колонок ``summary``, ``provider`` и ``duration_ms``. Сводка и провайдер
живут в ответе ``POST /file-assistant/execute``, а длительность история считает как
разность ``finished_at - started_at``: хранить три производных значения значило бы
держать их согласованными при каждой правке.

Таблицу создаёт ``init_db`` (``create_all`` дописывает её в существующую
``agents.db``) — миграций в проекте нет, как и у остальных таблиц дней 18–33.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from shared.db_base import Base

from ..core import config


class FileAssistantRun(Base):
    """Запуск ассистента файлов (таблица file_assistant_runs, день 34)."""

    __tablename__ = "file_assistant_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Цель пользователя целиком (заголовок запуска в истории и в разделе интерфейса).
    goal = Column(String(config.INDEX_QUERY_MAX), nullable=False)
    #: План шагов, прошедший валидацию домена (то, что ассистент собирался сделать).
    plan = Column(JSON, nullable=False, default=list)
    #: Журнал выполненных шагов: статус, время, аргументы, результат и ошибка.
    steps = Column(JSON, nullable=False, default=list)
    #: Пути, которые ассистент прочитал, изменил и создал (в порядке появления).
    files_read = Column(JSON, nullable=False, default=list)
    files_modified = Column(JSON, nullable=False, default=list)
    files_created = Column(JSON, nullable=False, default=list)
    #: Unified diff изменений прогона; пусто в ``dry_run`` и у прогона без правок.
    diff = Column(Text, nullable=True)
    #: Статус прогона: running/completed/failed/dry_run (значение домена строкой).
    status = Column(String(16), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
