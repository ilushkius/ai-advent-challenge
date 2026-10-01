"""Реранкинг кандидатов RAG кросс-энкодером (день 23).

Второй этап отбора: гибридный поиск дня 22 отдаёт пул кандидатов, кросс-энкодер
считает пару «запрос, фрагмент» целиком (в отличие от би-энкодера эмбеддингов,
который кодирует текст заранее) и переставляет фрагменты по своему баллу.

Устройство повторяет ``embedding_service``: модель загружается ЛЕНИВО (импорт
``sentence_transformers`` — внутри ``_load``), вызовы сериализуются блокировкой,
служба одна на процесс. Греет модель общий демон-поток старта приложения.

Модель по умолчанию — ``cross-encoder/mmarco-mMiniLMv2-L12-H384-v1``: мультиязычная
(обучена на переводе MS MARCO, понимает русский), стандартная архитектура без
``trust_remote_code``, самая лёгкая из подходящих. Веса кэшируются в ``index/models``.
"""
from __future__ import annotations

import threading
from typing import Any, Optional, Sequence

from shared.logging_utils import get_logger

from ..core import config
from ..domain import rag_filter

logger = get_logger(__name__)


class RerankError(RuntimeError):
    """Сбой загрузки или вызова кросс-энкодера."""


class RerankService:
    """Кросс-энкодер реранкера: ленивая загрузка, батчи, баллы в ``[0, 1]``."""

    def __init__(self, model_name: Optional[str] = None,
                 cache_dir: Optional[object] = None,
                 batch_size: Optional[int] = None,
                 max_length: Optional[int] = None) -> None:
        self._model_name = model_name or rag_filter.RAG_RERANK_MODEL
        self._cache_dir = cache_dir if cache_dir is not None else config.INDEX_MODELS_DIR
        self._batch_size = max(1, int(batch_size or rag_filter.RAG_RERANK_BATCH_SIZE))
        self._max_length = int(max_length or rag_filter.RAG_RERANK_MAX_LENGTH)
        self._model = None
        self._load_lock = threading.Lock()
        self._call_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        """Имя модели реранкера (в отчёте и в разделе интерфейса)."""
        return self._model_name

    @property
    def loaded(self) -> bool:
        """Загружена ли модель прямо сейчас."""
        return self._model is not None

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Баллы релевантности текстов запросу — по одному на текст, в ``[0, 1]``.

        Пустой вход даёт пустой список без загрузки модели: вызывающему не нужно
        различать «текстов нет» и «модель недоступна» по исключению.
        """
        items = [str(text) for text in texts]
        if not items:
            return []
        model = self._load()
        try:
            with self._call_lock:
                raw = model.predict(self._pairs(str(query), items),
                                    batch_size=self._batch_size,
                                    convert_to_numpy=True,
                                    show_progress_bar=False)
        except Exception as exc:  # noqa: BLE001 — наружу идёт один тип ошибки
            raise RerankError(f"вызов реранкера не удался: {exc}") from exc
        return rag_filter.normalize_rerank_scores([float(value) for value in raw])

    def warmup(self) -> bool:
        """Прогревает модель (скачивает веса) и не бросает исключений наружу.

        Прогрев идёт в демон-потоке старта приложения: его неудача не должна валить
        бэкенд — фрагменты просто останутся в порядке дня 22.
        """
        try:
            self.score("прогрев", ["прогрев модели реранкера"])
        except Exception as exc:  # noqa: BLE001 — старт приложения важнее прогрева
            logger.warning("Модель реранкера не прогрелась: %s", exc)
            return False
        logger.info("Модель реранкера загружена: %s", self._model_name)
        return True

    def reset(self) -> None:
        """Забывает загруженную модель (нужно тестам и повторной загрузке)."""
        with self._load_lock:
            self._model = None

    def _load(self) -> Any:
        """Загружает модель при первом обращении (или поставляет ``RerankError``)."""
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder

                logger.info("Загружаю модель реранкера %s (кэш %s)",
                            self._model_name, self._cache_dir)
                model = CrossEncoder(self._model_name, cache_folder=str(self._cache_dir))
                # Имя свойства в 6.1.0 переименовано: max_length — устаревший псевдоним.
                model.max_seq_length = self._max_length
            except Exception as exc:  # noqa: BLE001 — текст ошибки важен целиком
                # Подсказка про кэш неслучайна: оборванная загрузка оставляет
                # неполный снимок, и та же ошибка повторяется на каждом запуске,
                # пока каталог `index/models/` не будет удалён и скачан заново.
                raise RerankError(
                    f"не удалось загрузить модель реранкера {self._model_name}: {exc}; "
                    "проверьте, что она скачана целиком (оборванная загрузка "
                    "лечится удалением index/models) или задайте RAG_RERANK_MODEL"
                ) from exc
            self._model = model
            return model

    def _pairs(self, query: str, texts: Sequence[str]) -> list[tuple[str, str]]:
        """Пары «запрос, фрагмент» для кросс-энкодера (пустой текст остаётся пустым)."""
        return [(str(query), str(text)) for text in texts]


#: Единственная служба реранкера процесса (ставится лениво при первом обращении).
_service: Optional[RerankService] = None
_service_lock = threading.Lock()


def get_rerank_service() -> RerankService:
    """Служба реранкера процесса: одна на процесс (модель весит сотни мегабайт)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = RerankService()
    return _service
