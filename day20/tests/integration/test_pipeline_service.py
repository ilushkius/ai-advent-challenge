"""Тесты службы пайплайнов (день 19): фоновый запуск, отчёт, история, удаление.

Служба — это то, чем пользуются API и агент, поэтому проверяется её контракт:
фоновый запуск возвращается сразу со статусом ``running`` и записью в БД, прогон
доходит до терминального статуса, ``report`` объясняет остановку (номер шага, текст
ошибки, сообщение условия), а исчезнувший запуск — это отказ с кодом ``not_found``,
а не пустой ответ.
"""

import time

import pytest

from backend.domain.pipeline_spec import (
    DEFAULT_PIPELINE,
    MSG_COMPLETED,
    MSG_NO_DATA,
    MSG_RUNNING,
    REASON_NOT_FOUND,
    PipelineRejected,
)
from backend.services.pipeline import Pipeline
from backend.services.pipeline_service import PipelineService

ARGUMENTS = {
    "query": "RAG",
    "source": "file:notes.md",
    "limit": 5,
    "style": "short",
    "max_length": 600,
    "filename": "run.md",
    "format": "md",
}

#: Сколько ждать терминального статуса фонового прогона (фейковые инструменты
#: отвечают мгновенно, так что этого запаса хватает с большим избытком).
WAIT_SECONDS = 5.0


def _wait_terminal(service: PipelineService, run_id: int) -> dict:
    """Ждёт терминального статуса запуска и возвращает его отчёт."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        report = service.report(run_id)
        if report["run"]["status"] != "running":
            return report
        time.sleep(0.05)
    raise AssertionError(f"прогон {run_id} не завершился за {WAIT_SECONDS} с")


def test_sync_start_returns_full_report(pipeline_service):
    """``background=False`` выполняет прогон в запросе и отдаёт все шаги сразу."""
    report = pipeline_service.start_pipeline(None, dict(ARGUMENTS), background=False)
    assert report["background"] is False
    assert report["status"] == "completed"
    assert report["message"] == MSG_COMPLETED
    assert [step["tool_name"] for step in report["steps"]] == [
        "search", "summarize", "save_to_file"]


def test_background_start_records_run_and_finishes(pipeline_service, pipeline_store):
    """Фоновый запуск виден сразу со статусом running и доходит до терминального."""
    started = pipeline_service.start_pipeline(None, dict(ARGUMENTS), background=True)
    assert started["background"] is True
    assert started["status"] == "running" and started["message"] == MSG_RUNNING
    assert started["steps"] == [] and started["count"] == 0
    # Строка запуска создаётся ДО старта потока, поэтому она уже есть в БД — это и
    # есть гонка, которой не должно быть: интерфейс опрашивает статус сразу.
    assert pipeline_store.run(started["run_id"]) is not None

    report = _wait_terminal(pipeline_service, started["run_id"])
    assert report["run"]["status"] == "completed"
    assert report["count"] == 3
    assert report["message"] == MSG_COMPLETED


def test_report_explains_early_stop(pipeline_service, pipeline_registry):
    """Досрочное завершение объясняется сообщением условия и не выглядит ошибкой."""
    pipeline_registry.client.results = {
        "search": {"count": 0, "items": [], "source_kind": "file", "source": "notes.md"},
    }
    report = pipeline_service.start_pipeline(None, dict(ARGUMENTS), background=False)
    assert report["status"] == "stopped"
    detail = pipeline_service.report(report["run_id"])
    assert detail["failed_at_step"] is None
    assert detail["error"] is None
    assert detail["message"] == MSG_NO_DATA


def test_report_explains_failed_step(pipeline_registry, pipeline_service):
    """Ошибка шага видна в отчёте номером шага и текстом причины."""
    pipeline_registry.client.errors = {"summarize": "Стиль «exotic» не поддержан"}
    started = pipeline_service.start_pipeline(
        None, {**ARGUMENTS, "style": "exotic"}, background=False)
    detail = pipeline_service.report(started["run_id"])
    assert detail["run"]["status"] == "failed"
    assert detail["failed_at_step"] == 1
    assert "exotic" in detail["error"]


def test_history_filters_by_status(pipeline_service, pipeline_registry):
    """История отдаёт свежие запуски первыми и умеет фильтровать по статусу."""
    pipeline_service.start_pipeline(None, dict(ARGUMENTS), background=False)
    pipeline_registry.client.errors = {"summarize": "Стиль «exotic» не поддержан"}
    pipeline_service.start_pipeline(None, {**ARGUMENTS, "style": "exotic"},
                                    background=False)

    everything = pipeline_service.list_runs()
    assert everything["count"] == 2
    assert [run["id"] for run in everything["runs"]] == [2, 1]
    failed = pipeline_service.list_runs(status="failed")
    assert failed["count"] == 1 and failed["runs"][0]["status"] == "failed"
    assert pipeline_service.list_runs(status="completed")["count"] == 1
    assert pipeline_service.list_runs(limit=1)["count"] == 1


def test_steps_of_missing_run_is_not_found(pipeline_service):
    """Шаги несуществующего запуска — отказ с кодом not_found."""
    with pytest.raises(PipelineRejected) as exc:
        pipeline_service.steps(4242)
    assert exc.value.reason_code == REASON_NOT_FOUND
    assert "4242" in exc.value.message


def test_report_of_missing_run_is_not_found(pipeline_service):
    """Отчёт несуществующего запуска — отказ с кодом not_found."""
    with pytest.raises(PipelineRejected) as exc:
        pipeline_service.report(4242)
    assert exc.value.reason_code == REASON_NOT_FOUND


def test_delete_removes_run_and_steps(pipeline_service, pipeline_store):
    """Удаление убирает запуск вместе с шагами; повторное — уже отказ."""
    started = pipeline_service.start_pipeline(None, dict(ARGUMENTS), background=False)
    run_id = started["run_id"]
    assert pipeline_store.steps(run_id)
    assert pipeline_service.delete_run(run_id) == {"status": "deleted", "run_id": run_id}
    assert pipeline_store.steps(run_id) == []
    with pytest.raises(PipelineRejected):
        pipeline_service.delete_run(run_id)


def test_background_failure_gets_terminal_status(pipeline_store, monkeypatch):
    """Исключение в фоновом потоке ставит запуску статус failed, а не оставляет running."""
    service = PipelineService(pipeline=Pipeline(store=pipeline_store),
                              store=pipeline_store)

    def _boom(*_args, **_kwargs):
        """Прогон, падающий до записи шагов: так проверяется терминальный статус."""
        raise RuntimeError("инструменты недоступны")

    monkeypatch.setattr(service.pipeline, "run_pipeline", _boom)
    started = service.start_pipeline(None, dict(ARGUMENTS), background=True)
    report = _wait_terminal(service, started["run_id"])
    assert report["run"]["status"] == "failed"


def test_statuses_match_pipeline_states(pipeline_service):
    """Список статусов — значения ``PipelineState`` (им валидируется фильтр API)."""
    assert set(pipeline_service.statuses()) == {
        "idle", "running", "completed", "stopped", "failed"}


def test_service_substitutes_default_pipeline(pipeline_service):
    """Пустая конфигурация означает встроенный пайплайн, а не ошибку."""
    report = pipeline_service.start_pipeline({}, dict(ARGUMENTS), background=False)
    assert report["pipeline_name"] == DEFAULT_PIPELINE["name"]
    assert report["count"] == 3
