"""Прогон индексации по этапам: чанкинг → эмбеддинги → индекс → поиск → сравнение.

Здесь живёт исполнение прогона (``IndexingService`` решает, когда его запускать и
что отдавать API): этапы идут по стейт-машине домена, прогресс пишется в строку
``index_runs`` после каждого шага, а терминальный статус ставится при ЛЮБОМ исходе.

Почему терминальный статус обязателен: прогресс читает интерфейс из другого
процесса, и запуск без терминального статуса означал бы вечный прогресс-бар.
Поэтому исключение внутри прогона не улетает наружу — оно попадает в ``error``
строки запуска со статусом ``failed``.

Демо-сценарий отличается от одиночного прогона только хвостом: он ищет по обеим
стратегиям пятью тестовыми запросами и считает метрики сравнения
(``index_comparison.py``). Отсюда два выхода из состояния ``INDEXING``: ``DONE``
(одиночная стратегия) и ``INDEXED`` (демо — дальше поиск и сравнение).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from shared.logging_utils import get_logger

from ..core import config
from ..domain.chunking import ChunkStrategy
from ..domain.document_sources import Document
from ..domain.index_scenarios import DEMO_QUERIES
from ..domain.indexing_fsm import IndexingEvent, IndexingFSM, IndexingState
from ..storage.index_run_store import IndexRunStore
from .chunker import chunk_document
from .document_loader import DocumentLoader
from .index_comparison import build_metrics, summary
from .index_service import IndexService
from .indexing_service import REASON_NO_DOCUMENTS, IndexingRejected

logger = get_logger(__name__)


class IndexRunner:
    """Прогон индексации: этапы, журнал прогресса и метрики сравнения."""

    def __init__(self, index_service: IndexService, loader: DocumentLoader,
                 run_store: IndexRunStore) -> None:
        self.index_service = index_service
        self.loader = loader
        self.run_store = run_store

    def run(self, run_id: int, strategies: Sequence[ChunkStrategy]) -> None:
        """Выполняет прогон и ставит терминальный статус (исключения не улетают).

        Доменный отказ (``IndexingRejected``) идёт особым путём: строка запуска
        закрывается статусом ``failed``, а само исключение уходит НАРУЖУ. Так
        синхронный ``POST /indexing/demo`` отвечает кодом причины (400 — нет
        документов), а фоновый путь его глотает: там отвечать уже нечем, а статус
        в БД — единственное место, где отказ виден.
        """
        started = time.perf_counter()
        try:
            self._body(run_id, strategies)
        except IndexingRejected as exc:
            self._fail(run_id, started, exc.message)
            raise
        except Exception as exc:  # noqa: BLE001 — фон не должен ронять процесс
            logger.error("Индексация %s упала: %s", run_id, exc)
            self._fail(run_id, started, str(exc))

    def _fail(self, run_id: int, started: float, error) -> None:
        """Ставит запуску терминальный статус ``failed``."""
        self.run_store.finish_run(
            run_id,
            status=IndexingState.FAILED.value,
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=error,
        )

    def _body(self, run_id: int, strategies: Sequence[ChunkStrategy]) -> None:
        """Этапы прогона по FSM; метрики пишутся вместе с терминальным статусом.

        Статус этапа пишется в НАЧАЛЕ его работы (кроме ``indexing`` — он отмечает
        момент, когда векторы и метаданные уже записаны): интерфейс опрашивает
        прогресс из другого процесса и обязан видеть тот этап, который идёт сейчас,
        а не тот, который только что закончился.
        """
        fsm = IndexingFSM()
        started = time.perf_counter()
        documents = self.loader.ensure_documents()
        if not documents:
            raise IndexingRejected(
                REASON_NO_DOCUMENTS,
                "документов не нашлось: проверьте источники дня (documents/ собирается "
                "из файлов репозитория)",
            )
        self.run_store.update_progress(run_id, documents_total=len(documents),
                                       documents_done=len(documents))
        self._advance(run_id, fsm, IndexingEvent.LOADED)  # -> chunking
        chunks = self._chunk_all(run_id, documents, strategies)
        self._advance(run_id, fsm, IndexingEvent.CHUNKED)  # -> embedding
        results = self._index_all(run_id, fsm, chunks, strategies)
        if len(strategies) > 1:
            self._advance(run_id, fsm, IndexingEvent.INDEXED)  # -> searching
            searches = self._search_all(run_id, strategies)
            self._advance(run_id, fsm, IndexingEvent.SEARCHED)  # -> comparing
            metrics = build_metrics(
                documents=documents, chunks=chunks, results=results, searches=searches,
                stats=self.index_service.stats(),
                embedding_model=self.index_service.embedder.model_name,
            )
            # Терминальный переход применяется, но НЕ пишется отдельно: статус
            # «completed» уходит в БД вместе с метриками в finish_run ниже. Иначе
            # полсекунды существовало бы состояние «завершено, метрик нет», и любой
            # читатель (прогресс-бар интерфейса, тест) увидел бы именно его.
            fsm.apply(IndexingEvent.COMPARED)
        else:
            metrics = build_metrics(
                documents=documents, chunks=chunks, results=results, searches={},
                stats=self.index_service.stats(),
                embedding_model=self.index_service.embedder.model_name,
            )
            fsm.apply(IndexingEvent.DONE)
        self.run_store.finish_run(
            run_id,
            status=fsm.state.value,
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - started) * 1000),
            embed_duration_ms=sum(int(item["embed_ms"]) for item in results.values()),
            index_duration_ms=sum(int(item["index_ms"]) for item in results.values()),
            metrics=metrics,
        )
        logger.info("Индексация %s завершена: %s", run_id, summary(metrics))

    def _chunk_all(self, run_id: int, documents: List[Document],
                   strategies: Sequence[ChunkStrategy]) -> Dict[str, List[Any]]:
        """Режет документы каждой стратегией, отмечая прогресс по документам."""
        chunks: Dict[str, List[Any]] = {}
        for strategy in strategies:
            collected: list[Any] = []
            for position, document in enumerate(documents, start=1):
                collected.extend(chunk_document(document, strategy))
                self.run_store.update_progress(
                    run_id, documents_done=position,
                    **{f"chunks_{strategy.value}": len(collected)})
            chunks[strategy.value] = collected
            logger.info("Чанкинг %s: %d чанков на %d документах",
                        strategy.value, len(collected), len(documents))
        return chunks

    def _index_all(self, run_id: int, fsm: IndexingFSM, chunks: Dict[str, List[Any]],
                   strategies: Sequence[ChunkStrategy]) -> Dict[str, dict]:
        """Считает эмбеддинги и кладёт их в FAISS, обновляя счётчики прогресса."""
        total = sum(len(chunks[strategy.value]) for strategy in strategies)
        self.run_store.update_progress(run_id, embeddings_total=total, embeddings_done=0)
        results: Dict[str, dict] = {}
        done = 0
        for strategy in strategies:
            items = chunks[strategy.value]

            def progress(processed: int, _total: int, _done: int = done) -> None:
                """Сколько эмбеддингов посчитано с учётом пройденных стратегий."""
                self.run_store.update_progress(run_id, embeddings_done=_done + processed)

            results[strategy.value] = self.index_service.index_chunks(
                items, strategy.value, progress=progress)
            done += len(items)
        self.run_store.update_progress(run_id, embeddings_done=total)
        self._advance(run_id, fsm, IndexingEvent.EMBEDDED)  # -> indexing
        return results

    def _search_all(self, run_id: int,
                    strategies: Sequence[ChunkStrategy]) -> Dict[str, List[dict]]:
        """Выполняет пять тестовых запросов на каждой стратегии."""
        results: Dict[str, List[dict]] = {}
        for strategy in strategies:
            entries: list[dict] = []
            for query in DEMO_QUERIES:
                entries.append({
                    "query": query.query,
                    "note": query.note,
                    "expected_sources": list(query.expected_sources),
                    "hits": self.index_service.search(
                        query.query, top_k=config.INDEX_DEFAULT_TOP_K,
                        strategy=strategy.value),
                    "relevant_total": self.index_service.store.chunks_by_sources(
                        strategy.value, query.expected_sources),
                })
            results[strategy.value] = entries
        return results

    def _advance(self, run_id: int, fsm: IndexingFSM, event: IndexingEvent) -> IndexingState:
        """Двигает автомат событием и пишет новый этап в строку запуска."""
        state = fsm.apply(event)
        self._set_status(run_id, fsm)
        return state

    def _set_status(self, run_id: int, fsm: IndexingFSM) -> None:
        """Пишет текущий этап автомата в строку запуска (его читает интерфейс)."""
        self.run_store.update_progress(run_id, status=fsm.state.value)
