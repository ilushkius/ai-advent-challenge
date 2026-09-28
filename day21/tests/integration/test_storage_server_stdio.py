"""Интеграционный тест ``storage_server`` на настоящем stdio (день 20).

Сервер запускается дочерним процессом (``sys.executable`` + путь к ``server.py``) с
временными ``--output-dir`` и ``--db-path``: файлы результатов и база не трогают
артефакты дня. Проверяются каталог из четырёх инструментов, их схемы и настоящие
вызовы: запись файла и чтение его обратно, запись строки в базу и её выдача,
ошибки данными (чужой вид выборки, опасное имя файла).
"""
import sys
from pathlib import Path

import pytest

from backend.services.mcp_client import MCPClient

from mcp_servers.storage_server import config

SERVER = (Path(__file__).resolve().parents[1] / ".."
          / "mcp_servers" / "storage_server" / "server.py")

#: Имена инструментов, которые обязан публиковать сервер сохранения.
EXPECTED_TOOLS = {"save_to_file", "save_to_db", "list_saved", "load_from_file"}


@pytest.fixture
def output_dir(tmp_path) -> Path:
    """Каталог файлов результатов для конкретного теста."""
    return tmp_path / "out"


@pytest.fixture
def db_file(tmp_path) -> Path:
    """Файл базы сохранённых строк для конкретного теста."""
    return tmp_path / "storage.db"


@pytest.fixture
def client(output_dir, db_file):
    """Клиент на своём сервере: цель — команда запуска с путями прогона."""
    instance = MCPClient(
        f'{sys.executable} "{SERVER.resolve()}" '
        f'--output-dir "{output_dir}" --db-path "{db_file}"',
        timeout=30.0,
    )
    try:
        yield instance
    finally:
        instance.close()


def test_catalog_has_four_tools_with_schemas(client):
    """Каталог — четыре инструмента сохранения, у каждого описания и схемы."""
    client.connect()
    tools = {tool.name: tool for tool in client.list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    for tool in tools.values():
        assert tool.description
        assert tool.output_schema.get("properties"), f"{tool.name}: пустая outputSchema"


def test_tool_schemas_are_typed(client):
    """Схемы собраны из аннотаций и ``TypedDict``: обязательные поля и результаты."""
    client.connect()
    tools = {tool.name: tool for tool in client.list_tools()}

    save_file = tools["save_to_file"]
    assert save_file.input_schema["required"] == ["content"]
    assert save_file.input_schema["properties"]["format"]["default"] == "md"
    assert {"filename", "filepath", "size_bytes", "format", "saved_at"} <= set(
        save_file.output_schema["properties"])

    save_db = tools["save_to_db"]
    assert save_db.input_schema["required"] == ["kind", "title", "content"]
    assert {"row_id", "kind", "title", "source", "size_bytes", "created_at"} <= set(
        save_db.output_schema["properties"])

    listed = tools["list_saved"]
    assert listed.input_schema["properties"]["kind"]["default"] == "all"
    assert listed.input_schema["properties"]["limit"]["type"] == "integer"
    assert {"files", "rows", "count", "kind"} <= set(listed.output_schema["properties"])

    loaded = tools["load_from_file"]
    assert loaded.input_schema["required"] == ["filename"]
    assert {"filename", "filepath", "chars", "format", "text"} <= set(
        loaded.output_schema["properties"])


def test_save_then_load_round_trip(client, output_dir):
    """Файл записывается в каталог вывода и читается обратно тем же текстом."""
    client.connect()
    saved = client.call_tool("save_to_file", {
        "content": "сводка про RAG", "filename": "итог", "format": "md"})
    assert saved.is_error is False
    assert saved.structured["filename"] == "итог.md"
    assert saved.structured["format"] == "md"
    assert (output_dir / "итог.md").is_file()
    assert saved.structured["size_bytes"] == (output_dir / "итог.md").stat().st_size

    loaded = client.call_tool("load_from_file", {"filename": "итог.md"})
    assert loaded.is_error is False
    assert loaded.structured["text"] == "сводка про RAG\n"
    assert loaded.structured["chars"] == len("сводка про RAG\n")
    assert loaded.structured["format"] == "md"


def test_save_to_db_then_list_saved_rows(client):
    """Строка ложится в базу, а ``list_saved(kind="row")`` её возвращает."""
    client.connect()
    saved = client.call_tool("save_to_db", {
        "kind": "orchestration", "title": "Сводка", "content": "текст",
        "source": "search_web", "metadata": {"step": 5}})
    assert saved.is_error is False
    assert saved.structured["row_id"] == 1
    assert saved.structured["kind"] == "orchestration"

    listed = client.call_tool("list_saved", {"kind": "row"})
    assert listed.is_error is False
    assert listed.structured["kind"] == "row"
    assert listed.structured["count"] == 1
    assert listed.structured["files"] == []
    assert listed.structured["rows"][0]["row_id"] == 1
    assert listed.structured["rows"][0]["title"] == "Сводка"


def test_list_saved_all_shows_files_and_rows(client):
    """``kind="all"`` показывает и файл, и строку базы, а ``count`` их суммирует."""
    client.connect()
    client.call_tool("save_to_file", {"content": "файл", "filename": "итог"})
    client.call_tool("save_to_db", {"kind": "orchestration", "title": "Строка",
                                    "content": "текст"})
    listed = client.call_tool("list_saved", {"kind": "all"})
    assert listed.is_error is False
    assert listed.structured["count"] == 2
    assert [item["filename"] for item in listed.structured["files"]] == ["итог.md"]
    assert [row["title"] for row in listed.structured["rows"]] == ["Строка"]


def test_list_saved_reports_unknown_kind_as_tool_error(client):
    """Чужой вид выборки — ошибка данными с перечнем допустимых, не падение."""
    client.connect()
    result = client.call_tool("list_saved", {"kind": "cloud"})
    assert result.is_error is True
    assert "cloud" in result.text
    for allowed in config.LIST_KINDS:
        assert allowed in result.text


def test_save_to_file_rejects_path_in_name(client, output_dir):
    """Имя с «..» — ошибка инструмента: за каталог вывода выйти нельзя."""
    client.connect()
    result = client.call_tool("save_to_file", {"content": "текст",
                                               "filename": "../escape.md"})
    assert result.is_error is True
    assert "«..»" in result.text
    assert not (output_dir.parent / "escape.md").exists()


def test_save_to_file_rejects_too_long_text(client):
    """Текст длиннее ``FILE_CONTENT_MAX`` — ошибка данными с пределом в тексте."""
    client.connect()
    result = client.call_tool("save_to_file",
                              {"content": "я" * (config.FILE_CONTENT_MAX + 1)})
    assert result.is_error is True
    assert str(config.FILE_CONTENT_MAX) in result.text


def test_load_from_file_reports_missing_file(client):
    """Отсутствующего файла нет — ошибка с его именем, а не пустой текст."""
    client.connect()
    result = client.call_tool("load_from_file", {"filename": "нет-такого.md"})
    assert result.is_error is True
    assert "нет-такого.md" in result.text
