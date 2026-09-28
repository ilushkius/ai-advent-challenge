"""Тесты многоподключенческого реестра флота (день 20).

Реестр дня 20 делает три вещи, которых не делал реестр дня 17: держит по соединению
на КАЖДЫЙ сервер из конфигурации, кэширует каталог каждого (в памяти и в файле) и
маршрутизирует вызов по имени инструмента. Здесь проверяется всё это вместе с
поведением при сбоях: упавший сервер не мешает остальным, сбой одного не отменяет
каталоги других, а вызов в неизвестный сервер или инструмент — явная ошибка с
перечнем известных.

Флот — фейковый (``orchestration_fakes``): настоящие процессы не поднимаются, но
каталоги, схемы аргументов и ответы инструментов — те же, что у настоящих серверов.
"""
import json

import pytest

from backend.domain.mcp_tools import MCPFleetTool
from backend.services.mcp_errors import MCPUnknownServerError, MCPUnknownToolError
from backend.services.mcp_registry import MCPRegistry

from orchestration_fakes import (
    ECHO_CATALOG,
    FLEET_CATALOGS,
    FLEET_RESULTS,
    make_fleet_factory,
    make_fleet_registry,
    write_servers_file,
)

#: Ожидаемый состав флота: три сервера и одиннадцать инструментов.
EXPECTED_TOOLS = {
    "search_web", "search_local", "fetch_url",
    "summarize", "extract_keywords", "filter_by_date", "aggregate",
    "save_to_file", "save_to_db", "list_saved", "load_from_file",
}


def _connected(tmp_path, **kwargs) -> MCPRegistry:
    """Реестр с подключённым флотом (фабрика и файл — временные)."""
    registry = make_fleet_registry(tmp_path, **kwargs)
    registry.connect_all()
    return registry


def test_connect_all_connects_every_server(tmp_path):
    """``connect_all`` поднимает соединение с каждым сервером файла конфигурации."""
    registry = _connected(tmp_path)
    try:
        status = registry.fleet_status()
        assert status["count"] == 3
        assert status["connected"] == 3
        assert status["total_tools"] == len(EXPECTED_TOOLS)
        assert [item["name"] for item in status["servers"]] == list(FLEET_CATALOGS)
        assert all(item["state"] == "connected" for item in status["servers"])
        assert all(item["error"] is None for item in status["servers"])
    finally:
        registry.close()


def test_list_all_tools_marks_the_server(tmp_path):
    """Плоский каталог флота несёт имя сервера у каждого инструмента."""
    registry = _connected(tmp_path)
    try:
        tools = registry.list_all_tools()
        assert {tool.name for tool in tools} == EXPECTED_TOOLS
        assert all(isinstance(tool, MCPFleetTool) for tool in tools)
        search = next(tool for tool in tools if tool.name == "search_web")
        assert search.server == "search_server"
        assert search.description == "Поиск в ленте jsonplaceholder или в Википедии"
        assert search.input_schema["required"] == ["query"]
        assert search.to_dict()["server"] == "search_server"
    finally:
        registry.close()


def test_routing_calls_the_right_server(tmp_path):
    """Вызов уходит тому серверу, который объявляет инструмент, и только ему."""
    factory = make_fleet_factory()
    registry = _connected(tmp_path, factory=factory)
    try:
        assert registry.find_tool_by_name("summarize") == "data_server"
        assert registry.find_tool_by_name("save_to_db") == "storage_server"
        assert registry.find_tool_by_name("нет_такого") is None

        result = registry.call_tool("summarize", {"items": [{"title": "RAG"}]})
        assert result.structured == FLEET_RESULTS["summarize"]
        assert factory.by_server("data_server").call_calls == [
            {"server": "data_server", "tool": "summarize",
             "arguments": {"items": [{"title": "RAG"}]}}
        ]
        assert factory.by_server("search_server").call_calls == []
        assert factory.by_server("storage_server").call_calls == []
    finally:
        registry.close()


