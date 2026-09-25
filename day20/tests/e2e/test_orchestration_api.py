"""Тесты эндпоинтов оркестрации (день 20).

Проверяется контракт ``/orchestration``: демо-сценарий одной кнопкой, запуск по
реплике (синхронно и фоном), отчёт о запуске, его шаги, история со статистикой и
удаление. Отдельно — контракт ошибок: 400 на негодный план и на неизвестный статус
в фильтре, 404 на исчезнувший запуск, 422 на пустую реплику. Плюс поле
``orchestration`` ответа генерации — то, ради чего день и делался: реплика запускает
флоу по трём серверам, а его результат уходит в системный промпт.

Флот фейковый (``orchestration_fakes``): настоящие процессы в тестах не
поднимаются, но каталоги, схемы и ответы инструментов — как у настоящих серверов.
"""
import time

import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.services.mcp_registry import MCPRegistry
from backend.services.orchestration_service import OrchestrationService
from backend.services.orchestrator import Orchestrator
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory
from backend.storage.orchestration_store import OrchestrationStore

from orchestration_fakes import make_fleet_factory, write_servers_file
from support import FakeClient

#: Реплика, которая обязана попасть в оркестрацию (сохранение в базу).
ORCH_REPLY = "найди данные про RAG и сохрани в базу"


