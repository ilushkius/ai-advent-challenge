"""Тесты эндпоинтов пайплайна (день 19).

Проверяется контракт ``/pipelines``: запуск (синхронный и фоновый), отчёт о запуске,
его шаги, история с фильтром статуса и удаление. Отдельно — контракт ошибок: 400 на
негодную конфигурацию и на неизвестный статус в фильтре, 404 на исчезнувший запуск,
422 на невалидное тело. Плюс поле ``pipeline`` ответа генерации — то, ради чего день
и делался: реплика запускает пайплайн, а его результат уходит в системный промпт.

Реестр MCP подменяется фейковой фабрикой (``pipeline_fakes``): настоящий сервер в
тестах не поднимается, а клиент DeepSeek — фейком.
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.services.mcp_registry import MCPRegistry
from backend.services.mcp_tool_runner import MCPToolRunner
from backend.services.pipeline import Pipeline
from backend.services.pipeline_service import PipelineService
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory
from backend.storage.pipeline_store import PipelineStore

from pipeline_fakes import make_pipeline_factory
from support import FakeClient

#: Аргументы запуска встроенного пайплайна.
ARGS = {
    "query": "RAG",
    "source": "file:notes.md",
    "limit": 5,
    "style": "short",
    "max_length": 600,
    "filename": "api-run.md",
    "format": "md",
}

RAG_QUESTION = "найди статьи про RAG, сделай сводку и сохрани в файл"


def _build_client(tmp_path, monkeypatch, **client_kwargs):
    """TestClient с изолированной БД, фейковым MCP-реестром и службой пайплайнов."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'pipelines.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    import backend.api.main as main

    registry = MCPRegistry(client_factory=make_pipeline_factory(**client_kwargs))
    registry.connect("uv run python mcp_server/server.py")
    store = PipelineStore(session_factory=factory)
    service = PipelineService(pipeline=Pipeline(runner=MCPToolRunner(registry),
                                                store=store), store=store)
    manager = AgentManager(session_factory=factory, mcp_registry=registry,
                           pipeline_service=service)
    monkeypatch.setattr(main, "get_manager", lambda: manager)
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)
    monkeypatch.setattr(main, "get_pipeline_service", lambda: service)
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient())

    test_client = TestClient(main.app)
    test_client.registry = registry
    test_client.service = service
    test_client.store = store
    return test_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с подключённым фейковым сервером композиции."""
    instance = _build_client(tmp_path, monkeypatch)
    try:
        yield instance
    finally:
        instance.registry.close()


def _sync_run(client, **overrides):
    """Синхронный запуск пайплайна через API (``background=false``)."""
    body = {"initial_args": {**ARGS, **overrides}, "background": False}
    response = client.post("/pipelines/run", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _empty_search(client) -> None:
    """Настраивает фейковый поиск на пустой результат (условие шага не выполнится)."""
    client.registry.client.results = {
        "search": {"query": "квантовые вычисления", "source": ARGS["source"],
                   "source_kind": "file", "count": 0, "items": []},
    }


def _wait_terminal(client, run_id: int) -> dict:
    """Ждёт терминального статуса запуска (фейковые шаги отвечают мгновенно)."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        report = client.get(f"/pipelines/runs/{run_id}").json()
        if report["run"]["status"] != "running":
            return report
        time.sleep(0.05)
    raise AssertionError("запуск не завершился за 5 с")


# ---------- запуск ----------
def test_sync_run_returns_all_steps(client):
    """Синхронный запуск отдаёт полный отчёт: три шага, статус и длительность."""
    body = _sync_run(client)
    assert body["background"] is False
    assert body["status"] == "completed"
    assert body["pipeline_name"] == "search-summarize-save"
    assert [step["tool_name"] for step in body["steps"]] == [
        "search", "summarize", "save_to_file"]
    assert body["count"] == 3 and body["failed_at_step"] is None
    assert body["total_duration_ms"] >= 0


def test_background_run_is_pollable(client):
    """Фоновый запуск отвечает running, а дальше статус опрашивается до финала."""
    response = client.post("/pipelines/run",
                           json={"initial_args": dict(ARGS), "background": True})
    assert response.status_code == 200
    body = response.json()
    assert body["background"] is True and body["status"] == "running"
    assert body["message"] == "пайплайн выполняется"
    report = _wait_terminal(client, body["run_id"])
    assert report["run"]["status"] == "completed" and report["count"] == 3


def test_run_without_configuration_uses_default(client):
    """Без поля ``pipeline`` выполняется встроенный пайплайн (декларация в домене)."""
    body = _sync_run(client)
    assert body["pipeline_name"] == "search-summarize-save"
    assert len(body["steps"]) == 3


def test_run_rejects_bad_configuration(client):
    """Негодная конфигурация — 400 с текстом причины, а не 500 и не пустой ответ."""
    response = client.post("/pipelines/run",
                           json={"pipeline": {"steps": []}, "initial_args": {}})
    assert response.status_code == 400
    assert "шагов" in response.json()["detail"]