def test_unknown_tool_and_server_are_explicit_errors(tmp_path):
    """Неизвестный инструмент и сервер — ошибки с перечнем известных."""
    registry = _connected(tmp_path)
    try:
        with pytest.raises(MCPUnknownToolError) as exc:
            registry.call_tool("teleport", {})
        assert "teleport" in str(exc.value) and "search_web" in str(exc.value)

        with pytest.raises(MCPUnknownServerError) as exc:
            registry.tools_of("echo_server")
        assert "echo_server" in str(exc.value) and "search_server" in str(exc.value)
    finally:
        registry.close()


def test_tools_of_uses_file_cache_when_server_is_down(tmp_path):
    """Сервер не поднялся — состав флота и его инструменты видны из кэша файла.

    Это и есть смысл ``tools_cache``: интерфейс и планировщик плана работают с
    каталогом, даже когда сервер недоступен, а не показывают «инструментов нет».
    """
    path = write_servers_file(tmp_path / "mcp_servers.json", names=("search_server",))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["servers"][0]["tools_cache"] = [
        {"name": "search_web", "description": "из кэша",
         "input_schema": {"type": "object"}, "output_schema": {}}]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    factory = make_fleet_factory(errors={"search_server": "сервер не ответил"})
    registry = make_fleet_registry(tmp_path, servers_file=path,
                                  names=("search_server",), factory=factory)
    try:
        registry.connect_all()
        record = registry.servers()[0]
        assert record["connected"] is False and record["state"] == "error"
        assert record["tool_count"] == 1, "число инструментов берётся из кэша"
        assert "не ответил" in record["error"]
        tools = registry.tools_of("search_server")
        assert [tool.name for tool in tools] == ["search_web"]
        assert tools[0].description == "из кэша"
        assert registry.find_tool_by_name("search_web") == "search_server"
        # Поднять упавший сервер по требованию нельзя: отказ приходит наружу.
        with pytest.raises(Exception):
            registry.ensure_connected("search_server")
    finally:
        registry.close()


def test_catalog_survives_disconnect(tmp_path):
    """После отключения флота каталог остаётся доступным (последний известный)."""
    registry = _connected(tmp_path)
    try:
        before = [tool.name for tool in registry.tools_of("data_server")]
        registry.disconnect_all()
        assert registry.connected("data_server") is False
        assert [tool.name for tool in registry.tools_of("data_server")] == before
        assert registry.servers()[0]["state"] == "disconnected"
    finally:
        registry.close()


def test_refresh_tools_writes_cache_to_file(tmp_path):
    """``refresh_tools`` перечитывает каталоги и пишет их в файл конфигурации."""
    path = write_servers_file(tmp_path / "mcp_servers.json",
                              names=("search_server", "data_server"))
    registry = make_fleet_registry(tmp_path, servers_file=path,
                                   names=("search_server", "data_server"))
    try:
        registry.connect_all()
        registry.refresh_tools()
        payload = json.loads(path.read_text(encoding="utf-8"))
        cached = {item["name"]: [tool["name"] for tool in item["tools_cache"]]
                  for item in payload["servers"]}
        assert cached["search_server"] == [tool.name for tool in
                                          FLEET_CATALOGS["search_server"]]
        assert cached["data_server"] == [tool.name for tool in FLEET_CATALOGS["data_server"]]
    finally:
        registry.close()


def test_failed_server_does_not_break_the_others(tmp_path):
    """Сбой одного сервера — данные его записи, остальные продолжают работать."""
    factory = make_fleet_factory(errors={"data_server": "сервер не ответил"})
    registry = _connected(tmp_path, factory=factory)
    try:
        status = {item["name"]: item for item in registry.servers()}
        assert status["search_server"]["connected"] is True
        assert status["storage_server"]["connected"] is True
        assert status["data_server"]["connected"] is False
        assert status["data_server"]["state"] == "error"
        assert "не ответил" in status["data_server"]["error"]
        assert registry.fleet_status()["connected"] == 2
        # Маршрутизация цела: инструменты живых серверов доступны, вызов идёт им.
        assert registry.call_tool("search_web", {"query": "RAG"}).is_error is False
        with pytest.raises(Exception):
            registry.call_tool("summarize", {"items": []})
    finally:
        registry.close()