def _build_client(tmp_path, monkeypatch, *, fleet_errors=None):
    """TestClient с изолированной БД, фейковым флотом и службой оркестрации."""
    import backend.api.main as main

    engine = make_engine(f"sqlite:///{(tmp_path / 'orchestration.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    servers_file = write_servers_file(tmp_path / "mcp_servers.json")
    fleet_factory = make_fleet_factory(errors=fleet_errors)
    registry = MCPRegistry(fleet_factory=fleet_factory, servers_file=servers_file,
                           cwd=str(tmp_path))
    registry.connect_all()
    store = OrchestrationStore(session_factory=factory)
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry, store=store), store=store)
    manager = AgentManager(session_factory=factory, mcp_registry=registry,
                           orchestration_service=service)
    monkeypatch.setattr(main, "get_manager", lambda: manager)
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)
    monkeypatch.setattr(main, "get_orchestration_service", lambda: service)
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient())

    client = TestClient(main.app)
    client.registry = registry
    client.service = service
    client.store = store
    client.fleet_factory = fleet_factory
    return client


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с подключённым фейковым флотом из трёх серверов."""
    instance = _build_client(tmp_path, monkeypatch)
    try:
        yield instance
    finally:
        instance.registry.close()


def _wait_terminal(client, run_id: int, deadline: float = 20.0) -> dict:
    """Ждёт терминального статуса фонового запуска и возвращает отчёт."""
    started = time.perf_counter()
    while time.perf_counter() - started < deadline:
        report = client.get(f"/orchestration/runs/{run_id}").json()
        if report["run"]["status"] != "running":
            return report
        time.sleep(0.05)
    raise AssertionError(f"запуск {run_id} не завершился за {deadline:.0f} с")


def test_root_lists_new_endpoint_groups(client):
    """Корневая точка знает про оркестрацию и флот серверов."""
    body = client.get("/").json()
    assert "оркестрацией MCP-серверов" in body["name"]
    assert "/orchestration/demo" in body["orchestration"]
    assert "/mcp/servers/refresh" in body["mcp_servers"]
    assert body["endpoints"].count("POST /orchestration/demo") == 1
    assert "GET /orchestration/runs/{run_id}/steps" in body["endpoints"]
    assert body["endpoints"].count("GET /mcp/servers") == 1


def test_demo_button_flow_over_api(client):
    """Демо-сценарий: фон, потом отчёт с пятью шагами по трём серверам."""
    started = client.post("/orchestration/demo", json={}).json()
    assert started["status"] == "running" and started["background"] is True
    report = _wait_terminal(client, started["run_id"])
    assert report["run"]["status"] == "completed"
    assert report["count"] == 5
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]
    assert report["run"]["query"].startswith("найди последние посты")
    assert report["run"]["plan"]["name"] == "demo-scenario"
    assert [step["server_name"] for step in report["steps"]] == [
        "search_server", "data_server", "data_server", "storage_server",
        "storage_server"]
    assert report["failed_at_step"] is None and report["error"] is None


def test_sync_run_with_explicit_plan(client):
    """Синхронный запуск с готовым планом: шаги и результат в одном ответе."""
    body = {"query": "проверка", "background": False,
            "plan": {"name": "один шаг",
                     "steps": [{"tool": "list_saved", "args": {"kind": "all"}}]}}
    report = client.post("/orchestration/run", json=body).json()
    assert report["status"] == "completed"
    assert report["plan_source"] == "given"
    assert report["count"] == 1
    assert report["steps"][0]["server_name"] == "storage_server"
    assert report["steps"][0]["output_result"]["is_error"] is False


def test_run_by_reply_uses_heuristic_plan(client):
    """Запуск без плана: план строит домен (эвристика), это видно в ответе."""
    report = client.post("/orchestration/run",
                         json={"query": ORCH_REPLY, "background": False}).json()
    assert report["status"] == "completed"
    assert report["plan_source"] == "heuristic"
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]


def test_steps_endpoint_returns_journal(client):
    """``GET /orchestration/runs/{id}/steps`` отдаёт шаги с сервером и временем."""
    started = client.post("/orchestration/demo", json={"background": False}).json()
    steps = client.get(f"/orchestration/runs/{started['run_id']}/steps").json()
    assert steps["count"] == 5
    assert [step["step_index"] for step in steps["steps"]] == [0, 1, 2, 3, 4]
    first = steps["steps"][0]
    assert first["server_name"] == "search_server"
    assert first["tool_name"] == "search_web"
    assert first["status"] == "ok"
    assert first["duration_ms"] >= 0
    assert first["input_args"]["limit"] == 5


def test_history_and_stats_over_api(client):
    """История непуста, статистика считает вызовы по серверам и инструментам."""
    client.post("/orchestration/demo", json={"background": False})
    body = client.get("/orchestration/runs").json()
    assert body["count"] == 1
    assert body["runs"][0]["status"] == "completed"
    assert body["stats"]["runs"] == 1 and body["stats"]["steps"] == 5
    assert {item["server"] for item in body["stats"]["servers"]} == {
        "search_server", "data_server", "storage_server"}
    assert body["stats"]["tools"][0]["calls"] >= 1
    assert client.get("/orchestration/runs?status=completed").json()["count"] == 1
    assert client.get("/orchestration/runs?limit=1").json()["count"] == 1


def test_delete_run_over_api(client):
    """Удаление запуска убирает его из истории, повторный запрос — 404."""
    started = client.post("/orchestration/demo", json={"background": False}).json()
    run_id = started["run_id"]
    assert client.delete(f"/orchestration/runs/{run_id}").json() == {
        "status": "deleted", "run_id": run_id}
    assert client.get(f"/orchestration/runs/{run_id}").status_code == 404
    assert client.get(f"/orchestration/runs/{run_id}/steps").status_code == 404
    assert client.delete(f"/orchestration/runs/{run_id}").status_code == 404


def test_error_contract(client):
    """Контракт ошибок: 400 на план и статус, 404 на запуск, 422 на пустую реплику."""
    bad_plan = client.post("/orchestration/run",
                           json={"query": "запрос", "plan": {"steps": []}})
    assert bad_plan.status_code == 400
    assert "непустой список шагов" in bad_plan.json()["detail"]

    bad_status = client.get("/orchestration/runs?status=nope")
    assert bad_status.status_code == 400
    assert "Неизвестный статус" in bad_status.json()["detail"]

    assert client.get("/orchestration/runs/9999").status_code == 404
    assert client.post("/orchestration/run", json={"query": ""}).status_code == 422
    assert client.post("/orchestration/demo",
                       json={"background": "не bool"}).status_code == 422


def test_failed_run_is_reported_with_step_number(tmp_path, monkeypatch):
    """Падение шага: 200 с ``failed``, номер шага и предыдущие ``ok`` в истории."""
    client = _build_client(tmp_path, monkeypatch,
                           fleet_errors={"data_server": "сервер не ответил"})
    try:
        report = client.post("/orchestration/run", json={
            "query": "запрос", "background": False,
            "plan": {"name": "падение", "steps": [
                {"tool": "search_web", "args": {"query": ""}},
                {"tool": "summarize", "args": {"items": "$steps.0.structured.items"}}]},
        }).json()
        assert report["status"] == "failed"
        assert report["failed_at_step"] == 1
        assert "Не подключены серверы" in report["error"] or "data_server" in report["error"]
        stored = client.get(f"/orchestration/runs/{report['run_id']}").json()
        assert [step["status"] for step in stored["steps"]] == ["ok", "failed"]
        assert stored["run"]["status"] == "failed"
    finally:
        client.registry.close()


def test_generate_reports_orchestration_in_response(client):
    """Ответ генерации несёт поле ``orchestration``: реплика про базу ушла во флот."""
    agent_id = client.post("/agents", json={"name": "Агент флота"}).json()["agent_id"]
    body = client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": ORCH_REPLY}).json()
    assert body["status"] == "ok"
    report = body["orchestration"]
    assert report["detected"] is True
    assert report["status"] == "completed"
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]
    assert report["tools_used"][0] == "search_web"
    assert report["used_in_prompt"] is True and report["added_tokens"] > 0
    assert "## Результат оркестрации" in body["system_prompt"]
    # Один ход — один автоматизм: пайплайн и одиночный вызов не запускались.
    assert body["pipeline"]["detected"] is False
    assert body["mcp"] is None


def test_generate_keeps_pipeline_reply_a_pipeline(client):
    """Реплика дня 19 через API остаётся пайплайном, а не оркестрацией."""
    agent_id = client.post("/agents", json={"name": "Агент пайплайна"}).json()["agent_id"]
    body = client.post(
        f"/agents/{agent_id}/generate",
        json={"prompt": "найди статьи про RAG, сделай сводку и сохрани в файл"},
    ).json()
    assert body["status"] == "ok"
    assert body["orchestration"]["detected"] is False
    assert body["pipeline"]["detected"] is True
