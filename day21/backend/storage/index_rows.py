"""ORM-строки индексации → словари для API/UI (день 21).

Преобразования живут здесь, а не в хранилище: и ``ChunkStore``, и ``IndexRunStore``,
и сервис, и роутер, и отчёт прогона видят одну и ту же форму записи (та же причина,
что у ``pipeline_rows.py`` дня 19). Метки времени приводятся к UTC-aware, JSON-поля —
к виду, который переживает запись в колонку (``as_utc`` и ``jsonable``
переиспользуются из ``scheduler_rows``: ещё один экземпляр тех же помощников был бы
копированием).

Имя ``index_run_dict`` (а не ``run_dict``, как у соседей) выбрано потому, что
``run_dict`` уже занято строкой запуска планировщика в ``scheduler_rows``:
``storage/__init__.py`` реэкспортирует имена слоя, и одноимённая функция второго
домена молча заслонила бы первую.
"""
from __future__ import annotations

from typing import Any

from ..models.indexing import DocumentChunk, IndexRun
from .scheduler_rows import as_utc, jsonable


def chunk_dict(row: DocumentChunk) -> dict[str, Any]:
    """Чанк документа для API/UI: метаданные, текст и границы в исходнике."""
    created = as_utc(row.created_at)
    return {
        "id": row.id,
        "source": row.source,
        "title": row.title,
        "section": row.section or "",
        "chunk_id": row.chunk_id,
        "strategy": row.strategy,
        "content": row.content,
        "token_count": int(row.token_count or 0),
        "embedding_id": int(row.embedding_id or 0),
        "start_char": int(row.start_char or 0),
        "end_char": int(row.end_char or 0),
        "section_level": int(row.section_level or 0),
        "created_at": created.isoformat() if created else None,
    }


def index_run_dict(row: IndexRun) -> dict[str, Any]:
    """Запуск индексации для API/UI: статус, счётчики, время, метрики и ошибка."""
    started = as_utc(row.started_at)
    finished = as_utc(row.finished_at)
    return {
        "id": row.id,
        "strategy": row.strategy,
        "status": row.status,
        "documents_total": int(row.documents_total or 0),
        "documents_done": int(row.documents_done or 0),
        "chunks_fixed": int(row.chunks_fixed or 0),
        "chunks_structural": int(row.chunks_structural or 0),
        "embeddings_total": int(row.embeddings_total or 0),
        "embeddings_done": int(row.embeddings_done or 0),
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "duration_ms": int(row.duration_ms or 0),
        "embed_duration_ms": int(row.embed_duration_ms or 0),
        "index_duration_ms": int(row.index_duration_ms or 0),
        "metrics": jsonable(row.metrics),
        "error": row.error,
    }
