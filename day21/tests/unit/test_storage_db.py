"""База ``storage_server`` (``storage.db`` на ``sqlite3``): запись и список строк.

Проверяется, что строки ложатся в СВОЙ файл (не ``agents.db``), возвращают id и
момент в ISO-8601 UTC, идут свежими вверх, фильтруются по виду, хранят метаданные
JSON-строкой, а пустой вид/заголовок и слишком длинный текст отклоняются.
"""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from mcp_servers.storage_server import config, db
from mcp_servers.storage_server.db import SavedRecordError


@pytest.fixture
def storage_db(tmp_path):
    """Изолированный файл базы: инструмент пишет только в него."""
    original = db.db_path()
    db.configure(tmp_path / "storage.db")
    yield db
    db.configure(original)


def _metadata_of(db_module) -> str:
    """Столбец ``metadata`` единственной строки — как он лежит в базе."""
    with sqlite3.connect(str(db_module.db_path())) as connection:
        return connection.execute("SELECT metadata FROM saved_records").fetchone()[0]


def test_insert_returns_record_with_id(storage_db):
    """``insert`` отдаёт id строки, вид, заголовок, источник, размер и момент."""
    record = storage_db.insert("orchestration", "Сводка", "текст сводки", "search_web")
    assert record["row_id"] == 1
    assert record["kind"] == "orchestration"
    assert record["title"] == "Сводка"
    assert record["source"] == "search_web"
    assert record["size_bytes"] == len("текст сводки".encode("utf-8"))
    moment = datetime.fromisoformat(record["created_at"])
    assert moment.tzinfo is not None
    assert moment.utcoffset() == timezone.utc.utcoffset(None)


def test_insert_writes_into_its_own_file(storage_db):
    """Строка ложится в файл базы сервера, а не в ``agents.db`` дня."""
    storage_db.insert("orchestration", "Сводка", "текст")
    assert storage_db.db_path().is_file()
    with sqlite3.connect(str(storage_db.db_path())) as connection:
        rows = connection.execute("SELECT title FROM saved_records").fetchall()
    assert rows == [("Сводка",)]


def test_list_rows_returns_newest_first_with_kind_filter(storage_db):
    """Строки идут свежими вверх, а ``kind`` оставляет только нужный вид."""
    storage_db.insert("file", "Первый", "а")
    storage_db.insert("db", "Второй", "б")
    storage_db.insert("file", "Третий", "в")
    assert [row["title"] for row in storage_db.list_rows()] == ["Третий", "Второй", "Первый"]
    file_rows = storage_db.list_rows(kind="file")
    assert [row["title"] for row in file_rows] == ["Третий", "Первый"]
    assert all(row["kind"] == "file" for row in file_rows)


def test_list_rows_all_synonym_means_no_filter(storage_db):
    """``kind="all"`` — то же, что отсутствие фильтра: и файлы, и строки базы."""
    storage_db.insert("file", "Первый", "а")
    storage_db.insert("db", "Второй", "б")
    assert len(storage_db.list_rows(kind="all")) == 2


@pytest.mark.parametrize("limit,expected", [
    (0, config.LIST_LIMIT_MIN),
    (1, 1),
    (999, 3),
])
def test_list_rows_clamps_limit(storage_db, limit, expected):
    """``limit`` подтягивается к границам ``LIST_LIMIT_MIN..LIST_LIMIT_MAX``."""
    for index in range(3):
        storage_db.insert("file", f"Запись {index}", "текст")
    assert len(storage_db.list_rows(limit=limit)) == expected


def test_metadata_round_trips_as_json(storage_db):
    """Метаданные лежат JSON-строкой с читаемым русским текстом и разбираются обратно."""
    storage_db.insert("orchestration", "Сводка", "текст",
                      metadata={"file": "output/сводка.md", "keywords": "RAG, чанкинг"})
    raw = _metadata_of(storage_db)
    assert json.loads(raw) == {"file": "output/сводка.md", "keywords": "RAG, чанкинг"}
    assert "сводка" in raw


def test_metadata_defaults_to_empty_object(storage_db):
    """Без метаданных в базу ложится пустой объект, а не ``NULL``."""
    storage_db.insert("file", "Без метаданных", "текст")
    assert json.loads(_metadata_of(storage_db)) == {}


@pytest.mark.parametrize("kind,title", [
    ("", "Заголовок"),
    ("   ", "Заголовок"),
    ("file", ""),
    ("file", "  "),
])
def test_empty_kind_or_title_is_rejected(storage_db, kind, title):
    """Пустой вид или заголовок — ошибка: строке нечем опознать себя."""
    with pytest.raises(SavedRecordError):
        storage_db.insert(kind, title, "текст")


def test_long_content_is_rejected(storage_db):
    """Текст длиннее ``FILE_CONTENT_MAX`` в базу не пишется."""
    with pytest.raises(SavedRecordError) as exc:
        storage_db.insert("file", "Длинный", "я" * (config.FILE_CONTENT_MAX + 1))
    assert str(config.FILE_CONTENT_MAX) in str(exc.value)


def test_long_fields_are_truncated(storage_db):
    """Вид, заголовок и источник обрезаются до своих границ, запись не падает."""
    record = storage_db.insert("к" * 200, "з" * 300, "текст", source="и" * 500)
    assert len(record["kind"]) == config.KIND_MAX
    assert len(record["title"]) == config.TITLE_MAX
    assert len(record["source"]) == config.SOURCE_MAX
