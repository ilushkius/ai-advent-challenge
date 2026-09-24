"""Тесты эндпоинтов /mcp (FastAPI TestClient, день 16).

Проверяются четыре эндпоинта и контракт ошибок: статус до подключения, успешное
подключение, список инструментов с полями ``name``/``description``/
``input_schema`` и ``count``, отключение, 400 на неразобранную цель, 502 на
недоступный сервер, 409 запрос инструментов без соединения и 422 на неизвестный
транспорт. Реестр подменяется фейковой фабрикой клиентов
(``support.make_mcp_factory``) — настоящий MCP-сервер здесь не поднимается.
"""
import pytest
from fastapi.testclient import TestClient

from backend.services.mcp_registry import MCPRegistry
from backend.storage import database
from backend.agents.agent_manager import AgentManager
from backend.storage.database import init_db, make_engine, make_session_factory

from mcp_fakes import FAKE_MCP_TOOLS, make_mcp_factory


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с изолированной БД и реестром на фейковых MCP-клиентах."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'mcp.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    import backend.api.main as main

    monkeypatch.setattr(main, "get_manager", lambda: AgentManager(session_factory=factory))
    mcp_factory = make_mcp_factory()
    registry = MCPRegistry(client_factory=mcp_factory)
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)

    with TestClient(main.app) as test_client:
        test_client.registry = registry
        test_client.mcp_factory = mcp_factory
        yield test_client


def test_status_before_connect(client):
    """GET /mcp/status до подключения: disconnected и подсказка про connect."""
    response = client.get("/mcp/status")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["state"] == "disconnected"
    assert body["tool_count"] == 0
    assert body["error"] is None
    assert body["allowed_events"] == ["connect"]


def test_tools_without_connection_conflict(client):
    """GET /mcp/tools без соединения — 409 с объяснением, а не пустой список."""
    response = client.get("/mcp/tools")
    assert response.status_code == 409
    assert "не установлено" in response.json()["detail"]


def test_connect_then_tools_and_disconnect(client):
    """Полный цикл: подключение → список инструментов → отключение."""
    connected = client.post("/mcp/connect", json={"target": "uvx mcp-server-fetch"})
    assert connected.status_code == 200
    body = connected.json()
    assert body["connected"] is True and body["state"] == "connected"
    assert body["target"] == "uvx mcp-server-fetch"
    assert body["transport"] == "stdio"
    assert body["server_name"] == "fake-mcp"
    assert body["protocol"] == "2025-11-25"

    listed = client.get("/mcp/tools")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["count"] == len(FAKE_MCP_TOOLS)
    assert [tool["name"] for tool in payload["tools"]] == [
        tool.name for tool in FAKE_MCP_TOOLS
    ]
    first = payload["tools"][0]
    assert set(first) == {"name", "description", "input_schema", "output_schema"}
    assert first["description"]
    assert isinstance(first["input_schema"], dict)
    assert payload["server_version"] == "1.0.0"

    refreshed = client.get("/mcp/tools", params={"refresh": True})
    assert refreshed.status_code == 200
    assert refreshed.json()["count"] == payload["count"]

    stopped = client.post("/mcp/disconnect", json={})
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "disconnected"
    assert client.get("/mcp/tools").status_code == 409


def test_connect_rejects_unparsable_target(client):
    """Пустая цель — 422 от схемы; цель из пробелов — 400 от разбора."""
    empty = client.post("/mcp/connect", json={"target": ""})
    assert empty.status_code == 422

    blank = client.post("/mcp/connect", json={"target": "   "})
    assert blank.status_code == 400
    assert "цель" in blank.json()["detail"].lower()

    bad = client.post("/mcp/connect", json={"target": "uvx mcp-server-fetch",
                                           "transport": "http"})
    assert bad.status_code == 400
    assert "URL" in bad.json()["detail"]


def test_connect_unknown_transport_rejected_by_schema(client):
    """Неизвестный транспорт — 422 от Pydantic: значение вне Enum."""
    response = client.post("/mcp/connect",
                           json={"target": "uvx mcp-server-fetch", "transport": "ws"})
    assert response.status_code == 422


def test_connect_unavailable_server_returns_502(client, monkeypatch):
    """Недоступный сервер — 502 с понятным текстом; статус показывает ошибку."""
    import backend.api.main as main

    registry = MCPRegistry(client_factory=make_mcp_factory(fail="Сервер не отвечает"))
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)

    response = client.post("/mcp/connect", json={"target": "http://127.0.0.1:9/mcp"})
    assert response.status_code == 502
    assert "Сервер не отвечает" in response.json()["detail"]

    status = client.get("/mcp/status").json()
    assert status["state"] == "error" and status["error"] == "Сервер не отвечает"
    assert status["allowed_events"] == ["connect", "disconnect"]


def test_disconnect_without_connection_is_noop(client):
    """Повторное отключение без соединения не ошибка (безопасный no-op)."""
    response = client.post("/mcp/disconnect", json={})
    assert response.status_code == 200
    assert response.json()["state"] == "disconnected"