def test_new_server_in_file_needs_no_code_change(tmp_path):
    """Четвёртый сервер в файле подхватывается перечитыванием без правок кода."""
    path = write_servers_file(tmp_path / "mcp_servers.json",
                              names=("search_server", "data_server", "storage_server"))
    factory = make_fleet_factory(
        catalogs={**FLEET_CATALOGS, "echo_server": ECHO_CATALOG},
        results={**FLEET_RESULTS, "echo": {"text": "эхо"}})
    registry = make_fleet_registry(tmp_path, servers_file=path, factory=factory)
    try:
        registry.connect_all()
        assert registry.fleet_status()["count"] == 3

        write_servers_file(path, names=("search_server", "data_server",
                                       "storage_server", "echo_server"))
        registry.connect_all()
        assert registry.fleet_status()["count"] == 4
        assert registry.find_tool_by_name("echo") == "echo_server"
        assert registry.call_tool("echo", {"text": "привет"}).structured == {"text": "эхо"}
        assert registry.servers()[-1]["name"] == "echo_server"
    finally:
        registry.close()


def test_disappeared_server_is_closed(tmp_path):
    """Сервер, исчезнувший из файла, закрывается и уходит из списка флота."""
    path = write_servers_file(tmp_path / "mcp_servers.json",
                              names=("search_server", "data_server"))
    factory = make_fleet_factory()
    registry = make_fleet_registry(tmp_path, servers_file=path, factory=factory)
    try:
        registry.connect_all()
        closed = factory.by_server("data_server")
        write_servers_file(path, names=("search_server",))
        registry.connect_all()
        assert [item["name"] for item in registry.servers()] == ["search_server"]
        assert closed.closed is True
        with pytest.raises(MCPUnknownServerError):
            registry.tools_of("data_server")
    finally:
        registry.close()


def test_close_disconnects_the_whole_fleet(tmp_path):
    """``close`` (и ``disconnect_all``) закрывает всех: процессов не остаётся."""
    factory = make_fleet_factory()
    registry = _connected(tmp_path, factory=factory)
    registry.disconnect_all()
    assert registry.fleet_status()["connected"] == 0
    assert all(client.closed for client in factory.created)

    factory2 = make_fleet_factory()
    registry2 = _connected(tmp_path, factory=factory2)
    registry2.close()
    assert registry2.fleet_status()["connected"] == 0
    assert registry2.client is None
    assert all(client.closed for client in factory2.created)


def test_broken_config_file_does_not_raise(tmp_path):
    """Испорченный файл конфигурации не роняет старт: флот просто пуст."""
    path = tmp_path / "mcp_servers.json"
    path.write_text("{ это не json", encoding="utf-8")
    registry = make_fleet_registry(tmp_path, servers_file=path)
    try:
        assert registry.connect_all() == []
        assert registry.fleet_status()["count"] == 0
        assert registry.list_all_tools() == []
    finally:
        registry.close()


def test_active_connection_semantics_are_unchanged(tmp_path):
    """Активное соединение дня 17 живёт отдельно от флота и не подменяется им."""
    from mcp_fakes import make_mcp_factory

    factory = make_mcp_factory()
    registry = MCPRegistry(client_factory=factory, servers_file=tmp_path / "none.json")
    try:
        assert registry.status()["state"] == "disconnected"
        registry.connect("uv run python mcp_server/server.py")
        assert registry.status()["connected"] is True
        assert registry.call_active_tool("echo", {}).structured["tool"] == "echo"
        registry.disconnect()
        assert registry.client is None
    finally:
        registry.close()
