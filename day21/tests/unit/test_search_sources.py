"""Источник ``file:`` инструмента ``search`` (день 19): блоки файла внутри дня.

Проверяются правила, которые делают локальный источник безопасным и предсказуемым:
читается только папка дня (относительный путь, ``../`` и абсолютный отклоняются),
файл разбивается на блоки по пустым строкам, фильтр ищет подстроку без учёта
регистра, а ``limit`` зажимается в границы дня.

Заглушка клиента jsonplaceholder и строки таблиц живут в
``tests/search_sources_fakes.py``; здесь — источник-файл и разбор самой строки
источника. Таблица SQLite проверяется в ``test_search_sources_sqlite.py``, лента
внешнего API — в ``test_search_sources_api.py``.
"""
from __future__ import annotations

import pytest

from mcp_server import config, search_sources
from mcp_server.search_sources import SearchSourceError, parse_source, search_items

from search_sources_fakes import NOTES, configure_sources, write_notes


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """Свой каталог источников и путь базы: настройки процесса возвращаются после теста."""
    return configure_sources(tmp_path, monkeypatch)


# ---------- разбор источника ----------
@pytest.mark.parametrize("source,expected", [
    ("posts", ("api", "posts")),
    ("users", ("api", "users")),
    ("file:output/x.md", ("file", "output/x.md")),
    ("sqlite:collected_data", ("sqlite", "collected_data")),
    ("  file:a.md  ", ("file", "a.md")),
])
def test_parse_source_kinds(source, expected):
    """Вид источника и уточнение разбираются по префиксу, лишние пробелы снимаются."""
    assert parse_source(source) == expected


@pytest.mark.parametrize("source", ["weather", "post", "", "files:a.md", "FILE:a.md"])
def test_parse_source_unknown_lists_available(source):
    """Неизвестный источник — ошибка, текст которой перечисляет доступные виды."""
    with pytest.raises(SearchSourceError) as exc:
        parse_source(source)
    text = str(exc.value)
    assert "не поддержан" in text
    for hint in ("posts", "users", "file:<путь>", "sqlite:<таблица>"):
        assert hint in text


# ---------- источник ``file:`` ----------
def test_file_source_returns_one_item_per_block(sources):
    """Каждый блок файла — элемент с номером блока, заголовком и общим числом блоков."""
    source = write_notes(sources, NOTES)

    kind, items = search_items("", source, 5)

    assert kind == "file"
    assert [item["id"] for item in items] == [
        "file:notes.md#1", "file:notes.md#2", "file:notes.md#3",
    ]
    assert items[0]["title"] == "RAG: что такое"
    assert items[0]["content"].startswith("RAG: что такое\n")
    assert items[0]["url"] == ""
    assert items[0]["metadata"] == {
        "path": "notes.md", "block": 1, "total_blocks": 3,
    }
    assert items[2]["metadata"]["block"] == 3


def test_file_source_skips_empty_blocks(sources):
    """Пустые блоки (лишние пустые строки) в выдачу не попадают и номеров не занимают."""
    source = write_notes(sources, ["Первый\nТекст.", "", "", "Второй\nТекст."])

    _, items = search_items("", source, 5)

    assert [item["id"] for item in items] == ["file:notes.md#1", "file:notes.md#2"]
    assert items[0]["metadata"]["total_blocks"] == 2


def test_file_source_title_is_first_line_truncated(sources):
    """Заголовок блока — его первая строка, обрезанная до ``SEARCH_TITLE_MAX``."""
    long_title = "З" * (config.SEARCH_TITLE_MAX + 50)
    source = write_notes(sources, [f"{long_title}\nТело блока."])

    _, items = search_items("", source, 5)

    assert items[0]["title"] == "З" * config.SEARCH_TITLE_MAX


@pytest.mark.parametrize("query,expected", [
    ("fsm", ["file:notes.md#2"]),
    ("ГИБРИДНЫЙ", ["file:notes.md#1"]),
    ("РАСПИСАНИЮ", ["file:notes.md#3"]),
    ("квантовые вычисления", []),
])
def test_file_source_filters_blocks_by_substring(sources, query, expected):
    """Фильтр ищет подстроку в блоке без учёта регистра, нумерация блоков сохраняется."""
    source = write_notes(sources, NOTES)

    _, items = search_items(query, source, 5)

    assert [item["id"] for item in items] == expected


@pytest.mark.parametrize("limit,count", [(0, 1), (1, 1), (2, 2), (7, 3)])
def test_file_source_limit_caps_items(sources, limit, count):
    """``limit`` ограничивает выдачу, а неположительный зажимается до минимума."""
    source = write_notes(sources, NOTES)

    _, items = search_items("", source, limit)

    assert len(items) == count


def test_limit_above_max_is_clamped(sources):
    """``limit`` больше максимума урезается до ``SEARCH_LIMIT_MAX``, а не отдаёт всё."""
    blocks = [f"Заметка {index}\nТекст." for index in range(1, 26)]
    source = write_notes(sources, blocks)

    _, items = search_items("", source, config.SEARCH_LIMIT_MAX * 50)

    assert len(items) == config.SEARCH_LIMIT_MAX
    assert items[-1]["id"] == f"file:notes.md#{config.SEARCH_LIMIT_MAX}"


def test_long_query_is_truncated_not_rejected(sources):
    """Запрос длиннее ``SEARCH_QUERY_MAX`` обрезается: ищутся первые 200 символов."""
    source = write_notes(sources, ["b" * config.SEARCH_QUERY_MAX + "\nТело блока."])

    _, items = search_items("b" * config.SEARCH_QUERY_MAX + "X", source, 5)

    assert len(items) == 1


def test_file_source_missing_file_names_it(sources):
    """Нет файла — ошибка с его путём: чинить надо источник, а не запрос."""
    with pytest.raises(SearchSourceError) as exc:
        search_items("", "file:нет-такого.md", 5)
    assert "нет-такого.md" in str(exc.value)
    assert "не найден" in str(exc.value)


def test_file_source_rejects_absolute_path(sources):
    """Абсолютный путь отклоняется, даже когда файл существует: читается только день."""
    source = write_notes(sources, NOTES)
    absolute = f"file:{(sources / 'notes.md').as_posix()}"

    with pytest.raises(SearchSourceError) as exc:
        search_items("", absolute, 5)

    assert "должен быть относительным" in str(exc.value)
    assert source == "file:notes.md"


@pytest.mark.parametrize("detail", ["../secret.txt", "sub/../../secret.txt"])
def test_file_source_rejects_path_outside_day(sources, detail):
    """``../`` отклоняется, даже когда файл существует: иначе читался бы любой файл."""
    (sources.parent / "secret.txt").write_text("секрет\n\nвторой блок", encoding="utf-8")

    with pytest.raises(SearchSourceError) as exc:
        search_items("", f"file:{detail}", 5)

    assert "за пределы папки дня" in str(exc.value)


def test_source_longer_than_max_is_rejected(sources):
    """Слишком длинная строка источника — ошибка с числом символов, а не обрез."""
    with pytest.raises(SearchSourceError) as exc:
        search_items("", "file:" + "a" * config.SEARCH_SOURCE_MAX, 5)
    assert str(config.SEARCH_SOURCE_MAX) in str(exc.value)


def test_search_items_returns_kind_and_items(sources):
    """Вид источника возвращается рядом с элементами (поле ``source_kind`` результата)."""
    write_notes(sources, NOTES)

    kind, items = search_items("", "file:notes.md", 5)

    assert kind == "file"
    assert len(items) == 3
