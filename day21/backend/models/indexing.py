"""ORM-таблицы индексации документов (день 21).

Две таблицы, по одной на вопрос «что лежит в индексе» и «что происходило при
сборке индекса»:

- ``document_chunks`` (DocumentChunk) — ЧАНК ДОКУМЕНТА: источник, заголовок, секция
  (у структурной стратегии — заголовок раздела, у фиксированной — пусто), номер
  чанка, стратегия, текст, число токенов, границы в исходном тексте и уровень
  секции. Колонка ``embedding_id`` — это id вектора в FAISS: он равен ``id`` строки,
  потому что метаданные чанка живут здесь, а вектор — в индексе. Разделение
  намеренное: FAISS отвечает за близость векторов, SQLite — за всё остальное
  (фильтры, историю, отчёты), и второй слой не требует пересчёта эмбеддингов;
- ``index_runs`` (IndexRun) — ЗАПУСК ИНДЕКСАЦИИ: стратегия, статус (значения
  ``IndexingState``), счётчики документов/чанков/эмбеддингов, метки времени,
  длительности этапов, метрики сравнения стратегий (JSON) и текст ошибки.

Журнал лежит в SQLite, а не в памяти процесса: прогон идёт фоновым потоком,
поэтому интерфейс (другой процесс) опрашивает прогресс по номеру запуска, а после
перезапуска приложения история запусков читается снова.

Границы строк — из ``config`` (та же конвенция, что у таблиц планировщика,
пайплайна и оркестрации).
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text

from shared.db_base import Base

from ..core import config


class DocumentChunk(Base):
    """Чанк документа (таблица document_chunks, день 21)."""

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Имя файла-документа в папке documents/ (например, ``day20-readme.md``).
    source = Column(String(config.INDEX_SOURCE_MAX), nullable=False, index=True)
    #: Заголовок документа (первый заголовок markdown или докстринг модуля).
    title = Column(String(config.INDEX_TITLE_MAX), nullable=False)
    #: Заголовок раздела: у структурной стратегии — из документа, у fixed — "".
    section = Column(String(config.INDEX_SECTION_MAX), nullable=True)
    #: Идентификатор чанка внутри стратегии (``structural:day20-readme.md:0003``).
    #: Уникальность НЕ гарантируется: повторный прогон по тем же документам
    #: дописывает индекс (в интерфейсе для переиндексации есть явная очистка), и
    #: запрет повторов превратил бы кнопку демо-прогона в одноразовую — вместо
    #: этого рост числа чанков видно в статистике и в истории запусков.
    chunk_id = Column(String(config.INDEX_CHUNK_ID_MAX), nullable=False, index=True)
    #: Значение ``ChunkStrategy``: "fixed" (окно по токенам) или "structural".
    strategy = Column(String(config.INDEX_STRATEGY_MAX), nullable=False, index=True)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    #: Идентификатор вектора в FAISS (равен id строки: см. docstring модуля).
    embedding_id = Column(Integer, nullable=False, default=0)
    #: Границы чанка в тексте исходного документа (точные, а не оценка).
    start_char = Column(Integer, nullable=False, default=0)
    end_char = Column(Integer, nullable=False, default=0)
    #: Уровень секции из заголовка (0 — преамбула markdown/plain, 1 — «#», …).
    section_level = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class IndexRun(Base):
    """Запуск индексации документов (таблица index_runs, день 21)."""

    __tablename__ = "index_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Стратегия прогона: "fixed" | "structural" | "demo" (прогон обеих).
    strategy = Column(String(config.INDEX_STRATEGY_MAX), nullable=False, index=True)
    #: Статус: значение ``IndexingState`` (loading…completed/failed).
    status = Column(String(config.INDEX_STATUS_MAX), nullable=False, index=True)
    documents_total = Column(Integer, nullable=False, default=0)
    documents_done = Column(Integer, nullable=False, default=0)
    chunks_fixed = Column(Integer, nullable=False, default=0)
    chunks_structural = Column(Integer, nullable=False, default=0)
    embeddings_total = Column(Integer, nullable=False, default=0)
    embeddings_done = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    #: Длительность прогона целиком и отдельно — эмбеддингов и записи индекса.
    duration_ms = Column(Integer, nullable=False, default=0)
    embed_duration_ms = Column(Integer, nullable=False, default=0)
    index_duration_ms = Column(Integer, nullable=False, default=0)
    #: Метрики сравнения стратегий (документы, запросы, статистика, время).
    metrics = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
