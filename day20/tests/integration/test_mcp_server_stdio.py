"""Интеграционный тест своего MCP-сервера на настоящем stdio (день 19).

Проверяется весь путь целиком: клиент поднимает ``day20/mcp_server/server.py``
дочерним процессом того же интерпретатора, а внешний API подменяется локальным
стендом (``tests/stub_api.py``) — в сеть тест не ходит, но HTTP-запросы и разбор
ответов настоящие. Здесь же фиксируется контракт инструментов: ``input_schema``
собирается SDK из типов параметров, ``output_schema`` — из ``TypedDict``, а
``structuredContent`` равен самому словарю.

Инструменты композиции (день 19) проверяются РЕАЛЬНЫМИ вызовами: ``search`` читает
файл внутри папки дня и таблицу базы дня, ``summarize`` без ключа переходит на
агрегацию (``--llm off``), ``save_to_file`` пишет файл в переданный каталог.
Каталоги и пути — временные (``tmp_path``), поэтому рабочая папка дня не меняется.

Тест медленнее юнит-тестов (поднимается процесс и HTTP-стенд), поэтому клиент в
фикстуре один на тест и всегда закрывается в ``finally``.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

from backend.services.mcp_client import MCPClient, MCPNotConnectedError

SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_server" / "server.py"

#: Корень дня: корень источников ``file:`` у сервера прогона.
DAY_ROOT = SERVER.resolve().parents[1]

#: Имена инструментов, которые обязан публиковать сервер дня (день 19: девять —
#: три читают внешний API, три ставят фоновые задачи, три собирают пайплайн).
EXPECTED_TOOLS = {
    "get_user", "get_post", "list_user_posts",
    "schedule_reminder", "collect_data", "generate_summary",
    "search", "summarize", "save_to_file",
}

#: Текст заметки-источника: один абзац — один элемент результата поиска.
NOTE = "RAG — генерация с опорой на найденные фрагменты\n\nЧанкинг — нарезка документов\n"


@pytest.fixture
def db_path(tmp_path) -> Path:
    """База дня с таблицей ``pipeline_steps`` — источник ``sqlite:`` у поиска."""
    path = tmp_path / "agents.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE pipeline_steps (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tool_name TEXT, input_args TEXT, output_result TEXT)"
        )
        connection.executemany(
            "INSERT INTO pipeline_steps (tool_name, input_args, output_result) "
            "VALUES (?, ?, ?)",
            [("search", '{"query": "RAG"}', '{"count": 2}'),
             ("summarize", '{"style": "short"}', '{"engine": "aggregation"}')],
        )
        connection.commit()
    return path


@pytest.fixture
def notes(tmp_path) -> Path:
    """Файл внутри папки дня — источник ``file:`` у поиска (путь относительный)."""
    path = DAY_ROOT / "output" / "stdio-notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NOTE, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture
def client(stub_api_base, tmp_path, db_path):
    """Клиент на своём сервере: цель — команда запуска с путями прогона."""
    instance = MCPClient(
        f'{sys.executable} "{SERVER.resolve()}" --api-base {stub_api_base} '
        f'--llm off --output-dir "{tmp_path}" --file-root "{DAY_ROOT}" '
        f'--db-path "{db_path}"',
        timeout=30.0,
    )
    try:
        yield instance
    finally:
        instance.close()


def test_catalog_has_nine_tools_with_schemas(client):
    """Каталог — девять инструментов дня, у каждого схемы аргументов и результата."""
    client.connect()
    tools = client.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS

    user = next(tool for tool in tools if tool.name == "get_user")
    assert user.input_schema.get("required") == ["user_id"]
    assert user.input_schema["properties"]["user_id"]["type"] == "integer"
    assert user.output_schema.get("properties"), "output_schema не опубликована"
    assert "name" in user.output_schema["properties"]
    assert user.description

    posts = next(tool for tool in tools if tool.name == "list_user_posts")
    assert posts.input_schema["required"] == ["user_id"]
    assert posts.input_schema["properties"]["limit"]["default"] == 5


def test_composition_tool_schemas_are_typed(client):
    """Схемы трёх инструментов композиции собираются из аннотаций и TypedDict."""
    client.connect()
    tools = {tool.name: tool for tool in client.list_tools()}

    search = tools["search"]
    assert search.input_schema["required"] == ["query"]
    assert search.input_schema["properties"]["limit"]["type"] == "integer"
    assert search.input_schema["properties"]["source"]["type"] == "string"
    assert {"count", "items", "source_kind"} <= set(search.output_schema["properties"])

    summarize = tools["summarize"]
    assert summarize.input_schema["required"] == ["items"]
    assert summarize.input_schema["properties"]["items"]["type"] == "array"
    assert {"summary_text", "key_points", "engine"} <= set(
        summarize.output_schema["properties"])

    save = tools["save_to_file"]
    assert save.input_schema["required"] == ["content"]
    assert {"filename", "size_bytes", "filepath"} <= set(
        save.output_schema["properties"])


def test_call_returns_structured_user(client):
    """Вызов возвращает структурированные данные пользователя, а не только текст."""
    client.connect()
    result = client.call_tool("get_user", {"user_id": 1})
    assert result.is_error is False
    assert result.structured["name"] and result.structured["email"]
    assert result.structured["city"]
    assert result.tool == "get_user" and result.arguments == {"user_id": 1}
    assert result.duration_ms >= 0


def test_call_reports_missing_user_as_tool_error(client):
    """Несуществующий id — ответ с ``isError`` и текстом про 404, а не исключение."""
    client.connect()
    result = client.call_tool("get_user", {"user_id": 999})
    assert result.is_error is True
    assert "999" in result.text and "404" in result.text
    assert result.structured is None


def test_list_user_posts_respects_limit(client):
    """``limit`` ограничивает ответ, а ``count`` считает именно возвращённые посты."""
    client.connect()
    result = client.call_tool("list_user_posts", {"user_id": 1, "limit": 2})
    assert result.is_error is False
    assert result.structured["count"] == 2
    assert [post["id"] for post in result.structured["posts"]] == [1, 2]


def test_call_requires_connection(client):
    """Без соединения вызов недоступен: явная ошибка, а не пустой результат."""
    with pytest.raises(MCPNotConnectedError):
        client.call_tool("get_user", {"user_id": 1})


# ---------- инструменты композиции (день 19) ----------
def test_search_reads_a_file_of_the_day(client, notes):
    """``search`` по источнику ``file:`` находит блоки файла и возвращает элементы."""
    client.connect()
    result = client.call_tool("search", {
        "query": "RAG", "source": "file:output/stdio-notes.md", "limit": 5,
    })
    assert result.is_error is False
    assert result.structured["source_kind"] == "file"
    assert result.structured["count"] == 1
    item = result.structured["items"][0]
    assert item["title"].startswith("RAG")
    assert item["metadata"]["total_blocks"] == 2


def test_search_reads_a_table_of_the_day(client):
    """``search`` по источнику ``sqlite:`` читает таблицу базы дня только на чтение."""
    client.connect()
    result = client.call_tool("search", {
        "query": "summarize", "source": "sqlite:pipeline_steps", "limit": 5,
    })
    assert result.is_error is False
    assert result.structured["source_kind"] == "sqlite"
    assert result.structured["count"] == 1
    assert result.structured["items"][0]["id"].startswith("sqlite:pipeline_steps:")


def test_search_reports_bad_source_as_tool_error(client):
    """Неизвестный источник — ошибка инструмента с перечнем доступных, не падение."""
    client.connect()
    result = client.call_tool("search", {"query": "RAG", "source": "telepathy"})
    assert result.is_error is True
    assert "не поддержан" in result.text and "sqlite:" in result.text


def test_summarize_falls_back_to_aggregation(client):
    """Без ключа ``--llm off`` сводку собирает агрегация: движок ``aggregation``."""
    client.connect()
    result = client.call_tool("summarize", {
        "items": [{"title": "RAG", "content": "поиск"}, {"title": "Чанкинг",
                                                          "content": "нарезка"}],
        "style": "bullets",
        "max_length": 400,
    })
    assert result.is_error is False
    assert result.structured["engine"] == "aggregation"
    assert result.structured["total_items"] == 2
    assert result.structured["key_points"] == ["RAG", "Чанкинг"]
    assert result.structured["summary_text"].startswith("- RAG")


def test_summarize_rejects_empty_list(client):
    """Пустой список — ошибка инструмента: сводить нечего."""
    client.connect()
    result = client.call_tool("summarize", {"items": []})
    assert result.is_error is True
    assert "пуст" in result.text


def test_save_to_file_writes_into_the_given_directory(client, tmp_path):
    """``save_to_file`` пишет файл в переданный каталог и возвращает его размер."""
    client.connect()
    result = client.call_tool("save_to_file", {
        "content": "# Сводка\nRAG — это поиск", "filename": "stdio-run.md",
        "format": "md",
    })
    assert result.is_error is False
    target = tmp_path / result.structured["filename"]
    assert target.is_file()
    assert target.read_text(encoding="utf-8").startswith("# Сводка")
    assert result.structured["size_bytes"] == target.stat().st_size


def test_save_to_file_rejects_a_path_in_the_name(client):
    """Имя с путём — ошибка инструмента: выйти за каталог вывода нельзя."""
    client.connect()
    result = client.call_tool("save_to_file", {
        "content": "текст", "filename": "../escape.md", "format": "md",
    })
    assert result.is_error is True
    assert "«..»" in result.text


def test_full_pipeline_over_stdio(client, notes, tmp_path):
    """Три инструмента по очереди: поиск → сводка → файл (данные передаются вручную)."""
    client.connect()
    found = client.call_tool("search", {
        "query": "RAG", "source": "file:output/stdio-notes.md", "limit": 5})
    summary = client.call_tool("summarize", {
        "items": found.structured["items"], "style": "short", "max_length": 300})
    saved = client.call_tool("save_to_file", {
        "content": summary.structured["summary_text"], "filename": "stdio-pipeline.md",
        "format": "txt"})

    assert summary.is_error is False and saved.is_error is False
    assert summary.structured["total_items"] == found.structured["count"]
    # Расширение имени заменяется на запрошенный формат: «.md» при format="txt"
    # стало бы файлом, который формат не описывает.
    assert saved.structured["filename"] == "stdio-pipeline.txt"
    assert (tmp_path / "stdio-pipeline.txt").read_text(
        encoding="utf-8").startswith(summary.structured["summary_text"])
