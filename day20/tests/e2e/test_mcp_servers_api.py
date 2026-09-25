"""Тесты эндпоинтов флота MCP-серверов (день 20).

Три эндпоинта: состав флота (``GET /mcp/servers``), инструменты одного сервера
(``GET /mcp/servers/{name}/tools``) и обновление кэша (``POST /mcp/servers/refresh``).
Проверяется и контракт ошибок: неизвестный сервер — 404 с перечнем известных, а
сбой ОДНОГО сервера — не отказ запроса, а данные его записи.

Флот фейковый: настоящие процессы не поднимаются, но конфигурация читается из
временного файла, поэтому проверяется и запись кэша в него.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.services.mcp_registry import MCPRegistry
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory

from orchestration_fakes import FLEET_CATALOGS, make_fleet_factory, write_servers_file

#: Ожидаемый состав: три сервера и одиннадцать инструментов.
EXPECTED_TOTAL_TOOLS = 11


def _build_client(tmp_path, monkeypatch, *, errors=None):
    """TestClient с изолированной БД и фейковым флотом из временного файла."""
    import backend.api.main as main

    engine = make_engine(f"sqlite:///{(tmp_path / 'fleet.db').as_posix()}")
    init_db(engine)
    monkeypatch.setattr(database, "SessionLocal", make_session_factory(engine))

    servers_file = write_servers_file(tmp_path / "mcp_servers.json")
    registry = MCPRegistry(fleet_factory=make_fleet_factory(errors=errors),
                           servers_file=servers_file, cwd=str(tmp_path))
    registry.connect_all()
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)

    client = TestClient(main.app)
    client.registry = registry
    client.servers_file = servers_file
    return client


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с подключённым фейковым флотом."""
    instance = _build_client(tmp_path, monkeypatch)
    try:
        yield instance
    finally:
        instance.registry.close()


def test_fleet_listing_over_api(client):
    """``GET /mcp/servers`` отдаёт состав флота и состояние каждого сервера."""
    body = client.get("/mcp/servers").json()
    assert body["count"] == 3
    assert body["connected"] == 3
    assert body["total_tools"] == EXPECTED_TOTAL_TOOLS
    assert [item["name"] for item in body["servers"]] == list(FLEET_CATALOGS)
    first = body["servers"][0]
    assert first["name"] == "search_server"
    assert first["transport"] == "stdio"
    assert first["target"].startswith("uv run python")
    assert first["state"] == "connected"
    assert first["tool_count"] == len(FLEET_CATALOGS["search_server"])
    assert first["error"] is None
    assert first["description"]


def test_server_tools_over_api(client):
    """``GET /mcp/servers/{name}/tools`` отдаёт инструменты со схемами."""
    body = client.get("/mcp/servers/data_server/tools").json()
    assert body["server"] == "data_server"
    assert body["count"] == len(FLEET_CATALOGS["data_server"])
    assert body["cached"] is False, "сервер подключён — каталог прочитан из соединения"
    assert [tool["name"] for tool in body["tools"]] == [
        tool.name for tool in FLEET_CATALOGS["data_server"]]
    summarize = next(tool for tool in body["tools"] if tool["name"] == "summarize")
    assert summarize["input_schema"]["required"] == ["items"]
    assert summarize["output_schema"]["properties"]
    assert summarize["description"]

    for name, catalog in FLEET_CATALOGS.items():
        assert client.get(f"/mcp/servers/{name}/tools").json()["count"] == len(catalog)


def test_unknown_server_is_404(client):
    """Неизвестное имя сервера — 404 с перечнем известных."""
    response = client.get("/mcp/servers/echo_server/tools")
    assert response.status_code == 404
    assert "echo_server" in response.json()["detail"]
    assert "search_server" in response.json()["detail"]


def test_refresh_writes_cache_to_file(client):
    """``POST /mcp/servers/refresh`` пишет каталоги в ``tools_cache`` файла флота."""
    before = json.loads(client.servers_file.read_text(encoding="utf-8"))
    assert all(item["tools_cache"] == [] for item in before["servers"])

    body = client.post("/mcp/servers/refresh").json()
    assert body["count"] == 3 and body["total_tools"] == EXPECTED_TOTAL_TOOLS
    assert body["refreshed_at"], "момент обновления попадает в ответ"

    after = json.loads(client.servers_file.read_text(encoding="utf-8"))
    cached = {item["name"]: [tool["name"] for tool in item["tools_cache"]]
              for item in after["servers"]}
    assert cached["search_server"] == ["search_web", "search_local", "fetch_url"]
    assert cached["data_server"] == [tool.name for tool in FLEET_CATALOGS["data_server"]]
    assert cached["storage_server"] == [
        tool.name for tool in FLEET_CATALOGS["storage_server"]]
    # Ручные правки файла не потерялись: описания и порядок записей на месте.
    assert [item["name"] for item in after["servers"]] == list(FLEET_CATALOGS)
    assert all(item["description"] for item in after["servers"])

    # После обновления каталог доступен и в следующем запросе.
    assert client.get("/mcp/servers/search_server/tools").json()["count"] == 3


def test_failed_server_is_data_not_error(tmp_path, monkeypatch):
    """Сбой одного сервера — его запись (``error``), а не отказ всего запроса."""
    client = _build_client(tmp_path, monkeypatch,
                           errors={"data_server": "сервер не ответил"})
    try:
        response = client.get("/mcp/servers")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 3 and body["connected"] == 2
        failed = next(item for item in body["servers"] if item["name"] == "data_server")
        assert failed["state"] == "error"
        assert "не ответил" in failed["error"]
        # Остальные серверы работают, и обновление кэша тоже проходит.
        ok = next(item for item in body["servers"] if item["name"] == "search_server")
        assert ok["connected"] is True
        refresh = client.post("/mcp/servers/refresh").json()
        assert refresh["count"] == 3
        tools = client.get("/mcp/servers/search_server/tools").json()
        assert tools["count"] == 3
        # Каталог упавшего сервера после обновления в файл не записан (его не прочитали).
        payload = json.loads(client.servers_file.read_text(encoding="utf-8"))
        failed_record = next(item for item in payload["servers"]
                             if item["name"] == "data_server")
        assert failed_record["tools_cache"] == []
    finally:
        client.registry.close()


def test_active_connection_endpoints_still_work(client):
    """Пять эндпоинтов активного соединения не пострадали от каталога флота."""
    assert client.get("/mcp/status").json()["state"] == "disconnected"
    assert client.get("/mcp/tools").status_code == 409
    assert client.get("/mcp/servers").status_code == 200
