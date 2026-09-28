"""Эмбеддинги чанков через sentence-transformers (день 21).

Модель загружается ЛЕНИВО: старт бэкенда и офлайн-тесты не должны тянуть torch
(его импорт — сотни миллибаллов и секунды работы), поэтому ``sentence_transformers``
импортируется внутри ``_load``, а не на импорте модуля. Греет модель отдельный
поток при старте приложения (``lifespan``): первая загрузка скачивает веса в
``index/models`` и занимает десятки секунд — блокировать старт бэкенда этим нельзя.

Параметры выбраны осознанно:

- модель по умолчанию — ``paraphrase-multilingual-MiniLM-L12-v2``: документы
  репозитория русскоязычные, а из доступных моделей понимает русский именно она;
- ``max_seq_length = 512`` — базовое значение модели (128 токенов) молча обрезало бы
  чанк в 512 токенов, и сравнение стратегий чанкинга потеряло бы смысл;
- ``normalize_embeddings = True`` — векторы приводятся к единичной длине, поэтому
  скалярное произведение в FAISS равно косинусной близости;
- батчи по ``EMBEDDING_BATCH_SIZE`` — компромисс памяти и скорости.

Вызовы сериализуются блокировкой: прогон индексации идёт в фоновом потоке, а
интерфейс может попросить поиск в тот же момент, и параллельный проход по модели
на одном процессе — лишняя нагрузка и нестабильные замеры времени.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional, Sequence

import numpy as np

from shared.logging_utils import get_logger

from ..core import config

logger = get_logger(__name__)


class EmbeddingError(Exception):
    """Модель эмбеддингов недоступна (нет сети, нет весов) — текст готов для UI."""


class EmbeddingService:
    """Модель эмбеддингов процесса: ленивая загрузка, батчи, нормализованные вектора."""

    def __init__(self, model_name: Optional[str] = None,
                 cache_dir: Optional[object] = None,
                 batch_size: Optional[int] = None,
                 max_seq_length: Optional[int] = None,
                 backend: Optional[object] = None) -> None:
        self._model_name = model_name or config.EMBEDDING_MODEL
        self._cache_dir = cache_dir if cache_dir is not None else config.INDEX_MODELS_DIR
        self._batch_size = max(1, int(batch_size or config.EMBEDDING_BATCH_SIZE))
        self._max_seq_length = int(max_seq_length or config.EMBEDDING_MAX_SEQ_LENGTH)
        self._backend = backend
        self._dimension = 0
        self._load_lock = threading.Lock()
        self._encode_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        """Имя модели (в отчёте и статистике — этот же текст)."""
        return self._model_name

    @property
    def loaded(self) -> bool:
        """Загружена ли модель прямо сейчас."""
        return self._backend is not None

    @property
    def dimension(self) -> int:
        """Размерность векторов (0 — модель ещё не загружена)."""
        return self._dimension

    def encode_one(self, text: str) -> np.ndarray:
        """Вектор одного текста формы ``(dim,)``, ``float32``, единичной длины."""
        return self.encode([text])[0]

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Векторы текстов формы ``(n, dim)``, ``float32``, единичной длины.

        Пустой вход даёт пустую матрицу ``(0, dim)``: вызывающий код не должен
        различать «текстов нет» и «модель не загружена» по исключению.
        """
        items = [str(text) for text in texts]
        self._load()
        if not items:
            return np.zeros((0, self._dimension), dtype=np.float32)
        batches: list[np.ndarray] = []
        with self._encode_lock:
            for start in range(0, len(items), self._batch_size):
                batch = items[start:start + self._batch_size]
                vectors = self._backend.encode(
                    batch,
                    batch_size=self._batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                batches.append(np.asarray(vectors, dtype=np.float32))
        matrix = np.vstack(batches).astype(np.float32)
        if self._dimension == 0 and matrix.shape[1]:
            self._dimension = int(matrix.shape[1])
        return matrix

    def warmup(self) -> bool:
        """Прогревает модель (скачивает веса) и не бросает исключений наружу.

        Прогрев идёт в демон-потоке старта приложения: его неудача не должна валить
        бэкенд — пользователь увидит понятную ошибку на первом прогоне индексации.
        """
        try:
            vector = self.encode_one("прогрев модели эмбеддингов")
        except Exception as exc:  # noqa: BLE001 — старт приложения важнее прогрева
            logger.warning("Модель эмбеддингов не прогрелась: %s", exc)
            return False
        logger.info("Модель эмбеддингов загружена: %s (размерность %d)",
                    self._model_name, vector.shape[0] if vector.size else self._dimension)
        return True

    def reset(self) -> None:
        """Забывает загруженную модель (нужно тестам между сценариями)."""
        self._backend = None
        self._dimension = 0

    def _load(self) -> None:
        """Загружает модель при первом обращении (или поставляет ошибку)."""
        if self._backend is not None:
            return
        with self._load_lock:
            if self._backend is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Загружаю модель эмбеддингов %s (кэш %s)",
                            self._model_name, self._cache_dir)
                model = SentenceTransformer(self._model_name,
                                            cache_folder=str(self._cache_dir))
                # Базовое значение этой модели — 128 токенов: молча обрезало бы чанки.
                model.max_seq_length = self._max_seq_length
            except Exception as exc:  # noqa: BLE001 — текст ошибки важен целиком
                # Подсказка про кэш неслучайна: оборванная загрузка оставляет
                # неполный снимок, и та же ошибка («Can't instantiate a tokenizer»,
                # «Unrecognized processing class») повторяется на каждом запуске,
                # пока каталог `index/models/` не будет удалён и скачан заново.
                raise EmbeddingError(
                    f"не удалось загрузить модель {self._model_name}: {exc}; "
                    "проверьте, что она скачана целиком (оборванная загрузка "
                    "лечится удалением index/models), задайте DAY21_EMBEDDING_MODEL "
                    "или используйте --stub-embedder"
                ) from exc
            self._backend = model
            self._dimension = _read_dimension(model)


def _read_dimension(model: object) -> int:
    """Размерность векторов модели (0 — модель её не сообщает).

    Новое имя метода (``get_embedding_dimension``) спрашивается первым, старое
    (``get_sentence_embedding_dimension``) — как запасное: sentence-transformers 6
    переименовал метод и предупреждает о будущем удалении старого.
    """
    for name in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
        reader = getattr(model, name, None)
        if reader is None:
            continue
        value = reader()
        if value:
            return int(value)
    return 0


#: Единственная служба эмбеддингов процесса (ставится лениво при первом обращении).
_service: Optional[EmbeddingService] = None
_service_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    """Служба эмбеддингов процесса: одна на процесс (модель весит сотни мегабайт).

    Точка подмены для тестов: ``monkeypatch.setattr(main, "get_embedding_service", ...)``.
    """
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EmbeddingService()
    return _service
