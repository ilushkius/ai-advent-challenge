"""Служба индексации: запуск прогонов, прогресс, поиск, статистика, очистка.

Разделение обязанностей: ``Chunker`` знает, КАК резать документ, ``IndexService`` —
как положить векторы и метаданные, ``IndexRunner`` — этапы прогона, а
``IndexingService`` решает, КОГДА что запускать, что отдавать API, интерфейсу и
отчёту. Роутер ``/indexing``, Streamlit, скрипты и агент работают только с ней,
поэтому контракт отказов и чтения описан в одном месте.

Фоновый запуск. Кнопка «🚀 Запустить демо-индексацию» не может ждать окончания
работы: модель считает эмбеддинги десятками секунд. Поэтому строка запуска
создаётся ДО старта потока (гонки «запуск ещё не записан» нет), поток —
демонический, а терминальный статус ставит раннер при любом исходе.

Отказы — данные, а не исключения наружу: ``IndexingRejected`` несёт код причины
(``bad_strategy``, ``bad_query``, ``no_documents``, ``run_not_found``,
``index_empty``), и роутер переводит код в HTTP-статус в одном месте.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from shared.logging_utils import get_logger

from ..core import config
from ..domain.chunking import ChunkStrategy, resolve_strategy, strategy_values
from ..domain.index_scenarios import queries_as_dicts, validate_queries
from ..domain.indexing_fsm import IndexingState
from ..storage.index_run_store import IndexRunStore
from .document_loader import DocumentLoader, get_document_loader
from .index_service import IndexNotBuiltError, IndexService, get_index_service

logger = get_logger(__name__)

#: Коды причин отказа: контракт API (400 — запрос, 404 — запуск, 409 — пустой индекс).
REASON_BAD_STRATEGY = "bad_strategy"
REASON_BAD_QUERY = "bad_query"
REASON_NO_DOCUMENTS = "no_documents"
REASON_RUN_NOT_FOUND = "run_not_found"
REASON_INDEX_EMPTY = "index_empty"

#: Значение ``strategy`` для демо-прогона (колонка ``index_runs.strategy``).
DEMO_STRATEGY = "demo"

#: Значение ``strategy`` очистки: «обе стратегии сразу».
CLEAR_ALL = "all"


class IndexingRejected(Exception):
    """Отказ индексации с кодом причины: роутер переводит код в HTTP-статус."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(message)