def test_run_rejects_unknown_guard_operator(client):
    """Неизвестное условие перехода — 400: прогон не может быть неоднозначным."""
    broken = {"steps": [{"tool": "search", "args": {"query": "x"},
                         "guard": {"path": "$steps.0.structured.items",
                                   "op": "magic"}}]}
    response = client.post("/pipelines/run", json={"pipeline": broken})
    assert response.status_code == 400
    assert "magic" in response.json()["detail"]


def test_run_validates_body(client):
    """Невалидное тело запроса — 422 (Pydantic), как у остальных эндпоинтов."""
    assert client.post("/pipelines/run", json={"background": "не bool"}).status_code == 422


# ---------- отчёт и шаги ----------
def test_report_of_run_contains_steps_and_message(client):
    """Отчёт о запуске отдаёт строку запуска, шаги, итог и причину остановки."""
    run_id = _sync_run(client)["run_id"]
    report = client.get(f"/pipelines/runs/{run_id}").json()
    assert report["run"]["id"] == run_id
    assert report["run"]["status"] == "completed"
    assert report["run"]["finished_at"] is not None
    assert report["message"] == "пайплайн выполнен"
    assert [step["step_index"] for step in report["steps"]] == [0, 1, 2]
    assert report["steps"][0]["input_args"]["query"] == "RAG"
    assert report["steps"][0]["duration_ms"] >= 0


def test_report_explains_early_stop(client):
    """Досрочное завершение видно сообщением условия и статусом stopped (не 404)."""
    _empty_search(client)
    run_id = _sync_run(client, query="квантовые вычисления")["run_id"]
    report = client.get(f"/pipelines/runs/{run_id}").json()
    assert report["run"]["status"] == "stopped"
    assert report["message"] == "нет данных для обработки"
    assert report["failed_at_step"] is None


def test_steps_endpoint_returns_only_steps(client):
    """``/steps`` отдаёт шаги запуска, не заворачивая их в отчёт."""
    run_id = _sync_run(client)["run_id"]
    body = client.get(f"/pipelines/runs/{run_id}/steps").json()
    assert body["run_id"] == run_id
    assert body["count"] == 3
    assert set(body) == {"run_id", "steps", "count"}


def test_missing_run_is_not_found(client):
    """Несуществующий запуск — 404 и у отчёта, и у шагов, и у удаления."""
    assert client.get("/pipelines/runs/4242").status_code == 404
    assert client.get("/pipelines/runs/4242/steps").status_code == 404
    assert client.delete("/pipelines/runs/4242").status_code == 404


# ---------- история ----------
def test_runs_history_is_fresh_first_and_filterable(client):
    """История идёт от свежих к старым, фильтр статуса принимается, чужой — 400."""
    first = _sync_run(client)["run_id"]
    _empty_search(client)
    second = _sync_run(client, query="квантовые вычисления")["run_id"]

    body = client.get("/pipelines/runs").json()
    assert [run["id"] for run in body["runs"]] == [second, first]
    assert body["count"] == 2

    stopped = client.get("/pipelines/runs", params={"status": "stopped"}).json()
    assert stopped["count"] == 1 and stopped["runs"][0]["id"] == second

    limit = client.get("/pipelines/runs", params={"limit": 1}).json()
    assert limit["count"] == 1

    bad = client.get("/pipelines/runs", params={"status": "нет такого"})
    assert bad.status_code == 400
    assert "completed" in bad.json()["detail"]


def test_delete_removes_run_and_its_steps(client):
    """Удаление убирает запуск вместе с шагами; повторное — 404."""
    run_id = _sync_run(client)["run_id"]
    response = client.delete(f"/pipelines/runs/{run_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "run_id": run_id}
    assert client.get("/pipelines/runs").json()["count"] == 0
    assert client.get(f"/pipelines/runs/{run_id}/steps").status_code == 404


# ---------- шаг агента ----------
def test_generate_reports_pipeline_step(client):
    """Реплика про RAG в ответе генерации приходит с отчётом пайплайна."""
    agent_id = client.post("/agents", json={"name": "Агент пайплайна"}).json()["agent_id"]
    body = client.post(f"/agents/{agent_id}/generate",
                      json={"prompt": RAG_QUESTION}).json()
    report = body["pipeline"]
    assert report["detected"] is True
    assert report["status"] == "completed"
    assert report["used_in_prompt"] is True and report["added_tokens"] > 0
    assert [step["tool_name"] for step in report["steps"]] == [
        "search", "summarize", "save_to_file"]
    assert body["mcp"] is None


def test_generate_without_pipeline_leaves_report_empty(client):
    """Обычная реплика: поле ``pipeline`` заполнено, но прогона не было."""
    agent_id = client.post("/agents", json={"name": "Обычный агент"}).json()["agent_id"]
    body = client.post(f"/agents/{agent_id}/generate",
                      json={"prompt": "Сколько будет 2+2?"}).json()
    assert body["pipeline"]["detected"] is False
    assert body["pipeline"]["run_id"] is None
    assert client.get("/pipelines/runs").json()["count"] == 0


def test_root_lists_pipelines(client):
    """Корневая точка перечисляет эндпоинты пайплайна (это справочник по API)."""
    body = client.get("/").json()
    assert "/pipelines/run" in body["pipelines"]
    assert "POST /pipelines/run" in body["endpoints"]
    assert "DELETE /pipelines/runs/{run_id}" in body["endpoints"]
