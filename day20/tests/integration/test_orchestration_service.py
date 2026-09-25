"""Тесты службы оркестрации (день 20): запуск, фон, история, статистика.

Служба — то, чем пользуются и роутер, и агент, поэтому проверяются оба способа
запуска: синхронный (весь отчёт сразу — так ходит агент) и фоновый (строка запуска
создаётся ДО потока, поэтому интерфейс сразу видит ``running`` и опрашивает шаги).
Отдельно — исключение внутри фонового потока: прогон обязан получить терминальный
``failed``, иначе интерфейс навсегда показывал бы «выполняется».
"""
import time

import pytest

from backend.domain.orchestration_spec import (
    DEMO_QUERY,
    MSG_COMPLETED,
    REASON_NOT_FOUND,
    STEP_FAILED,
    OrchestrationRejected,
)
from backend.services.orchestration_service import (
    OrchestrationService,
    get_orchestration_service,
)


def _wait_terminal(service: OrchestrationService, run_id: int, deadline: float = 20.0) -> dict:
    """Ждёт терминального статуса запуска и возвращает отчёт (или падает по дедлайну)."""
    started = time.perf_counter()
    while time.perf_counter() - started < deadline:
        report = service.report(run_id)
        if report["run"]["status"] != "running":
            return report
        time.sleep(0.02)
    raise AssertionError(f"запуск {run_id} не завершился за {deadline:.0f} с")


def test_sync_run_returns_full_report(orchestration_service):
    """Синхронный запуск возвращает весь отчёт сразу: так ходит агент."""
    report = orchestration_service.start_run(DEMO_QUERY, background=False)
    assert report["background"] is False
    assert report["status"] == "completed"
    assert report["count"] == 5
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]
    assert report["message"] == MSG_COMPLETED
    assert report["plan_source"] == "heuristic"


def test_background_run_is_visible_immediately(orchestration_service):
    """Фоновый запуск: ответ сразу ``running`` с номером, финал — в истории.

    Строка запуска создаётся до потока, поэтому номер есть в первом же ответе, а
    прогресс читается из БД (гонки «запуск ещё не записан» нет).
    """
    started = orchestration_service.start_run(DEMO_QUERY, plan=None, background=True)
    assert started["background"] is True
    assert started["status"] == "running"
    assert started["run_id"] > 0
    assert started["steps"] == [] and started["count"] == 0
    assert started["servers_used"] == []
    assert started["plan_source"] == "heuristic"
    report = _wait_terminal(orchestration_service, started["run_id"])
    assert report["run"]["status"] == "completed"
    assert report["count"] == 5
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]


def test_start_demo_runs_the_button_scenario(orchestration_service):
    """``start_demo`` — ровно то, что запускает кнопка: пять шагов по трём серверам."""
    report = orchestration_service.start_demo(background=False)
    assert report["query"] == DEMO_QUERY
    assert report["plan"]["name"] == "demo-scenario"
    assert report["plan_source"] == "given"
    assert report["count"] == 5
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]
    assert [step["tool_name"] for step in report["steps"]] == [
        "search_web", "summarize", "extract_keywords", "save_to_file", "save_to_db"]


def test_report_and_steps_read_from_store(orchestration_service):
    """Отчёт и шаги читаются из журнала (а не из ответа прогона)."""
    started = orchestration_service.start_demo(background=False)
    report = orchestration_service.report(started["run_id"])
    assert report["run"]["id"] == started["run_id"]
    assert report["count"] == 5
    assert report["failed_at_step"] is None and report["error"] is None
    assert report["message"] == MSG_COMPLETED

    steps = orchestration_service.steps(started["run_id"])
    assert steps["run_id"] == started["run_id"]
    assert [step["step_index"] for step in steps["steps"]] == [0, 1, 2, 3, 4]
    assert all(step["server_name"] for step in steps["steps"])


def test_unknown_run_is_rejected_with_not_found(orchestration_service):
    """Неизвестный запуск — отказ с кодом ``not_found`` (роутер отдаёт 404)."""
    for call in (orchestration_service.report, orchestration_service.steps,
                 orchestration_service.delete_run):
        with pytest.raises(OrchestrationRejected) as exc:
            call(9999)
        assert exc.value.reason_code == REASON_NOT_FOUND
        assert "9999" in exc.value.message


