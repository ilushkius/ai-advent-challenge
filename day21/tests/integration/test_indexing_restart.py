"""Перезапуск приложения: индексы читаются с диска, без повторной индексации (день 21).

Это сценарий 5 демонстрации, и он отвечает на главный эксплуатационный вопрос:
«надо ли индексировать заново после рестарта бэкенда». Ответ проверяется буквально —
новый сервис на тех же файлах и той же БД делает ``load_all``, после чего
статистика совпадает, поиск возвращает ТЕ ЖЕ чанки, а журнал запусков не получает
новой строки (то есть индексация не выполнялась).
"""
from backend.domain.index_scenarios import DEMO_QUERIES
from backend.services.index_service import IndexService
from backend.storage.index_run_store import IndexRunStore


def test_restart_reads_indexes_without_reindexing(index_service, indexing_service,
                                                  chunk_store, index_run_store):
    """После ``load_all`` поиск работает по тем же чанкам, а прогонов не прибавилось."""
    indexing_service.start_demo(background=False)
    query = DEMO_QUERIES[1]
    before_stats = index_service.stats()
    before_hits = [hit["chunk_id"] for hit in index_service.search(
        query.query, top_k=3, strategy="structural")]
    before_runs = index_run_store.list_runs()

    index_service.save_all()
    fresh = IndexService(embedder=index_service.embedder, store=chunk_store,
                         index_dir=index_service.path_for("fixed").parent)
    loaded = fresh.load_all()
    after_stats = fresh.stats()
    after_hits = [hit["chunk_id"] for hit in fresh.search(
        query.query, top_k=3, strategy="structural")]

    assert set(loaded) == {"fixed", "structural"}
    assert all(item["loaded"] for item in loaded.values())
    for strategy, item in loaded.items():
        assert item["vectors"] == after_stats[strategy]["chunks"]
    assert {name: entry["chunks"] for name, entry in after_stats.items()} == \
           {name: entry["chunks"] for name, entry in before_stats.items()}
    assert after_hits == before_hits
    assert len(index_run_store.list_runs()) == len(before_runs)


def test_restart_keeps_metrics_of_finished_run(indexing_service, session_factory):
    """Метрики прогона читаются после «перезапуска»: они лежат в БД, а не в памяти."""
    report = indexing_service.start_demo(background=False)
    fresh_store = IndexRunStore(session_factory=session_factory)
    restored = fresh_store.run(report["run_id"])
    assert restored["status"] == "completed"
    assert restored["metrics"]["comparison"] == report["metrics"]["comparison"]
    assert len(restored["metrics"]["queries"]) == 5


def test_index_files_live_beside_each_other(index_service, indexing_service):
    """Оба индекса — отдельные файлы в каталоге дня: их можно показать и скопировать."""
    indexing_service.start_demo(background=False)
    paths = {strategy: index_service.path_for(strategy)
             for strategy in ("fixed", "structural")}
    assert paths["fixed"].name == "fixed.index"
    assert paths["structural"].name == "structural.index"
    assert paths["fixed"].parent == paths["structural"].parent
    for path in paths.values():
        assert path.exists() and path.stat().st_size > 0