class IndexingService:
    """Прогоны индексации: запуск, прогресс в БД, метрики, поиск и очистка."""

    def __init__(self, index_service: Optional[IndexService] = None,
                 loader: Optional[DocumentLoader] = None,
                 run_store: Optional[IndexRunStore] = None) -> None:
        self._index_service = index_service
        self._loader = loader
        self._run_store = run_store

    # ---------- зависимости ----------
    @property
    def index_service(self) -> IndexService:
        """Служба индексов: переданная или служба процесса."""
        if self._index_service is None:
            self._index_service = get_index_service()
        return self._index_service

    @property
    def loader(self) -> DocumentLoader:
        """Загрузчик документов: переданный или загрузчик процесса."""
        if self._loader is None:
            self._loader = get_document_loader()
        return self._loader

    @property
    def run_store(self) -> IndexRunStore:
        """Хранилище запусков: переданное или хранилище процесса."""
        if self._run_store is None:
            self._run_store = IndexRunStore()
        return self._run_store

    @property
    def runner(self) -> "IndexRunner":
        """Раннер этапов: собранный на зависимостях службы.

        Импорт внутри метода, а не на уровне модуля: ``index_runner`` берёт из этого
        модуля коды отказа и исключение, и импорт наверху замкнул бы цикл.
        """
        from .index_runner import IndexRunner

        return IndexRunner(self.index_service, self.loader, self.run_store)

    # ---------- запуск ----------
    def start_run(self, strategy: str, background: bool = True) -> dict:
        """Индексирует документы одной стратегией (без поиска и сравнения)."""
        resolved = self._resolve(strategy)
        run_id = self._create_run(resolved.value)
        strategies = [resolved]
        if background:
            self._spawn(run_id, strategies)
        else:
            self.runner.run(run_id, strategies)
        return self._started(run_id, resolved.value, background)

    def start_demo(self, background: bool = True) -> dict:
        """Демо-сценарий: обе стратегии, пять запросов и таблица сравнения.

        Тестовые запросы проверяются ДО создания запуска: их опечатка — ошибка
        данных, а не свойство стратегии, и увидеть её нужно сразу (400), а не как
        «recall 0» в отчёте.
        """
        errors = validate_queries()
        if errors:
            raise IndexingRejected(REASON_BAD_QUERY,
                                   "тестовые запросы некорректны: " + "; ".join(errors))
        run_id = self._create_run(DEMO_STRATEGY)
        strategies = list(ChunkStrategy)
        if background:
            self._spawn(run_id, strategies)
        else:
            self.runner.run(run_id, strategies)
        return self._started(run_id, DEMO_STRATEGY, background)

    def _create_run(self, strategy: str) -> int:
        """Строка запуска создаётся синхронно: прогресс виден с первого опроса."""
        run = self.run_store.create_run(
            strategy=strategy,
            status=IndexingState.LOADING.value,
            started_at=datetime.now(timezone.utc),
        )
        return int(run["id"])

    def _spawn(self, run_id: int, strategies: Sequence[ChunkStrategy]) -> None:
        """Запускает прогон в фоновом потоке (демон: не держит процесс)."""
        thread = threading.Thread(target=self._run_in_thread, args=(run_id, strategies),
                                  daemon=True, name=f"indexing-{run_id}")
        thread.start()
        logger.info("Индексация %s запущена в фоне (стратегии: %s)",
                    run_id, ", ".join(item.value for item in strategies))

    def _run_in_thread(self, run_id: int, strategies: Sequence[ChunkStrategy]) -> None:
        """Тело фонового потока: доменный отказ уже записан в строку запуска."""
        try:
            self.runner.run(run_id, strategies)
        except IndexingRejected as exc:
            logger.warning("Индексация %s отклонена в фоне: %s", run_id, exc.message)

    def _started(self, run_id: int, strategy: str, background: bool) -> dict:
        """Ответ запуска: при фоне — только номер и статус, при синхронном — метрики."""
        run = self.run_store.run(run_id) or {}
        return {
            "run_id": run_id,
            "strategy": strategy,
            "status": str(run.get("status") or IndexingState.LOADING.value),
            "background": background,
            "metrics": None if background else run.get("metrics"),
            "error": run.get("error"),
        }

    # ---------- чтение ----------
    def status(self) -> dict:
        """Последний запуск (его опрашивает прогресс-бар интерфейса)."""
        return {"run": self.run_store.latest()}

    def runs(self, limit: int = config.INDEX_RUNS_LIMIT) -> dict:
        """История запусков: свежие первыми."""
        runs = self.run_store.list_runs(limit=limit)
        return {"runs": runs, "count": len(runs)}

    def run(self, run_id: int) -> dict:
        """Отчёт о запуске: строка запуска и его метрики."""
        run = self.run_store.run(run_id)
        if run is None:
            raise IndexingRejected(REASON_RUN_NOT_FOUND,
                                   f"Запуск индексации {run_id} не найден")
        return {"run": run, "metrics": run.get("metrics") or {}}

    def stats(self) -> dict:
        """Статистика обеих стратегий (для таблицы сравнения и гистограмм)."""
        return self.index_service.stats()

    def index_size(self, strategy: str) -> int:
        """Сколько векторов в индексе стратегии (0 — индекса нет).

        Отдельный метод нужен агенту: он делает шаг поиска только при непустом
        индексе, и «индекс есть» — самый дешёвый способ это выяснить, без запроса
        к модели эмбеддингов.
        """
        resolved = self._resolve(strategy)
        return self.index_service.index_size(resolved.value)

    def chunks(self, strategy: str, limit: int = config.INDEX_DEFAULT_LIMIT) -> dict:
        """Примеры чанков стратегии для интерфейса и отчёта."""
        resolved = self._resolve(strategy)
        items = self.index_service.sample_chunks(resolved.value, limit=limit)
        return {"strategy": resolved.value, "chunks": items, "count": len(items)}

    def search(self, query: str, top_k: Optional[int] = None,
               strategy: str = config.INDEX_AGENT_STRATEGY) -> dict:
        """Поиск по индексу: пустой запрос и пустой индекс — понятный отказ."""
        text = str(query or "").strip()
        if not text:
            raise IndexingRejected(REASON_BAD_QUERY, "пустой запрос поиска")
        resolved = self._resolve(strategy)
        limit = max(1, min(int(top_k or config.INDEX_DEFAULT_TOP_K),
                           config.INDEX_MAX_TOP_K))
        try:
            results = self.index_service.search(text, top_k=limit,
                                                strategy=resolved.value)
        except IndexNotBuiltError as exc:
            raise IndexingRejected(REASON_INDEX_EMPTY, str(exc)) from exc
        return {"query": text, "strategy": resolved.value, "top_k": limit,
                "count": len(results), "results": results}

    def clear(self, strategy: str) -> dict:
        """Очищает индекс стратегии (``"all"`` — обе): память, файл и строки таблицы."""
        value = str(strategy or "").strip().lower()
        targets = (list(strategy_values()) if value == CLEAR_ALL
                   else [self._resolve(value).value])
        removed: dict[str, int] = {}
        for target in targets:
            removed.update(self.index_service.clear_index(target)["removed"])
        return {"strategy": value, "removed": removed}

    def queries(self) -> List[dict]:
        """Тестовые запросы с ожидаемыми источниками (для интерфейса и отчёта)."""
        return queries_as_dicts()

    def strategies(self) -> tuple[str, ...]:
        """Значения стратегий (для фильтров API и интерфейса)."""
        return strategy_values()

    def _resolve(self, strategy: str) -> ChunkStrategy:
        """Стратегия по строке или отказ с кодом ``bad_strategy``."""
        resolved = resolve_strategy(strategy)
        if resolved is None:
            raise IndexingRejected(
                REASON_BAD_STRATEGY,
                f"Неизвестная стратегия {strategy!r}: ожидается "
                f"{' или '.join(strategy_values())}",
            )
        return resolved


#: Единственная служба индексации процесса (ставится лениво при первом обращении).
_service: Optional[IndexingService] = None
_service_lock = threading.Lock()


def get_indexing_service() -> IndexingService:
    """Служба индексации процесса: одна на процесс.

    Точка подмены для тестов: ``monkeypatch.setattr(main, "get_indexing_service", ...)``.
    """
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = IndexingService()
    return _service
