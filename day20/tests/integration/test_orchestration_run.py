"""Тесты прогона оркестрации по флоту серверов (день 20).

Здесь проверяется сердце дня: план выполняется по шагам, каждый шаг уходит СВОЕМУ
серверу (маршрутизация по имени инструмента), данные переходят между серверами
ссылками ``$steps.<i>``, а журнал пишется всегда — включая шаги, упавшие на
маппинге, потому что иначе причина остановки не доехала бы до истории и отчёта.

Отдельно проверяются исходы прогона: ``completed`` на полном флоте (пять шагов по
трём серверам), ``failed`` с номером упавшего шага и сохранением предыдущих ``ok``,
``stopped`` на невыполненном условии, отказы маршрутизации (``unknown_tool``,
``not_connected``) и форма ``output_result``, одинаковая у успеха и неудачи.
"""
import pytest

from backend.domain.orchestration_spec import DEMO_PLAN, STEP_FAILED, STEP_OK, STEP_STOPPED
from backend.services.orchestrator import Orchestrator
from backend.storage.orchestration_store import OrchestrationStore

from orchestration_fakes import FLEET_RESULTS, make_fleet_factory, make_fleet_registry


def _orchestrator(tmp_path, session_factory, **kwargs) -> Orchestrator:
    """Оркестратор на фейковом флоте и временном журнале (без модели: план — эвристика)."""
    registry = make_fleet_registry(tmp_path, **kwargs)
    registry.connect_all()
    return Orchestrator(registry=registry, store=OrchestrationStore(session_factory))


def test_demo_plan_runs_across_three_servers(tmp_path, session_factory):
    """Полный флот выполняет демо-план целиком: пять шагов, три сервера, ``completed``."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        report = orchestrator.run("найди данные и сохрани в базу", plan=DEMO_PLAN)
        assert report["status"] == "completed"
        assert report["count"] == 5 and report["failed_at_step"] is None
        assert report["error"] is None
        assert report["servers_used"] == ["search_server", "data_server",
                                          "storage_server"]
        assert [step["server_name"] for step in report["steps"]] == [
            "search_server", "data_server", "data_server", "storage_server",
            "storage_server"]
        assert [step["status"] for step in report["steps"]] == [STEP_OK] * 5
        assert report["plan"]["name"] == "demo-scenario"
        assert report["plan_source"] == "given"
        # Журнал записан целиком и читается из хранилища, а не только из ответа.
        stored = orchestrator.store.steps(report["run_id"])
        assert [step["tool_name"] for step in stored] == [
            step["tool_name"] for step in report["steps"]]
    finally:
        orchestrator.registry.close()


def test_data_flows_between_servers(tmp_path, session_factory):
    """Выход одного сервера становится входом следующего (через ссылки плана)."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        report = orchestrator.run("запрос", plan=DEMO_PLAN)
        steps = report["steps"]
        found = FLEET_RESULTS["search_web"]["items"]
        assert steps[1]["input_args"]["items"] == found
        assert steps[2]["input_args"]["text"] == FLEET_RESULTS["summarize"]["summary_text"]
        assert steps[3]["input_args"]["content"].startswith("Сводка:")
        assert FLEET_RESULTS["extract_keywords"]["joined"] in steps[3]["input_args"]["content"]
        # Строка базы несёт путь файла и ключевые слова из предыдущих шагов.
        metadata = steps[4]["input_args"]["metadata"]
        assert metadata["file"] == FLEET_RESULTS["save_to_file"]["filepath"]
        assert metadata["keywords"] == FLEET_RESULTS["extract_keywords"]["joined"]
        assert steps[4]["input_args"]["title"] == "запрос"
        # Аргументы запуска подставлены в заглушки плана.
        assert steps[0]["input_args"]["limit"] == 5
        assert steps[3]["input_args"]["filename"] == "запрос.md"
    finally:
        orchestrator.registry.close()


