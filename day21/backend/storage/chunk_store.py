"""Хранилище чанков документов в SQLite (день 21): ``ChunkStore``.

Здесь живёт таблица ``document_chunks``: запись чанков партии, чтение их по id
(в порядке, который вернул FAISS), выборки по стратегии и счётчики для метрик
сравнения. Правила («как резать документ», «как считать precision@k») — в домене
(``domain/chunking.py``, ``domain/index_metrics.py``); хранилище их не повторяет,
поэтому тестируется без модели эмбеддингов и без FAISS.

``add_chunks`` заводит строки и сразу проставляет ``embedding_id = id``: id вектора
в FAISS — это и есть первичный ключ метаданных, и второй источник истины («какой
вектор какому чанку соответствует») не нужен. Поэтому вставка идёт пачкой с
``flush()`` (id известны до ``commit()``).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, List, Optional, Sequence

from ..models.indexing import DocumentChunk
from . import database
from .index_rows import chunk_dict

__all__ = ["ChunkStore"]


class ChunkStore:
    """Строки ``document_chunks``: запись чанков и выборки для метрик."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``PipelineStore``)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def add_chunks(self, chunks: Iterable[Any], strategy: str) -> List[int]:
        """Пишет чанки одной стратегии; возвращает их id в порядке входа.

        id возвращаются (а не просто их число), потому что вектора FAISS кладутся
        под этими же id: ``IndexService`` не смог бы связать вектор с чанком, не зная
        id строк, — а запрашивать их повторно по ``chunk_id`` значило бы лишний
        запрос и вторую форму ответа на тот же вопрос.

        ``chunks`` — либо объекты чанкера (``Chunk`` с ``to_dict()``), либо готовые
        словари: обе формы приходят из сервисов, и лишний слой преобразования был бы
        копированием полей.
        """
        rows = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in chunks]
        if not rows:
            return []
        with self.session() as session:
            orm_rows = []
            for row in rows:
                orm = DocumentChunk(
                    source=row["source"],
                    title=row["title"],
                    section=row.get("section") or "",
                    chunk_id=row["chunk_id"],
                    strategy=strategy,
                    content=row["content"],
                    token_count=int(row.get("token_count") or 0),
                    embedding_id=0,
                    start_char=int(row.get("start_char") or 0),
                    end_char=int(row.get("end_char") or 0),
                    section_level=int(row.get("section_level") or 0),
                )
                session.add(orm)
                orm_rows.append(orm)
            session.flush()
            for orm in orm_rows:
                orm.embedding_id = orm.id
            ids = [int(orm.id) for orm in orm_rows]
            session.commit()
            return ids

    def rows_by_ids(self, ids: Sequence[int]) -> List[dict[str, Any]]:
        """Чанки по id в порядке ``ids`` (порядок FAISS — это порядок по близости).

        Отсутствующие в БД id (например, ``-1`` — «пустая ячейка» FAISS) пропускаются.
        """
        clean = [int(i) for i in ids if int(i) >= 0]
        if not clean:
            return []
        with self.session() as session:
            rows = (session.query(DocumentChunk)
                    .filter(DocumentChunk.id.in_(clean)).all())
            by_id = {row.id: chunk_dict(row) for row in rows}
        return [by_id[i] for i in clean if i in by_id]

    def chunks(self, strategy: str, limit: Optional[int] = None,
               offset: int = 0) -> List[dict[str, Any]]:
        """Чанки стратегии по возрастанию id; ``limit=None`` — все."""
        with self.session() as session:
            query = (session.query(DocumentChunk)
                     .filter(DocumentChunk.strategy == strategy)
                     .order_by(DocumentChunk.id.asc())
                     .offset(max(0, int(offset))))
            if limit is not None:
                query = query.limit(max(1, int(limit)))
            return [chunk_dict(row) for row in query.all()]

    def count(self, strategy: str) -> int:
        """Сколько чанков стратегии лежит в таблице."""
        with self.session() as session:
            return int(session.query(DocumentChunk)
                       .filter(DocumentChunk.strategy == strategy).count())

    def counts_by_source(self, strategy: str) -> dict[str, int]:
        """Сколько чанков стратегии пришло из каждого документа."""
        with self.session() as session:
            grouped = (session.query(DocumentChunk.source)
                       .filter(DocumentChunk.strategy == strategy).all())
        counts: dict[str, int] = {}
        for (source,) in grouped:
            counts[source] = counts.get(source, 0) + 1
        return counts

    def token_counts(self, strategy: str) -> List[int]:
        """Размеры всех чанков стратегии в токенах (для статистики и гистограммы)."""
        with self.session() as session:
            rows = (session.query(DocumentChunk.token_count)
                    .filter(DocumentChunk.strategy == strategy).all())
        return [int(value or 0) for (value,) in rows]

    def with_section(self, strategy: str) -> int:
        """Сколько чанков стратегии имеют непустую секцию (метрика структуры)."""
        with self.session() as session:
            return int(session.query(DocumentChunk)
                       .filter(DocumentChunk.strategy == strategy)
                       .filter(DocumentChunk.section.isnot(None))
                       .filter(DocumentChunk.section != "").count())

    def chunks_by_sources(self, strategy: str, sources: Sequence[str]) -> int:
        """Сколько чанков стратегии принадлежат перечисленным документам.

        Это знаменатель recall@k: «сколько всего релевантных фрагментов есть в
        индексе» — без него метрика делилась бы на число ожидаемых файлов.
        """
        clean = [str(s) for s in sources if s]
        if not clean:
            return 0
        with self.session() as session:
            return int(session.query(DocumentChunk)
                       .filter(DocumentChunk.strategy == strategy)
                       .filter(DocumentChunk.source.in_(clean)).count())

    def delete_strategy(self, strategy: str) -> int:
        """Удаляет все чанки стратегии (переиндексация начинается с чистого листа)."""
        with self.session() as session:
            removed = int(session.query(DocumentChunk)
                          .filter(DocumentChunk.strategy == strategy).delete())
            session.commit()
            return removed
