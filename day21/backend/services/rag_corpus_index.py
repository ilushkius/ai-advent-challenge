"""Сборка корпуса RAG и его конфигурация (день 22).

Вынесено из ``rag_service`` (день 23), чтобы служба не росла за предел строк: здесь
только работа с корпусом и индексами, а не режимы ответа модели. Имена индексов у
стратегий свои, а код чанкинга общий с днём 21 — иначе у RAG-корпуса появился бы
свой третий чанкер.
"""
from __future__ import annotations

from typing import Dict

from shared.logging_utils import get_logger

from ..domain import rag_corpus_spec, rag_mode
from ..domain.chunking import ChunkStrategy
from ..storage.chunk_store import ChunkStore
from .chunker import chunk_document
from .index_service import IndexService
from .rag_corpus_loader import RagCorpusLoader
from .rag_errors import RAGError

logger = get_logger(__name__)

__all__ = ["CHUNK_STRATEGIES", "corpus_config", "prepare_corpus"]

#: Разбиение текста для каждой стратегии корпуса: имена индексов свои, а код
#: чанкинга общий с днём 21 — иначе у RAG-корпуса появился бы свой третий чанкер.
CHUNK_STRATEGIES = {
    rag_mode.RAG_STRATEGY_FIXED: ChunkStrategy.FIXED,
    rag_mode.RAG_STRATEGY_STRUCTURAL: ChunkStrategy.STRUCTURAL,
}


def prepare_corpus(loader: RagCorpusLoader, index_service: IndexService) -> dict:
    """Собирает корпус заново и строит оба индекса под именами дня 22.

    Пересборка, а не дозапись: ``index_chunks`` умеет только дописывать, поэтому
    индекс предварительно очищается, и повторный прогон даёт то же состояние.
    """
    problems = loader.validate()
    if problems:
        raise RAGError("Источники корпуса не готовы: " + "; ".join(problems))
    loader.collect()
    documents = loader.load_documents()
    indexes: Dict[str, dict] = {}
    counts: Dict[str, int] = {}
    for strategy in rag_mode.RAG_STRATEGIES:
        chunks = [chunk
                  for document in documents
                  for chunk in chunk_document(document, CHUNK_STRATEGIES[strategy])]
        index_service.clear_index(strategy)
        indexes[strategy] = index_service.index_chunks(chunks, strategy)
        counts[strategy] = len(chunks)
        if len(chunks) < rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS:
            logger.warning("RAG: чанков стратегии %s меньше минимума: %d < %d",
                           strategy, len(chunks),
                           rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS)
    logger.info("Корпус RAG собран: документов %d, чанков %s",
                len(documents), counts)
    return {
        "corpus": loader.status(),
        "indexes": indexes,
        "chunks": counts,
        "min_pages": rag_corpus_spec.RAG_CORPUS_MIN_PAGES,
        "min_chunks": rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS,
    }


def corpus_config(loader: RagCorpusLoader, store: ChunkStore) -> dict:
    """Готовность режима: объём корпуса, чанки обеих стратегий и лимиты.

    Числа берутся из ``document_chunks``, а не из файлов индекса.
    """
    corpus = loader.status()
    indexes = [{"strategy": strategy, "chunks": store.count(strategy)}
               for strategy in rag_mode.RAG_STRATEGIES]
    total = sum(int(item["chunks"]) for item in indexes)
    return {
        "ready": bool(corpus.get("ready")) and total > 0,
        "corpus": corpus,
        "indexes": indexes,
        "chunks_total": total,
        "strategies": list(rag_mode.RAG_STRATEGIES),
        "default_strategy": rag_mode.RAG_DEFAULT_STRATEGY,
        "top_k_default": rag_mode.RAG_DEFAULT_TOP_K,
        "top_k_max": rag_mode.RAG_MAX_TOP_K,
        "context_max_tokens": rag_mode.RAG_CONTEXT_MAX_TOKENS,
        "chunk_max_chars": rag_mode.RAG_CHUNK_MAX_CHARS,
    }
