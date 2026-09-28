"""Интеграционный тест сервера поиска на настоящем stdio (день 20).

Клиент поднимает ``mcp_servers/search_server/server.py`` дочерним процессом того же
интерпретатора: транспорт MCP настоящий, внешний API подменён локальным стендом
(``--api-base``), а корень локальных источников сужен до временного каталога
(``--file-root``) — сети и правок в папке дня тест не делает.

Здесь фиксируется контракт инструментов: ``inputSchema`` собирается SDK из типов
параметров, ``outputSchema`` — из ``TypedDict``, ``structuredContent`` равен самому
словарю, а ошибка инструмента приходит ДАННЫМИ (``is_error``), а не исключением.
Тест медленнее юнит-тестов (поднимается процесс), поэтому клиент один на тест и
всегда закрывается в ``finally``, а соединяется лениво — в первом тесте.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.services.mcp_client import MCPClient

SERVER = Path(__file__).resolve().parents[2] / "mcp_servers" / "search_server" / "server.py"

#: Имена инструментов сервера поиска.
EXPECTED_TOOLS = {"search_web", "search_local", "fetch_url"}

#: Ожидаемые поля ``outputSchema``: из них собирается ``structuredContent``.
EXPECTED_FIELDS = {
    "search_web": {"query", "source", "source_kind", "count", "items"},
    "search_local": {"query", "path", "count", "items"},
    "fetch_url": {"url", "status", "content_type", "chars", "truncated", "text"},
}

#: Обязательные аргументы инструментов (из типов без значения по умолчанию).
REQUIRED = {"search_web": ["query"], "search_local": ["query"], "fetch_url": ["url"]}

#: Заметка-источник для ``search_local``: два блока, ищем только по первому.
NOTES = (
    "RAG — генерация с опорой на найденные фрагменты\n\n"
    "Чанкинг — нарезка документов на части\n"
)


@pytest.fixture
def notes(tmp_path) -> Path:
    """Файл внутри корня источников: ``--file-root`` указывает на этот же каталог."""
    path = tmp_path / "notes.md"
    path.write_text(NOTES, encoding="utf-8")
    return path


@pytest.fixture
def client(stub_api_base, tmp_path):
    """Клиент на своём сервере поиска: лента — стенд, источники — временный каталог."""
    instance = MCPClient(
        f'{sys.executable} "{SERVER.resolve()}" --api-base {stub_api_base} '
        f'--file-root "{tmp_path}" --timeout 10',
        timeout=30.0,
    )
    try:
        yield instance
    finally:
        instance.close()


def test_catalog_has_three_tools_with_schemas(client):
    """Каталог — ровно три инструмента, у каждого описание и обе схемы."""
    client.connect()
    tools = client.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS

    for tool in tools:
        assert tool.description.strip(), f"у {tool.name} пустое описание"
        assert tool.input_schema["required"] == REQUIRED[tool.name]
        schema = tool.output_schema or {}
        assert EXPECTED_FIELDS[tool.name] <= set(schema.get("properties", {}))

    search_web = next(tool for tool in tools if tool.name == "search_web")
    assert search_web.input_schema["properties"]["limit"]["type"] == "integer"
    assert search_web.input_schema["properties"]["source"]["default"] == "posts"
    fetch = next(tool for tool in tools if tool.name == "fetch_url")
    assert fetch.input_schema["properties"]["max_chars"]["type"] == "integer"


def test_search_web_reads_the_feed(client):
    """``search_web`` возвращает структурированные элементы ленты, а не строку."""
    client.connect()
    result = client.call_tool("search_web", {
        "query": "Post 4", "source": "posts", "limit": 2,
    })
    assert result.is_error is False
    assert result.structured["source_kind"] == "api"
    assert result.structured["count"] == 2
    assert [item["id"] for item in result.structured["items"]] == ["post:4", "post:40"]
    assert result.duration_ms >= 0


def test_search_local_reads_the_notes_file(client, notes):
    """``search_local`` находит блок файла внутри ``--file-root`` прогона."""
    client.connect()
    result = client.call_tool("search_local", {
        "query": "RAG", "path": notes.name, "limit": 5,
    })
    assert result.is_error is False
    assert result.structured["path"] == notes.name
    assert result.structured["count"] == 1
    item = result.structured["items"][0]
    assert item["title"].startswith("RAG")
    assert item["metadata"] == {"path": notes.name, "block": "1"}


def test_fetch_url_reads_the_stub_page(client, stub_api_base):
    """``fetch_url`` отдаёт текст страницы без тегов и без содержимого script."""
    client.connect()
    result = client.call_tool("fetch_url", {
        "url": f"{stub_api_base}/html", "max_chars": 4000,
    })
    assert result.is_error is False
    assert result.structured["status"] == 200
    assert result.structured["content_type"].startswith("text/html")
    assert "Заголовок стенда" in result.structured["text"]
    assert "alert" not in result.structured["text"]
    assert result.structured["chars"] == len(result.structured["text"])
    assert result.structured["truncated"] is False


def test_tool_error_comes_as_data(client):
    """``file://`` — ответ с ``isError`` и текстом про http, а не падение процесса."""
    client.connect()
    result = client.call_tool("fetch_url", {"url": "file:///C:/Windows/win.ini"})
    assert result.is_error is True
    assert "http://" in result.text or "https://" in result.text
    assert result.structured is None