def test_result_shape_is_the_same_for_success_and_failure(tmp_path, session_factory):
    """``output_result`` несёт одни и те же ключи у успеха и у ошибки инструмента.

    По этой форме строятся пути маппинга следующих шагов
    (``$steps.<i>.structured.<поле>``), поэтому она не может зависеть от исхода:
    разошлись бы «шаг упал» и «шаг ответил ошибкой» — и маппинг падал бы там, где
    должен был просто не найти поле.
    """
    ok = _orchestrator(tmp_path, session_factory)
    try:
        report = ok.run("запрос", plan=DEMO_PLAN)
        assert report["status"] == "completed"
        for step in report["steps"]:
            assert set(step["output_result"]) == {
                "reason_code", "structured", "text", "is_error", "duration_ms"}
            assert step["output_result"]["is_error"] is False
            assert step["output_result"]["reason_code"] is None
    finally:
        ok.registry.close()

    failing = _orchestrator(tmp_path, session_factory, tool_errors={
        "summarize": "Список элементов пуст: свести нечего"})
    try:
        report = failing.run("запрос", plan=DEMO_PLAN)
        assert report["status"] == "failed"
        step = report["steps"][1]
        assert set(step["output_result"]) == {
            "reason_code", "structured", "text", "is_error", "duration_ms"}
        assert step["output_result"]["is_error"] is True
        assert step["output_result"]["reason_code"] == "tool_error"
        assert "пуст" in step["output_result"]["text"]
        assert step["output_result"]["structured"] is None
    finally:
        failing.registry.close()


def test_failed_step_stops_the_run_and_keeps_previous_ok(tmp_path, session_factory):
    """Падение шага останавливает прогон: номер шага в отчёте, предыдущие — ``ok``."""
    factory = make_fleet_factory(tool_errors={
        "summarize": "Список элементов пуст: свести нечего"})
    orchestrator = _orchestrator(tmp_path, session_factory, factory=factory)
    try:
        report = orchestrator.run("запрос", plan=DEMO_PLAN)
        assert report["status"] == "failed"
        assert report["failed_at_step"] == 1
        assert [step["status"] for step in report["steps"]] == [STEP_OK, STEP_FAILED]
        assert "Список элементов пуст" in report["error"]
        # Четвёртый и пятый шаги не выполнялись вовсе: журнал короче плана.
        assert report["count"] == 2
        # Шаг упал на сервере, который его публикует: маршрутизация уже сработала.
        assert report["steps"][1]["server_name"] == "data_server"
        assert report["servers_used"] == ["search_server", "data_server"]
        # Дальше прогон не пошёл: файл и строка базы не появились.
        assert factory.by_server("storage_server").call_calls == []
    finally:
        orchestrator.registry.close()


def test_mapping_failure_is_logged_and_stops_the_run(tmp_path, session_factory):
    """Незаполненная ссылка логируется строкой журнала, а не теряется."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        plan = {"name": "плохой", "steps": [
            {"tool": "search_web", "args": {"query": "{нет_такого_аргумента}"}}]}
        report = orchestrator.run("запрос", plan=plan)
        assert report["status"] == "failed"
        assert report["failed_at_step"] == 0
        step = report["steps"][0]
        assert step["status"] == STEP_FAILED
        assert step["output_result"] is None and step["duration_ms"] == 0
        assert "нет_такого_аргумента" in step["error_message"]
    finally:
        orchestrator.registry.close()


def test_guard_stop_is_stopped_not_failed(tmp_path, session_factory):
    """Невыполненное условие — ``stopped`` с сообщением условия, а не ошибка."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        plan = {"name": "условие", "steps": [
            {"tool": "search_web", "args": {"query": ""}},
            {"tool": "summarize",
             "guard": {"path": "$steps.0.structured.items", "op": "empty",
                       "message": "нет данных для обработки"},
             "args": {"items": "$steps.0.structured.items"}},
        ]}
        report = orchestrator.run("запрос", plan=plan)
        assert report["status"] == "stopped"
        assert report["message"] == "нет данных для обработки"
        assert report["steps"][1]["status"] == STEP_STOPPED
        assert report["steps"][1]["error_message"] == "нет данных для обработки"
        assert report["failed_at_step"] is None
    finally:
        orchestrator.registry.close()


