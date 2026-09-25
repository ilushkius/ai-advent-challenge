"""Источник ``sqlite:`` инструмента ``search`` (день 19): таблицы базы дня.

Проверяются правила чтения базы дня: список таблиц закрытый (белый список
``config.SQLITE_SOURCES`` — чужой SQL не выполняется), соединение только на чтение,
строки отдаются свежими вперёд, LIKE идёт по объявленным колонкам, а отсутствие
базы — понятная ошибка, а не трассировка ``sqlite3``.

Материал (строки таблиц и создание базы) живёт в
``tests/search_sources_fakes.py``; источник-файл — в ``test_search_sources.py``,
лента внешнего API — в ``test_search_sources_api.py``.
"""
from __future__ import annotations

import pytest

from mcp_server import config
from mcp_server.search_sources import SearchSourceError, search_items

from search_sources_fakes import configure_sources, make_sqlite_db


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """Свой каталог источников и путь базы: настройки процесса возвращаются после теста."""
    return configure_sources(tmp_path, monkeypatch)


@pytest.fixture
def sqlite_db(sources):
    """База дня с двумя таблицами поиска: шаги пайплайна и собранные данные."""
    return make_sqlite_db(sources)


def test_sqlite_source_orders_rows_newest_first(sqlite_db):
    """Строки отдаются свежими вперёд, id — ``sqlite:<таблица>:<id>``, колонки в метаданных."""
    kind, items = search_items("", "sqlite:pipeline_steps", 10)

    assert kind == "sqlite"
    assert [item["id"] for item in items] == [
        "sqlite:pipeline_steps:3", "sqlite:pipeline_steps:2", "sqlite:pipeline_steps:1",
    ]
    assert items[0]["title"] == "pipeline_steps: save_to_file"
    assert items[0]["content"] == (
        'save_to_file | {"filename": "итог.md"} | Файл сохранён'
    )
    assert items[0]["url"] == ""
    assert items[0]["metadata"] == {
        "table": "pipeline_steps",
        "columns": ["id", "tool_name", "input_args", "output_result"],
    }


@pytest.mark.parametrize("query,expected", [
    ("rag", ["sqlite:pipeline_steps:2", "sqlite:pipeline_steps:1"]),
    ("save_to_file", ["sqlite:pipeline_steps:3"]),
    ("нет-такого", []),
])
def test_sqlite_source_filters_by_declared_columns(sqlite_db, query, expected):
    """LIKE идёт по объявленным колонкам таблицы: другая таблица того же слова не даёт."""
    _, items = search_items(query, "sqlite:pipeline_steps", 10)

    assert [item["id"] for item in items] == expected


def test_sqlite_source_respects_limit(sqlite_db):
    """``limit`` ограничивает число строк, берутся самые свежие."""
    _, one = search_items("", "sqlite:pipeline_steps", 1)
    _, two = search_items("", "sqlite:pipeline_steps", 2)

    assert [item["id"] for item in one] == ["sqlite:pipeline_steps:3"]
    assert [item["id"] for item in two] == [
        "sqlite:pipeline_steps:3", "sqlite:pipeline_steps:2",
    ]


def test_sqlite_source_takes_url_from_source_url_column(sqlite_db):
    """Колонка ``source_url`` попадает в ``url`` элемента, значения склеены через ``|``."""
    _, items = search_items("rag", "sqlite:collected_data", 5)

    assert len(items) == 1
    assert items[0]["id"] == "sqlite:collected_data:1"
    assert items[0]["title"] == "collected_data: Заметки про RAG"
    assert items[0]["url"] == "https://example.test/rag"
    assert items[0]["content"] == (
        "Заметки про RAG | https://example.test/rag | chunking и эмбеддинги"
    )
    assert items[0]["metadata"]["columns"] == [
        "id", "name", "source_url", "payload",
    ]


@pytest.mark.parametrize("table", ["pipeline_runs", "users", ""])
def test_sqlite_unknown_table_lists_available(sqlite_db, table):
    """Закрытый белый список: чужая таблица — ошибка с перечнем доступных таблиц."""
    with pytest.raises(SearchSourceError) as exc:
        search_items("", f"sqlite:{table}", 5)

    text = str(exc.value)
    assert "недоступна" in text
    for name in config.SQLITE_SOURCES:
        assert name in text


def test_sqlite_missing_database_is_reported(sources):
    """Базы дня нет — ошибка «недоступна в базе дня», а не трассировка ``sqlite3``."""
    with pytest.raises(SearchSourceError) as exc:
        search_items("", "sqlite:pipeline_steps", 5)
    assert "недоступна в базе дня" in str(exc.value)


def test_search_items_returns_kind_and_items(sqlite_db):
    """Вид источника возвращается рядом с элементами (поле ``source_kind`` результата)."""
    kind, items = search_items("", "sqlite:pipeline_steps", 5)

    assert kind == "sqlite"
    assert len(items) == 3
