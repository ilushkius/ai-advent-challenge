"""Тесты эндпоинтов вызова инструмента и каталога серверов (день 17).

Проверяется контракт ``POST /mcp/call``: 409 без соединения, 400 на неизвестный
инструмент и на не подходящие по ``input_schema`` аргументы, 422 на невалидное
тело, 502 на обрыв связи и 200 с ``is_error: true`` на ошибку самого инструмента.
Плюс ``GET /mcp/servers`` (каталог известных целей и подключённая из них) и поле
``mcp`` ответа генерации — то, ради чего день и делался: агент сам вызывает
инструмент и вставляет его данные в запрос.

Реестр подменяется фейковой фабрикой клиентов (``support.make_mcp_factory``):
настоящий MCP-сервер в тестах не поднимается, а клиент DeepSeek — фейком.
"""
import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.core import config
from backend.services.mcp_registry import MCPRegistry
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory

from mcp_fakes import FAKE_TOOL_CATALOG, make_mcp_factory
from support import FakeClient

USER = {"id": 1, "name": "Leanne Graham", "city": "Gwenborough"}

#: Реплика, по которой инструмент вызывается сам (ключевые слова + номер).
QUESTION = "Найди информацию о пользователе с ID 1"


def _build_client(tmp_path, monkeypatch, **client_kwargs):
    """TestClient с изолированной БД и реестром на фейковых MCP-клиентах."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'mcp_call.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    import backend.api.main as main

    mcp_factory = make_mcp_factory(tools=FAKE_TOOL_CATALOG, **client_kwargs)
    registry = MCPRegistry(client_factory=mcp_factory)
    # Один менеджер на тест: агент, созданный через API, должен быть виден и
    # следующему запросу (лямбда с конструктором отдавала бы новый пустой пул).
    manager = AgentManager(session_factory=factory, mcp_registry=registry)
    monkeypatch.setattr(main, "get_manager", lambda: manager)
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient())

    test_client = TestClient(main.app)
    test_client.registry = registry
    test_client.mcp_factory = mcp_factory
    return test_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с каталогом своего сервера дня и готовым результатом вызова."""
    with _build_client(tmp_path, monkeypatch, call_result=USER) as test_client:
        yield test_client


def test_call_without_connection_is_conflict(client):
    """Без соединения вызов — 409: это конфликт состояний, а не ошибка запроса."""
    response = client.post("/mcp/call", json={"tool": "get_user",
                                             "arguments": {"user_id": 1}})
    assert response.status_code == 409
    assert "POST /mcp/connect" in response.json()["detail"]


def test_call_returns_result_and_allowed_events(client):
    """После подключения вызов отвечает результатом и допустимыми событиями FSM."""
    client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
    response = client.post("/mcp/call", json={"tool": "get_user",
                                             "arguments": {"user_id": 1}})
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True and body["called"] is True
    assert body["state"] == "done"
    assert body["tool"] == "get_user" and body["arguments"] == {"user_id": 1}
    assert body["result"]["structured"] == USER
    assert body["is_error"] is False and body["error"] is None
    assert body["allowed_events"] == ["plan"]
    assert body["duration_ms"] >= 0


def test_call_rejects_unknown_tool(client):
    """Неизвестный инструмент — 400 с перечнем доступных имён."""
    client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
    response = client.post("/mcp/call", json={"tool": "no_such_tool", "arguments": {}})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "не найден в каталоге" in detail and "get_user" in detail


def test_call_rejects_wrong_argument_type(client):
    """Аргумент не по схеме — 400 с указанием ожидаемого типа."""
    client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
    response = client.post("/mcp/call", json={"tool": "get_user",
                                             "arguments": {"user_id": "один"}})
    assert response.status_code == 400
    assert "должен быть integer" in response.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"tool": "", "arguments": {}},
    {"tool": "x" * (config.MCP_TOOL_NAME_MAX + 1), "arguments": {}},
    {"arguments": {}},
])
def test_call_validates_body(client, payload):
    """Пустое/слишком длинное имя и отсутствие поля ``tool`` ловит Pydantic (422)."""
    response = client.post("/mcp/call", json=payload)
    assert response.status_code == 422


def test_call_reports_transport_failure_as_502(tmp_path, monkeypatch):
    """Обрыв связи — 502 с текстом ошибки: ответа сервера не было."""
    with _build_client(tmp_path, monkeypatch,
                       call_fail="Соединение с MCP-сервером оборвалось") as test_client:
        test_client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
        response = test_client.post("/mcp/call", json={"tool": "get_user",
                                                      "arguments": {"user_id": 1}})
    assert response.status_code == 502
    assert "оборвалось" in response.json()["detail"]


def test_tool_error_comes_as_data_not_http_error(tmp_path, monkeypatch):
    """Ошибка инструмента — 200 с ``is_error: true``: это ответ, а не отказ запроса."""
    with _build_client(tmp_path, monkeypatch,
                       call_error="Пользователя не существует") as test_client:
        test_client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
        response = test_client.post("/mcp/call", json={"tool": "get_user",
                                                      "arguments": {"user_id": 999}})
    assert response.status_code == 200
    body = response.json()
    assert body["is_error"] is True and body["state"] == "failed"
    assert body["reason_code"] == "tool_error"
    assert body["error"] == "Пользователя не существует"


def test_tools_include_output_schema(client):
    """Каталог отдаёт обе схемы инструмента: аргументы и структуру результата."""
    client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
    payload = client.get("/mcp/tools").json()
    assert payload["count"] == len(FAKE_TOOL_CATALOG)
    user = next(tool for tool in payload["tools"] if tool["name"] == "get_user")
    assert user["input_schema"]["required"] == ["user_id"]
    assert "name" in user["output_schema"]["properties"]


def test_servers_catalog_marks_connected_server(client):
    """Каталог — три известных сервера, подключён отмечен ровно один."""
    client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
    client.get("/mcp/tools")  # число инструментов считается по полученному каталогу

    body = client.get("/mcp/servers").json()
    assert body["count"] == 3
    assert body["connected_key"] == "day17-jsonplaceholder"
    assert body["connected_target"] == config.MCP_DEFAULT_TARGET
    connected = [item for item in body["servers"] if item["connected"]]
    assert len(connected) == 1 and connected[0]["tool_count"] == len(FAKE_TOOL_CATALOG)
    assert all(item["tool_count"] == 0 for item in body["servers"] if not item["connected"])


def test_servers_catalog_without_connection(client):
    """Без подключения каталог всё равно отдаёт цели — просто никто не отмечен."""
    body = client.get("/mcp/servers").json()
    assert body["count"] == 3
    assert body["connected_key"] is None and body["connected_target"] is None
    assert all(not item["connected"] for item in body["servers"])


def test_generate_reports_tool_call_in_response(client):
    """Ответ генерации несёт поле ``mcp``: инструмент, аргументы и вклад в промпт."""
    client.post("/mcp/connect", json={"target": config.MCP_DEFAULT_TARGET})
    agent_id = client.post("/agents", json={"name": "Агент MCP"}).json()["agent_id"]

    body = client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": QUESTION}).json()
    assert body["status"] == "ok"
    assert body["mcp"]["tool"] == "get_user"
    assert body["mcp"]["arguments"] == {"user_id": 1}
    assert body["mcp"]["used_in_prompt"] is True and body["mcp"]["added_tokens"] > 0
    assert "## Данные MCP-инструмента" in body["system_prompt"]
