"""Пять сценариев проверки индексации документов (день 21).

Сценарии — это доказательства дня, и каждый проверяет СОДЕРЖАТЕЛЬНОЕ утверждение,
а не факт запуска:

1. **полный демо-прогон** — обе стратегии дали непустые индексы, статус
   ``completed``, метрики сравнения и результаты пяти тестовых запросов на месте;
2. **одиночная стратегия** — индексация только ``fixed``: чанки есть, файл индекса
   создан, запуск завершён;
3. **поиск** — запрос из домена даёт непустой результат с метаданными, а порядок
   попаданий не нарушает убывания оценки;
4. **качество поиска** — один запрос на обеих стратегиях: печатаются топ-3 и
   precision@3 по ожидаемым источникам (ground truth из домена);
5. **перезапуск** — новый сервис на тех же БД и файлах индексов: ``load_all``
   находит оба индекса, статистика не меняется, поиск даёт те же ``chunk_id`` —
   то есть перезапуск НЕ требует повторной индексации.

Прогон идёт на **той же БД, что приложение** (``day21/agents.db``) и на тех же
файлах ``index/*.index``: векторы лежат в общих файлах, поэтому метаданные обязаны
быть в общей таблице — иначе запущенный бэкенд прочитает чужие векторы и не найдёт
к ним строк (поиск вернёт пустой список при непустом индексе, а расхождение видно
по ``chunks`` против ``index_vectors`` в ``GET /indexing/stats``). Рабочую БД стенд
не удаляет — воспроизводимость даёт очистка индексов при создании стенда.

Флаг ``--stub-embedder`` подменяет модель детерминированным хеш-эмбеддером: прогон и
отчёт собираются офлайн, без скачивания весов. Качество поиска при этом НЕ
показательно — и это печатается в выводе и в отчёте.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня
# и в корне репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import numpy as np  # noqa: E402

from backend.core import config  # noqa: E402
from backend.domain.document_sources import DOCUMENT_SOURCES  # noqa: E402
from backend.domain.index_scenarios import DEMO_QUERIES  # noqa: E402
from backend.services.document_loader import DocumentLoader  # noqa: E402
from backend.services.index_service import IndexService  # noqa: E402
from backend.services.indexing_service import IndexingService  # noqa: E402
from backend.storage.chunk_store import ChunkStore  # noqa: E402
from backend.storage.database import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)
from backend.storage.index_run_store import IndexRunStore  # noqa: E402

#: Каталог индексов прогона — рабочий каталог дня (его читает и сценарий 5, и API).
INDEX_DIR = DAY_ROOT / "index"
#: Каталог документов прогона — тоже рабочий: его собирает загрузчик.
DOCUMENTS_DIR = DAY_ROOT / "documents"

#: Подпись заглушки: она печатается в выводе и в отчёте, чтобы числа не приняли
#: за качество настоящей модели.
STUB_MODEL_NAME = "заглушка: hash-64 (качество поиска не показательно)"


class HashEmbedder:
    """Детерминированный эмбеддер-заглушка: одинаковый текст → одинаковый вектор.

    Нужен для офлайн-прогона: настоящая модель требует сети и сотен мегабайт весов.
    Векторы строятся из SHA-256 текста (байты хеша → компоненты) и приводятся к
    единичной длине, поэтому FAISS с внутренним произведением считает косинус —
    ровно так же, как с настоящей моделью. Осмысленной семантики у таких векторов
    нет: поиск находит совпадения по токенам текста, а не по смыслу.
    """

    dimension = 64
    model_name = STUB_MODEL_NAME

    @property
    def loaded(self) -> bool:
        """Заглушка «загружена» всегда: грузить нечего."""
        return True

    def encode(self, texts):
        """Векторы текстов формы ``(n, 64)``, ``float32``, единичной длины."""
        items = [str(text) for text in texts]
        if not items:
            return np.zeros((0, self.dimension), dtype=np.float32)
        rows = []
        for text in items:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = np.frombuffer(digest * (self.dimension // len(digest) + 1),
                                dtype=np.uint8)[:self.dimension].astype(np.float32)
            vector = raw - 128.0
            norm = float(np.linalg.norm(vector)) or 1.0
            rows.append(vector / norm)
        return np.vstack(rows).astype(np.float32)

    def encode_one(self, text: str):
        """Вектор одного текста формы ``(64,)``."""
        return self.encode([text])[0]

    def warmup(self) -> bool:
        """Прогрев не нужен: модель уже «готова»."""
        return True

    def reset(self) -> None:
        """Сброс состояния (у заглушки его нет)."""


@dataclass
class ScenarioResult:
    """Итог одного сценария: имя, признак успеха, вывод и собранные данные."""

    name: str
    ok: bool
    details: str = ""
    data: dict = field(default_factory=dict)


class DemoStand:
    """Стенд прогона: БД дня, документы дня и оба сервиса индексации.

    Стенд работает на **той же БД, что приложение** (``config.DB_PATH`` →
    ``day21/agents.db``) и на тех же файлах ``index/*.index``. Разделять их нельзя:
    векторы лежат в общих файлах, а метаданные — в таблице, и если прогон запишет
    метаданные в другую БД, запущенное приложение прочитает чужие векторы и не
    найдёт к ним строк: поиск вернёт пустой список при непустом индексе (видно по
    расхождению ``chunks`` и ``index_vectors`` в ``GET /indexing/stats``).

    Рабочую БД стенд не удаляет (в ней диалоги, задачи и профили пользователя) —
    воспроизводимость даёт очистка индексов при создании стенда: она уносит и
    строки стратегий, поэтому число чанков в прогоне не зависит от прошлых.
    """

    def __init__(self, embedder=None, *,
                 documents_dir: Path | None = None) -> None:
        self.engine = make_engine(config.DATABASE_URL)
        init_db(self.engine)
        self.session_factory = make_session_factory(self.engine)
        self.embedder = embedder if embedder is not None else HashEmbedder()
        self.documents_dir = Path(documents_dir or DOCUMENTS_DIR)
        self.loader = DocumentLoader(documents_dir=self.documents_dir,
                                     sources=DOCUMENT_SOURCES)
        self._stores = []
        self.index_service, self.indexing_service = self._build()
        # Файлы индексов обязаны соответствовать БД: прогон начинается с чистых
        # файлов — тот же шаг, что делает кнопка «🧹 Очистить обе стратегии».
        for strategy in ("fixed", "structural"):
            self.index_service.clear_index(strategy)

    def _build(self) -> tuple[IndexService, IndexingService]:
        """Собирает пару служб на общей БД и рабочих файлах индексов."""
        index_service = IndexService(embedder=self.embedder,
                                     store=self._store(),
                                     index_dir=INDEX_DIR)
        indexing_service = IndexingService(index_service=index_service,
                                          loader=self.loader,
                                          run_store=self._run_store())
        return index_service, indexing_service

    def _store(self) -> ChunkStore:
        """Хранилище чанков на БД стенда (список держит ссылки живыми)."""
        store = ChunkStore(session_factory=self.session_factory)
        self._stores.append(store)
        return store

    def _run_store(self) -> IndexRunStore:
        """Хранилище запусков на БД стенда."""
        store = IndexRunStore(session_factory=self.session_factory)
        self._stores.append(store)
        return store

    def new_services(self) -> tuple[IndexService, IndexingService]:
        """Новые службы на тех же БД и файлах — проверка перезапуска (сценарий 5)."""
        return self._build()


def scenario_demo_full(stand: DemoStand) -> ScenarioResult:
    """Сценарий 1: полный демо-прогон обеих стратегий с поиском и сравнением."""
    report = stand.indexing_service.start_demo(background=False)
    metrics = report.get("metrics") or {}
    fixed = stand.index_service.get_stats("fixed")
    structural = stand.index_service.get_stats("structural")
    queries = metrics.get("queries") or []
    checks = {
        "статус completed": report.get("status") == "completed",
        "fixed непуст": fixed["chunks"] > 0,
        "structural непуст": structural["chunks"] > 0,
        "таблица сравнения непуста": len(metrics.get("comparison") or []) > 1,
        "пять запросов с попаданиями": len(queries) == 5 and all(
            (entry.get("fixed") or {}).get("hits") for entry in queries),
    }
    return ScenarioResult(
        name="1. Полный демо-прогон",
        ok=all(checks.values()),
        details=(f"fixed: {fixed['chunks']} чанков (средний {fixed['tokens_avg']}), "
                 f"structural: {structural['chunks']} чанков "
                 f"(средний {structural['tokens_avg']}); "
                 f"запросов: {len(queries)}; "
                 + "; ".join(f"{name} — {'ок' if ok else 'НЕТ'}"
                             for name, ok in checks.items())),
        data={"report": report, "fixed": fixed, "structural": structural},
    )


def scenario_single_strategy(stand: DemoStand) -> ScenarioResult:
    """Сценарий 2: индексация только одной стратегии (``fixed``)."""
    cleared = stand.index_service.clear_index("fixed")
    report = stand.indexing_service.start_run("fixed", background=False)
    stats = stand.index_service.get_stats("fixed")
    path = stand.index_service.path_for("fixed")
    checks = {
        "статус completed": report.get("status") == "completed",
        "чанки есть": stand.index_service.store.count("fixed") > 0,
        "файл индекса создан": path.exists() and path.stat().st_size > 0,
        "векторов столько же, сколько чанков": (
            stand.index_service.index_size("fixed") == stats["chunks"]),
    }
    return ScenarioResult(
        name="2. Одиночная стратегия (fixed)",
        ok=all(checks.values()),
        details=(f"очищено чанков: {cleared['removed'].get('fixed', 0)}, "
                 f"проиндексировано: {stats['chunks']}, "
                 f"файл {path.name} ({stats['index_bytes']} байт); "
                 + "; ".join(f"{name} — {'ок' if ok else 'НЕТ'}"
                             for name, ok in checks.items())),
        data={"report": report, "stats": stats, "cleared": cleared},
    )


def scenario_search(stand: DemoStand) -> ScenarioResult:
    """Сценарий 3: поиск по индексу — непустой результат с метаданными и порядком."""
    query = DEMO_QUERIES[0]
    report = stand.indexing_service.search(query.query, top_k=3, strategy="structural")
    results = report.get("results") or []
    scores = [float(hit.get("score") or 0.0) for hit in results]
    checks = {
        "попадания есть": bool(results),
        "метаданные заполнены": all(hit.get("source") and hit.get("chunk_id")
                                    and hit.get("content") for hit in results),
        "оценки не возрастают": all(scores[i] >= scores[i + 1]
                                    for i in range(len(scores) - 1)),
        "запрошено три попадания": len(results) <= 3,
    }
    return ScenarioResult(
        name="3. Поиск по индексу",
        ok=all(checks.values()),
        details=(f"«{query.query}» → {len(results)} попаданий: "
                 + ", ".join(f"{hit['source']} ({hit['score']:.3f})"
                             for hit in results)
                 + "; " + "; ".join(f"{name} — {'ок' if ok else 'НЕТ'}"
                                    for name, ok in checks.items())),
        data={"report": report,
              "query": {"query": query.query, "note": query.note,
                        "expected_sources": list(query.expected_sources)}},
    )


def scenario_compare_quality(stand: DemoStand) -> ScenarioResult:
    """Сценарий 4: качество поиска одного запроса на обеих стратегиях."""
    query = DEMO_QUERIES[2]
    expected = set(query.expected_sources)
    per_strategy: dict[str, dict] = {}
    for strategy in ("fixed", "structural"):
        report = stand.indexing_service.search(query.query, top_k=3,
                                               strategy=strategy)
        hits = report["results"]
        relevant = sum(1 for hit in hits if hit["source"] in expected)
        per_strategy[strategy] = {
            "hits": hits,
            "precision_at_3": round(relevant / len(hits), 4) if hits else 0.0,
            "relevant_total": stand.index_service.store.chunks_by_sources(
                strategy, query.expected_sources),
        }
    checks = {
        "обе стратегии что-то нашли": all(entry["hits"]
                                          for entry in per_strategy.values()),
        "источники попаданий известны": all(
            hit["source"] for entry in per_strategy.values() for hit in entry["hits"]),
    }
    details = "; ".join(
        f"{strategy}: precision@3 {entry['precision_at_3']} "
        f"(релевантных в индексе {entry['relevant_total']}), топ: "
        + ", ".join(f"{hit['source']}" for hit in entry["hits"])
        for strategy, entry in per_strategy.items())
    return ScenarioResult(
        name="4. Качество поиска: обе стратегии",
        ok=all(checks.values()),
        details=(f"«{query.query}» (ожидались {', '.join(query.expected_sources)}): "
                 + details),
        data={"query": {"query": query.query, "note": query.note,
                        "expected_sources": list(query.expected_sources)},
              "fixed": per_strategy["fixed"], "structural": per_strategy["structural"]},
    )


def scenario_restart(stand: DemoStand) -> ScenarioResult:
    """Сценарий 5: перезапуск приложения — индексы читаются с диска, без индексации."""
    before = stand.index_service.stats()
    query = DEMO_QUERIES[1]
    before_hits = stand.indexing_service.search(query.query, top_k=3,
                                                strategy="structural")["results"]
    fresh_index, fresh_indexing = stand.new_services()
    loaded = fresh_index.load_all()
    after = fresh_index.stats()
    after_hits = fresh_indexing.search(query.query, top_k=3,
                                       strategy="structural")["results"]
    checks = {
        "оба индекса прочитаны": all(item["loaded"] and item["vectors"] > 0
                                     for item in loaded.values()),
        "статистика не изменилась": (
            [entry["chunks"] for entry in before.values()]
            == [entry["chunks"] for entry in after.values()]),
        "поиск даёт те же чанки": ([hit["chunk_id"] for hit in before_hits]
                                   == [hit["chunk_id"] for hit in after_hits]),
    }
    return ScenarioResult(
        name="5. Перезапуск без переиндексации",
        ok=all(checks.values()),
        details=("прочитано векторов: "
                 + ", ".join(f"{name} {item['vectors']}"
                             for name, item in loaded.items())
                 + f"; статистика до: {before['structural']['chunks']} чанков, "
                   f"после: {after['structural']['chunks']}; "
                 + "; ".join(f"{name} — {'ок' if ok else 'НЕТ'}"
                             for name, ok in checks.items())),
        data={"loaded": loaded, "before": before, "after": after,
              "query": {"query": query.query, "note": query.note,
                        "expected_sources": list(query.expected_sources)},
              "hits": after_hits},
    )


#: Сценарии в порядке прогона (сценарий 5 зависит от файлов сценария 1).
SCENARIOS = (
    scenario_demo_full,
    scenario_single_strategy,
    scenario_search,
    scenario_compare_quality,
    scenario_restart,
)


def run_all(stand: DemoStand, *, echo=print) -> list[ScenarioResult]:
    """Выполняет все пять сценариев и печатает трассировку каждого шага."""
    results: list[ScenarioResult] = []
    for scenario in SCENARIOS:
        echo("")
        echo(f"=== {scenario.__name__} ===")
        result = scenario(stand)
        echo(("OK   " if result.ok else "FAIL ") + result.name)
        echo("      " + result.details)
        results.append(result)
    return results


def print_summary(results: list[ScenarioResult], *, echo=print) -> None:
    """Итог прогона: сколько проверок пройдено и какие упали."""
    passed = sum(1 for result in results if result.ok)
    echo("")
    echo(f"проверок пройдено: {passed}/{len(results)}")
    for result in results:
        if not result.ok:
            echo(f"  НЕ ПРОШЁЛ: {result.name} — {result.details}")
