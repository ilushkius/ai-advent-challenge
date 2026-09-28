"""Инструмент ``search_local`` сервера поиска (день 20): файлы внутри папки дня.

Проверяются разбиение файла на блоки по пустым строкам, фильтр подстрокой без
учёта регистра, границы ``limit``, нумерация блоков и, главное, две защиты: файл
вне корня и отсутствующий файл — это ошибки инструмента (``ToolError``), а не
чтение произвольного файла машины.
"""
from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.search_server import config, local

#: Заметка-источник: три блока по пустым строкам.
NOTES = (
    "RAG — генерация с опорой на найденные фрагменты\n\n"
    "Чанкинг — нарезка документов на части\n\n"
    "Индексация: RAG требует векторного индекса\n"
)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """Снимок корня источников: ``configure`` внутри теста не течёт дальше."""
    monkeypatch.setattr(local, "_file_root", local._file_root)
    return local


@pytest.fixture
def notes(tmp_path):
    """Файл источника внутри корня дня прогона."""
    path = tmp_path / "notes.md"
    path.write_text(NOTES, encoding="utf-8")
    local.configure(file_root=tmp_path)
    return path


def test_blocks_are_split_and_numbered(notes):
    """Пустой запрос отдаёт все блоки: заголовок — первая строка, номер — по файлу."""
    result = local.search_local("", path="notes.md", limit=10)

    assert result["path"] == "notes.md" and result["count"] == 3
    assert [item["id"] for item in result["items"]] == [
        "file:notes.md#1", "file:notes.md#2", "file:notes.md#3",
    ]
    first = result["items"][0]
    assert first["title"].startswith("RAG — генерация")
    assert first["content"].startswith("RAG — генерация")
    assert first["url"] == ""
    assert first["metadata"] == {"path": "notes.md", "block": "1"}
    assert [item["metadata"]["block"] for item in result["items"]] == ["1", "2", "3"]


def test_filter_is_case_insensitive_and_keeps_file_index(notes):
    """Фильтр без учёта регистра, а номер блока — его место в файле, а не в выдаче."""
    result = local.search_local("rag", path="notes.md", limit=10)

    assert result["count"] == 2
    assert [item["metadata"]["block"] for item in result["items"]] == ["1", "3"]
    assert [item["id"] for item in result["items"]] == [
        "file:notes.md#1", "file:notes.md#3",
    ]


def test_limit_applies_after_filtering(notes):
    """``limit`` отсекает выдачу после фильтра, а не список блоков до него."""
    result = local.search_local("rag", path="notes.md", limit=1)
    assert result["count"] == 1
    assert result["items"][0]["id"] == "file:notes.md#1"


def test_default_path_is_a_file_of_the_day(tmp_path):
    """Путь по умолчанию — ``mcp_server/data/notes.md`` от корня источников."""
    target = tmp_path / "mcp_server" / "data" / "notes.md"
    target.parent.mkdir(parents=True)
    target.write_text("RAG — заметка дня\n", encoding="utf-8")
    local.configure(file_root=tmp_path)

    result = local.search_local("RAG")
    assert result["path"] == "mcp_server/data/notes.md" and result["count"] == 1


def test_absolute_path_inside_root_is_allowed(tmp_path, notes):
    """Абсолютный путь внутри корня читается: он не выходит за папку дня."""
    local.configure(file_root=tmp_path)
    result = local.search_local("Чанкинг", path=str(notes))
    assert result["count"] == 1
    assert result["items"][0]["title"].startswith("Чанкинг")


def test_path_outside_root_is_a_tool_error(tmp_path):
    """Путь за корнем — ``ToolError``: читать чужие файлы машины нельзя."""
    local.configure(file_root=tmp_path / "run")
    (tmp_path / "run").mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("секрет", encoding="utf-8")

    with pytest.raises(ToolError) as exc:
        local.search_local("секрет", path="../outside.md")
    assert "вне папки дня" in str(exc.value)

    with pytest.raises(ToolError) as exc_abs:
        local.search_local("секрет", path=str(outside))
    assert "вне папки дня" in str(exc_abs.value)


def test_missing_file_is_a_tool_error(notes):
    """Отсутствующий файл — отдельная причина: «файл источника не найден»."""
    with pytest.raises(ToolError) as exc:
        local.search_local("RAG", path="нет-такого.md")
    assert "не найден" in str(exc.value)


def test_empty_path_is_a_tool_error():
    """Пустой путь — ошибка инструмента, а не чтение корня."""
    with pytest.raises(ToolError) as exc:
        local.search_local("RAG", path="   ")
    assert "пуст" in str(exc.value)


def test_long_block_content_is_truncated(notes, tmp_path):
    """Длинный блок обрезается до ``CONTENT_MAX``: ответ остаётся читаемым."""
    long_text = "A" * (config.CONTENT_MAX + 500)
    (tmp_path / "long.md").write_text(long_text, encoding="utf-8")
    result = local.search_local("", path="long.md", limit=5)
    assert len(result["items"][0]["content"]) == config.CONTENT_MAX


def test_long_title_is_truncated(tmp_path):
    """Заголовок (первая строка блока) обрезается до ``TITLE_MAX``."""
    (tmp_path / "titles.md").write_text("Б" * (config.TITLE_MAX + 50) + "\n", encoding="utf-8")
    local.configure(file_root=tmp_path)
    result = local.search_local("", path="titles.md", limit=5)
    assert len(result["items"][0]["title"]) == config.TITLE_MAX
