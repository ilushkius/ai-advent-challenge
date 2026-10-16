"""ORM-таблица запусков подготовки релиза (день 35): ``release_runs``.

Одна строка на прогон «диапазон тегов → версия → раздел CHANGELOG → файлы». Колонки
выбраны ровно из требований дня, без запаса:

- ``from_tag``/``to_tag`` — запрошенный диапазон (то, что ввёл человек): по нему
  история релизов читается без расшифровки версий;
- ``version`` и ``version_reason`` — что решила модель (или правило) и ПОЧЕМУ; причина
  хранится рядом с версией, потому что «почему 1.0.1, а не 2.0.0» — первый вопрос к
  истории;
- ``changelog`` и ``release_notes`` — готовые тексты в ``Text``, а не ``JSON``: это
  разметка, её читают глазами, и она же уходит в выгрузку (``POST /release/export``);
- ``checks_passed`` — прошли ли проверки готовности на момент прогона (числа проверок
  живут в ответе и в отчёте, а в строке достаточно одного признака);
- ``files_modified`` — какие файлы прогон записал (пустой список — ``dry_run``);
- ``status`` — ``running``/``completed``/``failed``/``dry_run`` со ``index``: прогон
  идёт десятки секунд (модель, MCP, два ``pytest``), и интерфейс читает историю из
  другого потока, пока строка ещё ``running``.

Почему нет колонок ``provider``, ``commits_count`` и ``duration_ms``. Провайдер и
числа — свойства ОТВЕТА прогона, а длительность история считает как разность
``finished_at - started_at``: хранить производные значения значило бы держать их
согласованными при каждой правке.

Таблицу создаёт ``init_db`` (``create_all`` дописывает её в существующую
``agents.db``) — миграций в проекте нет, как и у остальных таблиц дней 18–34.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from shared.db_base import Base

from ..domain import release


class ReleaseRun(Base):
    """Запуск подготовки релиза (таблица release_runs, день 35)."""

    __tablename__ = "release_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Запрошенный диапазон: от какого тега и до какого собирались изменения.
    from_tag = Column(String(release.TAG_MAX), nullable=False)
    to_tag = Column(String(release.TAG_MAX), nullable=False)
    #: Итоговая версия и причина, по которой выбрана именно она.
    version = Column(String(release.VERSION_MAX), nullable=False)
    version_reason = Column(String(release.REASON_MAX), nullable=False, default="")
    #: Готовый раздел CHANGELOG и текст заметок о релизе (разметка, а не JSON).
    changelog = Column(Text, nullable=True)
    release_notes = Column(Text, nullable=True)
    #: Прошли ли проверки готовности на момент прогона.
    checks_passed = Column(Boolean, nullable=False, default=False)
    #: Какие файлы прогон записал (пустой список — ``dry_run``).
    files_modified = Column(JSON, nullable=False, default=list)
    #: Статус прогона: running/completed/failed/dry_run (значение домена строкой).
    status = Column(String(release.STATUS_MAX), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