def test_list_runs_gives_history_and_stats(orchestration_service):
    """История непуста после прогона, статистика считается по журналу шагов."""
    orchestration_service.start_demo(background=False)
    history = orchestration_service.list_runs()
    assert history["count"] == 1
    run = history["runs"][0]
    assert run["status"] == "completed"
    assert run["servers_used"] == ["search_server", "data_server", "storage_server"]
    stats = history["stats"]
    assert stats["runs"] == 1 and stats["steps"] == 5
    assert {item["server"] for item in stats["servers"]} == {
        "search_server", "data_server", "storage_server"}
    assert stats["tools"][0]["calls"] >= 1


def test_list_runs_filters_by_status(orchestration_service):
    """Фильтр по статусу отдаёт только нужные запуски."""
    orchestration_service.start_demo(background=False)
    assert orchestration_service.list_runs(status="completed")["count"] == 1
    assert orchestration_service.list_runs(status="failed")["count"] == 0
    assert set(orchestration_service.statuses()) == {
        "idle", "running", "completed", "stopped", "failed"}


def test_delete_run_removes_history(orchestration_service):
    """Удаление запуска убирает его из истории и из шагов."""
    started = orchestration_service.start_demo(background=False)
    assert orchestration_service.delete_run(started["run_id"]) == {
        "status": "deleted", "run_id": started["run_id"]}
    assert orchestration_service.list_runs()["count"] == 0
    with pytest.raises(OrchestrationRejected):
        orchestration_service.report(started["run_id"])


def test_failed_plan_is_rejected_before_any_row(orchestration_service):
    """Негодный план отвергается до создания строки запуска (роутер отдаёт 400)."""
    with pytest.raises(OrchestrationRejected) as exc:
        orchestration_service.start_run("запрос", plan={"steps": []})
    assert exc.value.reason_code == "bad_plan"
    assert orchestration_service.list_runs()["count"] == 0


def test_exception_in_background_thread_gives_terminal_failed(orchestration_service, monkeypatch):
    """Исключение в фоне ставит терминальный ``failed``, а не вечное «выполняется»."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("фон сломался")

    monkeypatch.setattr(orchestration_service.orchestrator, "execute", boom)
    started = orchestration_service.start_run("запрос", plan=None, background=True)
    report = _wait_terminal(orchestration_service, started["run_id"])
    assert report["run"]["status"] == "failed"
    assert report["run"]["finished_at"] is not None
    assert report["run"]["total_duration_ms"] >= 0


def test_empty_fleet_rejects_run(tmp_path, session_factory):
    """Пустой флот — отказ ``bad_query``: прогону нечего выполнять."""
    from backend.services.orchestrator import Orchestrator
    from backend.storage.orchestration_store import OrchestrationStore

    from orchestration_fakes import make_fleet_registry

    registry = make_fleet_registry(tmp_path, names=())
    registry.connect_all()
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry,
                                  store=OrchestrationStore(session_factory)),
        store=OrchestrationStore(session_factory))
    try:
        with pytest.raises(OrchestrationRejected) as exc:
            service.start_run("запрос", background=False)
        assert exc.value.reason_code == "bad_query"
        assert service.list_runs()["count"] == 0

        # Кнопка демо-сценария тоже отказывает сразу: её план всегда валиден, и
        # без этой проверки запрос отвечал бы «запущено», а прогон падал на шаге 1.
        with pytest.raises(OrchestrationRejected) as exc:
            service.start_demo(background=False)
        assert exc.value.reason_code == "bad_query"
        assert "Флот пуст" in exc.value.message
        assert service.list_runs()["count"] == 0
    finally:
        registry.close()


def test_demo_rejects_unreachable_servers(tmp_path, session_factory):
    """Серверы есть в файле, но ни один не поднялся — демо тоже отказ, а не падение."""
    from backend.services.orchestrator import Orchestrator
    from backend.storage.orchestration_store import OrchestrationStore

    from orchestration_fakes import make_fleet_factory, make_fleet_registry

    registry = make_fleet_registry(
        tmp_path, factory=make_fleet_factory(errors={
            "search_server": "нет ответа", "data_server": "нет ответа",
            "storage_server": "нет ответа"}))
    registry.connect_all()
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry,
                                  store=OrchestrationStore(session_factory)),
        store=OrchestrationStore(session_factory))
    try:
        with pytest.raises(OrchestrationRejected) as exc:
            service.start_demo(background=False)
        assert exc.value.reason_code == "bad_query"
        assert registry.fleet_status()["count"] == 3, "серверы в файле остаются"
    finally:
        registry.close()


def test_process_service_is_a_singleton():
    """Служба процесса — ленивый синглтон: точка подмены для тестов и API."""
    assert get_orchestration_service() is get_orchestration_service()
