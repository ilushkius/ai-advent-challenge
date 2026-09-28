"""Служба индексации: демо-прогон, одиночная стратегия, отказы и фон (день 21).

Проверяется то, что видит пользователь: этапы прогона идут по стейт-машине и
записываются в строку запуска, счётчики доходят до итоговых значений, метрики
сравнения и результаты пяти запросов на месте, а отказы приходят КОДОМ причины
(а не исключением библиотеки). Отдельно проверяется фоновый запуск: ответ приходит
сразу, а терминальный статус всё равно наступает.
"""
import time

import pytest

from backend.domain.index_scenarios import DEMO_QUERIES
from backend.services.document_loader import DocumentLoader
from backend.services.indexing_service import (
    IndexingRejected,
    IndexingService,
    REASON_BAD_QUERY,
    REASON_BAD_STRATEGY,
    REASON_INDEX_EMPTY,
    REASON_NO_DOCUMENTS,
    REASON_RUN_NOT_FOUND,
)
from backend.services.index_service import IndexService
from backend.storage.index_run_store import IndexRunStore
from indexing_fakes import FakeEmbedder


def _wait_finished(service, run_id, timeout: float = 30.0) -> dict:
    """Ждёт терминального статуса фонового прогона (для проверки фонового пути)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = service.run(run_id)["run"]
        if run["status"] in ("completed", "failed"):
            return run
        time.sleep(0.02)
    raise AssertionError(f"прогон {run_id} не завершился за {timeout} с")


# ---------- демо-прогон ----------
def test_demo_run_completes_with_metrics(indexing_service):
    """Демо-прогон: обе стратегии, метрики сравнения и пять запросов с попаданиями."""
    report = indexing_service.start_demo(background=False)
    assert report["status"] == "completed"
    assert report["error"] is None
    metrics = report["metrics"]
    assert len(metrics["comparison"]) > 1
    assert len(metrics["queries"]) == 5
    assert all(entry["fixed"]["hits"] for entry in metrics["queries"])
    assert all(entry["structural"]["hits"] for entry in metrics["queries"])
    for strategy in ("fixed", "structural"):
        assert metrics[strategy]["stats"]["chunks"] > 0
        assert metrics[strategy]["coverage"] > 0
        assert metrics[strategy]["timing"]["embed_ms"] >= 0
    assert metrics["embedding_model"] == indexing_service.index_service.embedder.model_name


@pytest.mark.slow
def test_demo_run_counts_and_stages(indexing_service, monkeypatch):
    """Счётчики доходят до итоговых, а этапы пишутся по FSM и в правильном порядке."""
    stages: list[str] = []
    original = IndexRunStore.update_progress

    def spy(self, run_id, **fields):
        if fields.get("status"):
            stages.append(fields["status"])
        return original(self, run_id, **fields)

    monkeypatch.setattr(IndexRunStore, "update_progress", spy)
    report = indexing_service.start_demo(background=False)
    run = indexing_service.run(report["run_id"])["run"]
    # Терминальный «completed» пишется вместе с метриками (finish_run), а не этапом:
    # иначе читатель увидел бы «завершено» без метрик.
    assert stages == ["chunking", "embedding", "indexing", "searching", "comparing"]
    assert run["status"] == "completed"
    assert run["documents_total"] == run["documents_done"] == 3
    assert run["chunks_fixed"] > 0 and run["chunks_structural"] > 0
    assert run["embeddings_total"] == run["embeddings_done"]
    assert run["embeddings_total"] >= run["chunks_fixed"] + run["chunks_structural"]
    assert run["finished_at"] and run["duration_ms"] >= 0


@pytest.mark.slow
def test_demo_run_indexes_both_strategies(indexing_service):
    """После демо-прогона поиск работает по обеим стратегиям."""
    indexing_service.start_demo(background=False)
    for strategy in ("fixed", "structural"):
        assert indexing_service.index_size(strategy) > 0
        hits = indexing_service.search("раздел про чанкинг", top_k=2,
                                       strategy=strategy)["results"]
        assert hits
        assert all(hit["source"] for hit in hits)


@pytest.mark.slow
def test_demo_metrics_have_quality_per_query(indexing_service):
    """По каждому запросу видно ожидаемые источники и сколько их чанков в индексе."""
    metrics = indexing_service.start_demo(background=False)["metrics"]
    for entry, query in zip(metrics["queries"], DEMO_QUERIES):
        assert entry["query"] == query.query
        assert entry["expected_sources"] == list(query.expected_sources)
        for strategy in ("fixed", "structural"):
            assert entry[strategy]["relevant_total"] >= 0
            for hit in entry[strategy]["hits"]:
                assert hit["score"] <= 1.0001


# ---------- одиночная стратегия ----------
def test_single_strategy_run_has_no_comparison(indexing_service, monkeypatch):
    """Одиночный прогон завершается без поиска и сравнения: сравнивать нечего."""
    stages: list[str] = []
    original = IndexRunStore.update_progress

    def spy(self, run_id, **fields):
        if fields.get("status"):
            stages.append(fields["status"])
        return original(self, run_id, **fields)

    monkeypatch.setattr(IndexRunStore, "update_progress", spy)
    report = indexing_service.start_run("fixed", background=False)
    assert report["status"] == "completed"
    assert stages == ["chunking", "embedding", "indexing"]
    assert "comparison" not in report["metrics"]
    assert "structural" not in report["metrics"]
    assert report["metrics"]["fixed"]["stats"]["chunks"] > 0


def test_run_rejects_unknown_strategy(indexing_service):
    """Неизвестная стратегия — отказ с кодом ``bad_strategy``."""
    with pytest.raises(IndexingRejected) as exc:
        indexing_service.start_run("окно", background=False)
    assert exc.value.reason_code == REASON_BAD_STRATEGY


# ---------- отказы ----------
def test_search_requires_query(indexing_service):
    """Пустой запрос поиска — отказ с кодом ``bad_query``."""
    with pytest.raises(IndexingRejected) as exc:
        indexing_service.search("   ")
    assert exc.value.reason_code == REASON_BAD_QUERY


def test_search_on_empty_index_is_rejected(indexing_service):
    """Поиск до индексации — отказ с кодом ``index_empty`` (роутер отвечает 409)."""
    with pytest.raises(IndexingRejected) as exc:
        indexing_service.search("что угодно", strategy="structural")
    assert exc.value.reason_code == REASON_INDEX_EMPTY


def test_unknown_run_is_rejected(indexing_service):
    """Неизвестный номер запуска — отказ с кодом ``run_not_found`` (404)."""
    with pytest.raises(IndexingRejected) as exc:
        indexing_service.run(999)
    assert exc.value.reason_code == REASON_RUN_NOT_FOUND


def test_no_documents_is_rejected(tmp_path, index_service, index_run_store):
    """Пустая папка документов и пустой список источников — отказ ``no_documents``."""
    loader = DocumentLoader(documents_dir=tmp_path / "empty", sources=())
    service = IndexingService(index_service=index_service, loader=loader,
                              run_store=index_run_store)
    with pytest.raises(IndexingRejected) as exc:
        service.start_demo(background=False)
    assert exc.value.reason_code == REASON_NO_DOCUMENTS
    run = service.runs()["runs"][0]
    assert run["status"] == "failed" and "документов" in run["error"]


def test_embedder_failure_lands_in_run_error(index_service, document_loader,
                                             index_run_store):
    """Сбой модели эмбеддингов не бросает исключение наружу, а виден в строке запуска."""
    class BrokenEmbedder(FakeEmbedder):
        def encode(self, texts):
            raise RuntimeError("нет сети")

    broken = IndexService(embedder=BrokenEmbedder(), store=index_service.store,
                          index_dir=index_service.path_for("fixed").parent)
    service = IndexingService(index_service=broken, loader=document_loader,
                              run_store=index_run_store)
    report = service.start_demo(background=False)
    assert report["status"] == "failed"
    assert "нет сети" in report["error"]
    run = service.run(report["run_id"])["run"]
    assert run["status"] == "failed" and run["finished_at"]


# ---------- фон и чтение ----------
@pytest.mark.slow
def test_background_run_finishes(indexing_service):
    """Фоновый запуск отвечает сразу, а терминальный статус всё равно наступает."""
    report = indexing_service.start_demo(background=True)
    assert report["background"] is True
    assert report["metrics"] is None
    assert report["status"] in ("loading", "chunking", "embedding", "indexing",
                               "searching", "comparing")
    run = _wait_finished(indexing_service, report["run_id"])
    assert run["status"] == "completed"
    assert run["metrics"] and run["metrics"]["comparison"]


def test_status_returns_latest_run(indexing_service):
    """``status`` отдаёт последний запуск, а без прогонов — ``None``."""
    assert indexing_service.status() == {"run": None}
    report = indexing_service.start_run("structural", background=False)
    assert indexing_service.status()["run"]["id"] == report["run_id"]


@pytest.mark.slow
def test_runs_history_is_newest_first(indexing_service):
    """История запусков идёт от свежих к старым и считает их число."""
    first = indexing_service.start_run("fixed", background=False)["run_id"]
    second = indexing_service.start_run("structural", background=False)["run_id"]
    payload = indexing_service.runs()
    assert [run["id"] for run in payload["runs"]] == [second, first]
    assert payload["count"] == 2


def test_chunks_endpoint_payload(indexing_service):
    """Примеры чанков отдаются стратегией и с числом записей."""
    indexing_service.start_run("structural", background=False)
    payload = indexing_service.chunks("structural", limit=2)
    assert payload["strategy"] == "structural"
    assert payload["count"] == len(payload["chunks"]) == 2
    assert all(chunk["strategy"] == "structural" for chunk in payload["chunks"])


@pytest.mark.slow
def test_search_caps_top_k(indexing_service):
    """Слишком большой ``top_k`` зажимается сверху пределом дня."""
    indexing_service.start_demo(background=False)
    payload = indexing_service.search("чанкинг", top_k=999, strategy="structural")
    assert payload["top_k"] <= 20


def test_clear_removes_strategy(indexing_service):
    """Очистка одной стратегии убирает её чанки, но не трогает вторую."""
    indexing_service.start_demo(background=False)
    payload = indexing_service.clear("fixed")
    assert payload["removed"]["fixed"] > 0
    assert indexing_service.index_size("fixed") == 0
    assert indexing_service.index_size("structural") > 0


def test_clear_all_removes_both(indexing_service):
    """``all`` очищает обе стратегии сразу."""
    indexing_service.start_demo(background=False)
    payload = indexing_service.clear("all")
    assert set(payload["removed"]) == {"fixed", "structural"}
    assert indexing_service.index_size("fixed") == 0
    assert indexing_service.index_size("structural") == 0


def test_clear_rejects_unknown_strategy(indexing_service):
    """Очистка неизвестной стратегии — отказ ``bad_strategy``."""
    with pytest.raises(IndexingRejected) as exc:
        indexing_service.clear("всё")
    assert exc.value.reason_code == REASON_BAD_STRATEGY


def test_queries_are_exposed_for_ui(indexing_service):
    """Тестовые запросы отдаются наружу: их показывает интерфейс и берёт отчёт."""
    payload = indexing_service.queries()
    assert len(payload) == 5
    assert payload[0]["expected_sources"]


def test_stats_are_available_before_any_run(indexing_service):
    """Статистика доступна и до первого прогона: интерфейсу нужна таблица сразу."""
    stats = indexing_service.stats()
    assert stats["fixed"]["chunks"] == 0 and stats["structural"]["chunks"] == 0