def test_unknown_tool_stops_with_reason_code(tmp_path, session_factory):
    """Неизвестный инструмент — ``unknown_tool`` со списком известных, шаг не идёт."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        plan = {"name": "телепорт", "steps": [
            {"tool": "search_web", "args": {"query": ""}},
            {"tool": "teleport", "args": {}}]}
        report = orchestrator.run("запрос", plan=plan)
        assert report["status"] == "failed"
        assert report["failed_at_step"] == 1
        step = report["steps"][1]
        assert step["output_result"]["reason_code"] == "unknown_tool"
        assert "teleport" in step["error_message"] and "search_web" in step["error_message"]
        assert step["server_name"] == "", "сервер не выбран — инструмента нет в флоте"
    finally:
        orchestrator.registry.close()


def test_disconnected_server_is_reported_as_not_connected(tmp_path, session_factory):
    """Известный по кэшу инструмент упавшего сервера даёт ``not_connected``.

    Каталог упавшего сервера живёт в файле (``tools_cache``), поэтому шаг доходит до
    маршрутизации: сервер выбран, но поднять его не удалось — это ``not_connected``,
    а не «инструмент неизвестен».
    """
    import json

    from orchestration_fakes import FLEET_CATALOGS, write_servers_file

    path = write_servers_file(tmp_path / "mcp_servers.json",
                              names=("search_server", "data_server"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["servers"][1]["tools_cache"] = [
        {"name": tool.name, "description": tool.description,
         "input_schema": tool.input_schema, "output_schema": tool.output_schema}
        for tool in FLEET_CATALOGS["data_server"]]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    factory = make_fleet_factory(errors={"data_server": "сервер не ответил"})
    registry = make_fleet_registry(tmp_path, servers_file=path,
                                  names=("search_server", "data_server"), factory=factory)
    registry.connect_all()
    orchestrator = Orchestrator(registry=registry,
                                store=OrchestrationStore(session_factory))
    try:
        plan = {"name": "падение", "steps": [
            {"tool": "search_web", "args": {"query": ""}},
            {"tool": "summarize", "args": {"items": "$steps.0.structured.items"}}]}
        report = orchestrator.run("запрос", plan=plan)
        assert report["status"] == "failed"
        step = report["steps"][1]
        assert step["server_name"] == "data_server"
        assert step["output_result"]["reason_code"] == "not_connected"
        assert "data_server" in step["error_message"]
        assert report["servers_used"] == ["search_server", "data_server"]
    finally:
        registry.close()


def test_unknown_tool_message_points_at_down_servers(tmp_path, session_factory):
    """Отказ «инструмент неизвестен» подсказывает, какие серверы не поднялись.

    Инструменты упавшего сервера в каталоге отсутствуют, поэтому без подсказки
    причина выглядела бы как ошибка плана.
    """
    factory = make_fleet_factory(errors={"data_server": "сервер не ответил"})
    orchestrator = _orchestrator(tmp_path, session_factory, factory=factory)
    try:
        report = orchestrator.run("запрос", plan={
            "name": "чужой", "steps": [{"tool": "summarize", "args": {}}]})
        step = report["steps"][0]
        assert step["output_result"]["reason_code"] == "unknown_tool"
        assert "Не подключены серверы" in step["error_message"]
        assert "data_server" in step["error_message"]
    finally:
        orchestrator.registry.close()


def test_plan_without_explicit_plan_uses_heuristic(tmp_path, session_factory):
    """Без плана прогон собирает эвристику по каталогу флота (и это видно в отчёте)."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        report = orchestrator.run("найди данные и сохрани в базу")
        assert report["status"] == "completed"
        assert report["plan_source"] == "heuristic"
        assert report["plan"]["name"] == "heuristic-chain"
        assert report["servers_used"] == ["search_server", "data_server",
                                          "storage_server"]
    finally:
        orchestrator.registry.close()


def test_given_plan_wins_over_heuristic(tmp_path, session_factory):
    """Присланный план важнее эвристики: он и выполняется, и помечен как ``given``."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        plan = {"name": "своё", "steps": [{"tool": "list_saved", "args": {"kind": "all"}}]}
        report = orchestrator.run("запрос", plan=plan)
        assert report["plan_source"] == "given"
        assert report["count"] == 1
        assert report["steps"][0]["server_name"] == "storage_server"
        assert report["steps"][0]["tool_name"] == "list_saved"
    finally:
        orchestrator.registry.close()


def test_existing_run_id_is_reused(tmp_path, session_factory):
    """Прогон по готовому ``run_id`` дописывает существующую строку запуска."""
    orchestrator = _orchestrator(tmp_path, session_factory)
    try:
        from datetime import datetime, timezone

        run_id = int(orchestrator.store.create_run(
            query="запрос", plan=DEMO_PLAN, status="running",
            started_at=datetime.now(timezone.utc),
        )["id"])
        report = orchestrator.run("запрос", plan=DEMO_PLAN, run_id=run_id)
        assert report["run_id"] == run_id
        assert orchestrator.store.run(run_id)["status"] == "completed"
        assert len(orchestrator.store.list_runs()) == 1, "второй запуск не заводится"
    finally:
        orchestrator.registry.close()
