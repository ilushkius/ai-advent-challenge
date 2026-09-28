"""Векторный индекс на FAISS плюс метаданные чанков в SQLite (день 21).

Разделение обязанностей здесь принципиальное:

- **FAISS** (`faiss.IndexIDMap2` над `IndexFlatIP`) отвечает за близость векторов.
  Векторы нормализованы (``EmbeddingService``), поэтому скалярное произведение
  равно косинусной близости, а ``IndexIDMap2`` позволяет класть вектора с ЯВНЫМИ
  id — id равен ``document_chunks.id``;
- **SQLite** отвечает за всё остальное: текст чанка, источник, заголовок, секцию,
  размер и границы в документе. ``ChunkStore.rows_by_ids`` возвращает метаданные в
  том порядке, в каком их вернул FAISS, поэтому «IDMap2 + таблица» дают полноценный
  поиск без второго индекса и без пересчёта эмбеддингов после перезапуска.

Индексы лежат в файлах ``index/fixed.index`` и ``index/structural.index``: при
старте бэкенда они читаются (``load_all``), при остановке — пишутся (``save_all``),
поэтому поиск работает сразу после перезапуска приложения.

Дописывание, а не переиндексация. Повторный ``index_chunks`` той же стратегии
ДОПИСЫВАЕТ индекс и таблицу (и подгружает файл с диска, если индекс не в памяти):
неявная переиндексация означала бы пересчёт всех эмбеддингов на каждый прогон.
Чистка — только явная (``clear_index``: кнопка в интерфейсе и ``POST /indexing/clear``).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import faiss
import numpy as np

from shared.logging_utils import get_logger

from ..core import config
from ..domain.chunking import ChunkStrategy
from ..domain.index_metrics import histogram, size_stats
from ..storage.chunk_store import ChunkStore
from .embedding_service import EmbeddingService, get_embedding_service

logger = get_logger(__name__)

#: Сколько символов попадания показываются в ``preview`` (полный текст — в ``content``).
PREVIEW_CHARS = 300


class IndexNotBuiltError(Exception):
    """Поиск по индексу, которого нет (роутер отвечает 409)."""


class IndexService:
    """Индексы процесса: построение, поиск, сохранение, чтение метрик."""

    def __init__(self, embedder: Optional[EmbeddingService] = None,
                 store: Optional[ChunkStore] = None,
                 index_dir: Optional[object] = None) -> None:
        self._embedder = embedder
        self._store = store
        self._index_dir = Path(index_dir) if index_dir is not None else config.INDEX_DIR
        self._indexes: Dict[str, Any] = {}
        self._locks = {
            strategy.value: threading.RLock() for strategy in ChunkStrategy
        }

    # ---------- зависимости ----------
    @property
    def embedder(self) -> EmbeddingService:
        """Служба эмбеддингов: переданная или служба процесса."""
        if self._embedder is None:
            self._embedder = get_embedding_service()
        return self._embedder

    @property
    def store(self) -> ChunkStore:
        """Хранилище чанков: переданное или хранилище процесса."""
        if self._store is None:
            self._store = ChunkStore()
        return self._store

    def path_for(self, strategy: str) -> Path:
        """Файл индекса стратегии (в каталоге дня или в подменённом каталоге теста)."""
        name = f"{strategy}.index"
        if self._index_dir == config.INDEX_DIR:
            return config.INDEX_FILES.get(strategy) or (self._index_dir / name)
        return self._index_dir / name

    # ---------- построение ----------
    def index_chunks(self, chunks: Sequence[Any], strategy: str,
                     progress: Optional[Callable[[int, int], None]] = None) -> dict:
        """Считает эмбеддинги, дописывает чанки в SQLite и векторы в FAISS.

        Порядок важен: сначала считаются и пишутся метаданные (строки получают id),
        потом вектора кладутся в индекс под этими же id. Если упасть между шагами,
        в таблице окажутся чанки без векторов — их видно в статистике (``chunks``
        больше ``index_size``), а повторный прогон допишет их.
        """
        rows = [chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
                for chunk in chunks]
        started = time.perf_counter()
        vectors = self._embed(rows, progress)
        embed_ms = int((time.perf_counter() - started) * 1000)
        if not rows:
            return {"indexed": 0, "embeddings": 0, "dimension": self.embedder.dimension,
                    "embed_ms": embed_ms, "index_ms": 0, "saved_to": None}
        index_started = time.perf_counter()
        ids = self.store.add_chunks(rows, strategy)
        index = self._ensure_index(strategy, dimension=int(vectors.shape[1]))
        with self._locks.get(strategy, threading.RLock()):
            index.add_with_ids(np.ascontiguousarray(vectors, dtype=np.float32),
                               np.asarray(ids, dtype=np.int64))
        saved = self.save_index(strategy)
        index_ms = int((time.perf_counter() - index_started) * 1000)
        logger.info("Индекс %s: чанков %d, размерность %d, эмбеддинги %d мс, индекс %d мс",
                    strategy, len(ids), vectors.shape[1], embed_ms, index_ms)
        return {
            "indexed": len(ids),
            "embeddings": int(vectors.shape[0]),
            "dimension": int(vectors.shape[1]),
            "embed_ms": embed_ms,
            "index_ms": index_ms,
            "saved_to": saved["path"],
        }

    def _embed(self, rows: Sequence[Dict[str, Any]],
               progress: Optional[Callable[[int, int], None]]) -> np.ndarray:
        """Эмбеддинги текстов чанков батчами, с отчётом о прогрессе."""
        texts = [str(row.get("content") or "") for row in rows]
        total = len(texts)
        if not total:
            return np.zeros((0, self.embedder.dimension), dtype=np.float32)
        batch_size = max(1, config.EMBEDDING_BATCH_SIZE)
        batches: list[np.ndarray] = []
        done = 0
        for start in range(0, total, batch_size):
            batches.append(self.embedder.encode(texts[start:start + batch_size]))
            done = min(total, start + batch_size)
            if progress is not None:
                progress(done, total)
        return np.vstack(batches).astype(np.float32)

    # ---------- поиск ----------
    def search(self, query: str, top_k: Optional[int] = None,
               strategy: str = config.INDEX_AGENT_STRATEGY) -> List[dict]:
        """Топ-k попаданий по косинусной близости (порядок — по убыванию оценки)."""
        index = self._loaded_index(strategy)
        if index is None or index.ntotal == 0:
            raise IndexNotBuiltError(
                f"Индекс стратегии {strategy!r} пуст: сначала выполните индексацию"
            )
        limit = max(1, int(top_k or config.INDEX_DEFAULT_TOP_K))
        vector = self.embedder.encode_one(str(query))
        with self._locks.get(strategy, threading.RLock()):
            scores, ids = index.search(np.ascontiguousarray(vector.reshape(1, -1),
                                                            dtype=np.float32), limit)
        rows = self.store.rows_by_ids([int(item) for item in ids[0]])
        return [
            {
                "rank": position + 1,
                "chunk_id": row["chunk_id"],
                "source": row["source"],
                "title": row["title"],
                "section": row["section"],
                "section_level": row["section_level"],
                "strategy": row["strategy"],
                "score": round(float(scores[0][position]), 4),
                "token_count": row["token_count"],
                "start_char": row["start_char"],
                "end_char": row["end_char"],
                "content": row["content"],
                "preview": _preview(str(row["content"])),
            }
            for position, row in enumerate(rows)
        ]

    # ---------- файлы индекса ----------
    def save_index(self, strategy: str, path: Optional[object] = None) -> dict:
        """Пишет индекс стратегии в файл (``faiss.write_index``)."""
        target = Path(path) if path is not None else self.path_for(strategy)
        index = self._indexes.get(strategy)
        if index is None:
            return {"strategy": strategy, "path": None, "vectors": 0, "written": False}
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._locks.get(strategy, threading.RLock()):
            faiss.write_index(index, str(target))
        return {"strategy": strategy, "path": str(target),
                "vectors": int(index.ntotal), "written": True}

    def save_all(self) -> Dict[str, dict]:
        """Пишет все загруженные индексы (вызывается при остановке приложения)."""
        return {strategy: self.save_index(strategy) for strategy in self._indexes}

    def load_index(self, strategy: str, path: Optional[object] = None) -> dict:
        """Читает индекс стратегии из файла (отсутствующий файл — не ошибка)."""
        source = Path(path) if path is not None else self.path_for(strategy)
        if not source.exists():
            logger.info("Индекс %s ещё не построен (%s)", strategy, source)
            return {"strategy": strategy, "path": str(source), "vectors": 0,
                    "loaded": False}
        index = faiss.read_index(str(source))
        self._indexes[strategy] = index
        logger.info("Индекс %s загружен: %d векторов", strategy, index.ntotal)
        return {"strategy": strategy, "path": str(source),
                "vectors": int(index.ntotal), "loaded": True}

    def load_all(self) -> Dict[str, dict]:
        """Читает оба индекса с диска (старт приложения: поиск работает сразу)."""
        return {strategy.value: self.load_index(strategy.value)
                for strategy in ChunkStrategy}

    def clear_index(self, strategy: str) -> dict:
        """Убирает индекс стратегии: память, файл и строки ``document_chunks``."""
        with self._locks.get(strategy, threading.RLock()):
            self._indexes.pop(strategy, None)
            path = self.path_for(strategy)
            if path.exists():
                path.unlink()
        removed = self.store.delete_strategy(strategy)
        logger.info("Индекс %s очищен: удалено чанков %d", strategy, removed)
        return {"strategy": strategy, "removed": {strategy: removed}}

    # ---------- чтение ----------
    def index_size(self, strategy: str) -> int:
        """Сколько векторов в индексе стратегии (0 — индекса нет ни в памяти, ни на диске)."""
        index = self._loaded_index(strategy)
        return int(index.ntotal) if index is not None else 0

    def chunks(self, strategy: str, limit: Optional[int] = None) -> List[dict]:
        """Чанки стратегии из таблицы (все при ``limit=None``)."""
        return self.store.chunks(strategy, limit=limit)

    def sample_chunks(self, strategy: str,
                      limit: int = config.INDEX_DEFAULT_LIMIT) -> List[dict]:
        """Первые чанки стратегии — примеры для интерфейса и отчёта."""
        return self.store.chunks(strategy, limit=limit)

    def get_stats(self, strategy: str) -> dict:
        """Статистика стратегии: объёмы чанков, документы, покрытие, файл индекса.

        Индекса нет — не ошибка: статистика нужна и до первого прогона (интерфейс
        рисует нули), поэтому пустая стратегия отдаёт нулевые значения.
        """
        token_counts = self.store.token_counts(strategy)
        sizes = size_stats(token_counts)
        sources = self.store.counts_by_source(strategy)
        path = self.path_for(strategy)
        return {
            "strategy": strategy,
            "chunks": sizes["count"],
            "tokens_total": sum(token_counts),
            "tokens_avg": sizes["avg"],
            "tokens_min": sizes["min"],
            "tokens_max": sizes["max"],
            "tokens_std": sizes["std"],
            "documents": len(sources),
            "sources": sources,
            "with_section": self.store.with_section(strategy),
            "histogram": histogram(token_counts),
            # Векторов против строк таблицы: расхождение (векторы есть, строк нет)
            # означает, что индекс и метаданные разошлись — например, индексы
            # записал другой процесс со своей БД. Раньше это выглядело просто как
            # «поиск ничего не нашёл», и причину приходилось искать руками.
            "index_vectors": self.index_size(strategy),
            "index_file": str(path) if path.exists() else None,
            "index_bytes": path.stat().st_size if path.exists() else 0,
        }

    def stats(self) -> Dict[str, dict]:
        """Статистика обеих стратегий (для таблицы сравнения)."""
        return {strategy.value: self.get_stats(strategy.value)
                for strategy in ChunkStrategy}

    # ---------- внутреннее ----------
    def _loaded_index(self, strategy: str):
        """Индекс стратегии из памяти или с диска (``None`` — индекса нет)."""
        if strategy not in self._indexes:
            path = self.path_for(strategy)
            if not path.exists():
                return None
            self.load_index(strategy, path=path)
        return self._indexes.get(strategy)

    def _ensure_index(self, strategy: str, dimension: int):
        """Индекс для записи: из памяти, с диска или новый с нужной размерностью."""
        index = self._loaded_index(strategy)
        if index is None:
            index = faiss.IndexIDMap2(faiss.IndexFlatIP(int(dimension)))
            self._indexes[strategy] = index
            logger.info("Индекс %s создан: размерность %d", strategy, dimension)
        elif int(index.d) != int(dimension):
            raise IndexNotBuiltError(
                f"Размерность индекса {strategy!r} ({index.d}) не совпадает с "
                f"размерностью модели ({dimension}): очистите индекс и постройте заново"
            )
        return index


def _preview(content: str) -> str:
    """Начало текста чанка — то, что показывают таблицы интерфейса и отчёта."""
    compact = " ".join(content.split())
    return compact[:PREVIEW_CHARS] + ("…" if len(compact) > PREVIEW_CHARS else "")


#: Единственная служба индексов процесса (ставится лениво при первом обращении).
_service: Optional[IndexService] = None
_service_lock = threading.Lock()


def get_index_service() -> IndexService:
    """Служба индексов процесса: одна на процесс (держит открытые файлы FAISS).

    Точка подмены для тестов: ``monkeypatch.setattr(main, "get_index_service", ...)``.
    """
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = IndexService()
    return _service
