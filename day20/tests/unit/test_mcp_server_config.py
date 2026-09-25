"""Тесты записи кэша инструментов в файл флота (день 20).

``save_tools_cache`` меняет РОВНО поле ``tools_cache`` одного сервера: файл читает и
реестр, и человек, поэтому ручные правки (описания, порядок записей, добавленный
сервер) обязаны пережить обновление кэша, а запись — быть атомарной (``.tmp`` плюс
``os.replace``), чтобы второй процесс не увидел половину JSON.
"""
import json

import pytest

from backend.core.mcp_server_config import load_specs, save_tools_cache
from backend.domain.mcp_server_spec import MCPServerSpecError
from backend.domain.mcp_tools import MCPToolInfo


def _write(path, records) -> None:
    """Пишет файл флота в форме, которую правит человек (с описаниями)."""
    path.write_text(json.dumps({"servers": records}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _records() -> list[dict]:
    return [
        {"name": "search_server", "command": "uv", "args": ["run", "s.py"],
         "description": "Поиск", "tools_cache": []},
        {"name": "data_server", "command": "uv", "args": ["run", "d.py"],
         "description": "Данные", "tools_cache": [{"name": "старый"}]},
        {"name": "storage_server", "command": "uv", "args": ["run", "st.py"],
         "description": "Хранение", "tools_cache": []},
    ]


def test_cache_goes_only_to_the_named_server(tmp_path):
    """Кэш обновляется у одного сервера; остальные записи и их порядок целы."""
    path = tmp_path / "mcp_servers.json"
    _write(path, _records())
    tools = [MCPToolInfo(name="search_web", description="поиск",
                         input_schema={"type": "object"},
                         output_schema={"type": "object"}),
             MCPToolInfo(name="search_local", description="файл")]
    save_tools_cache("search_server", tools, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [item["name"] for item in payload["servers"]] == [
        "search_server", "data_server", "storage_server"]
    assert [tool["name"] for tool in payload["servers"][0]["tools_cache"]] == [
        "search_web", "search_local"]
    assert payload["servers"][0]["tools_cache"][0]["input_schema"] == {"type": "object"}
    assert payload["servers"][1]["tools_cache"] == [{"name": "старый"}]
    assert payload["servers"][0]["description"] == "Поиск"
    assert payload["servers"][2]["args"] == ["run", "st.py"]


def test_dictionaries_are_accepted_too(tmp_path):
    """Кэш можно передать словарями (отчёты и скрипты так и делают)."""
    path = tmp_path / "mcp_servers.json"
    _write(path, _records())
    save_tools_cache("data_server", [{"name": "summarize"}], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["servers"][1]["tools_cache"] == [{"name": "summarize"}]


def test_missing_file_is_an_error(tmp_path):
    """Файла нет — ошибка: конфигурацию флота заводит человек, а не кэш."""
    with pytest.raises(MCPServerSpecError) as exc:
        save_tools_cache("search_server", [], tmp_path / "нет.json")
    assert "не найден" in str(exc.value)


def test_unknown_server_is_an_error(tmp_path):
    """Неизвестное имя сервера — ошибка со списком известных."""
    path = tmp_path / "mcp_servers.json"
    _write(path, _records())
    with pytest.raises(MCPServerSpecError) as exc:
        save_tools_cache("echo_server", [], path)
    assert "не объявлен" in str(exc.value) and "search_server" in str(exc.value)


def test_no_temporary_file_is_left_behind(tmp_path):
    """Атомарная запись не оставляет ``.tmp``: файл читают и реестр, и человек."""
    path = tmp_path / "mcp_servers.json"
    _write(path, _records())
    save_tools_cache("search_server", [{"name": "search_web"}], path)
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_load_specs_uses_default_file(tmp_path, monkeypatch):
    """``load_specs`` без пути читает файл из ``config`` (тот же, что у приложения)."""
    from backend.core import config

    path = tmp_path / "mcp_servers.json"
    _write(path, _records())
    monkeypatch.setattr(config, "MCP_SERVERS_FILE", path)
    assert [spec.name for spec in load_specs()] == [
        "search_server", "data_server", "storage_server"]
