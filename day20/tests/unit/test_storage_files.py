"""Файлы ``storage_server`` (день 20): имя, формат, запись, список и чтение.

Проверяются правила, из-за которых файл результата остаётся читаемым: расширение
ЗАМЕНЯЕТСЯ под запрошенный формат, путь и ``..`` в имени запрещены, ``json`` —
объект с самим текстом, ``saved_at`` — момент записи в UTC. Отдельно проверяются
новые относительно дня 19 вещи: ``list_files`` (свежие сверху, границы ``limit``,
отсутствующий каталог) и ``load`` (чтение ВНУТРИ каталога вывода).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_servers.storage_server import config, files
from mcp_servers.storage_server.files import LoadFileError, SaveFileError


@pytest.fixture
def storage(tmp_path):
    """Изолированный каталог вывода: инструмент пишет только в него."""
    original = files.output_dir()
    files.configure(tmp_path)
    yield files
    files.configure(original)


def _read(result):
    """Содержимое сохранённого файла текстом (для сверки с ожидаемым)."""
    return Path(result["filepath"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("format", ["txt", "md"])
@pytest.mark.parametrize("content", ["текст сводки", "текст сводки\n"])
def test_text_formats_end_with_single_newline(storage, format, content):
    """``txt`` и ``md`` — текст как есть ровно с одним завершающим переводом строки."""
    result = storage.save(content, "сводка", format)
    assert _read(result) == "текст сводки\n"


def test_json_is_object_with_content(storage):
    """``json`` — объект из четырёх полей, а не строка с экранированным текстом."""
    result = storage.save("сводка про RAG", "сводка.md", "json")
    payload = json.loads(_read(result))
    assert set(payload) == {"filename", "format", "saved_at", "content"}
    assert payload["format"] == "json"
    assert payload["filename"] == "сводка.json"
    assert payload["content"] == "сводка про RAG"
    assert payload["saved_at"] == result["saved_at"]


def test_json_keeps_cyrillic_readable(storage):
    """JSON пишется с ``ensure_ascii=False``: русский текст видно в файле."""
    storage.save("сводка", "сводка", "json")
    raw = Path(storage.output_dir() / "сводка.json").read_text(encoding="utf-8")
    assert "сводка" in raw
    assert "\\u" not in raw


@pytest.mark.parametrize("name,format,expected", [
    ("отчёт.txt", "md", "отчёт.md"),
    ("отчёт", "md", "отчёт.md"),
    ("report.MD", "json", "report.json"),
    ("report.tar.gz", "txt", "report.tar.txt"),
])
def test_extension_is_replaced_by_requested_format(storage, name, format, expected):
    """Расширение заменяется под формат: иначе формат на диске разошёлся бы с аргументом."""
    assert storage.sanitize_filename(name, format) == expected


def test_long_filename_is_cut_to_limit(storage):
    """Длинное имя обрезается до ``FILE_NAME_MAX`` перед добавлением расширения."""
    name = storage.sanitize_filename("я" * 200, "md")
    assert name == "я" * config.FILE_NAME_MAX + ".md"


@pytest.mark.parametrize("name", ["папка/файл.md", "папка\\файл.md", "../секрет.md", "a..b.md"])
def test_path_in_filename_is_rejected(storage, name):
    """Путь и «..» в имени запрещены: инструмент не выходит за каталог вывода."""
    with pytest.raises(SaveFileError) as exc:
        storage.sanitize_filename(name, "md")
    assert "путь" in str(exc.value)


@pytest.mark.parametrize("name", ["", "   ", ".md"])
def test_empty_filename_is_rejected(storage, name):
    """Пустое имя (в том числе без основы) — ошибка, а не файл «.md»."""
    with pytest.raises(SaveFileError):
        storage.sanitize_filename(name, "md")


@pytest.mark.parametrize("format,expected", [(".JSON", "json"), (" Txt ", "txt"), ("MD", "md")])
def test_format_normalization_tolerates_dot_and_case(storage, format, expected):
    """Формат читается с точкой и в любом регистре."""
    assert storage.normalize_format(format) == expected


@pytest.mark.parametrize("format", ["pdf", "", "jsonl"])
def test_unknown_format_lists_allowed_values(storage, format):
    """Чужой формат отклоняется, а текст ошибки перечисляет допустимые."""
    with pytest.raises(SaveFileError) as exc:
        storage.normalize_format(format)
    for allowed in config.SAVE_FORMATS:
        assert allowed in str(exc.value)


def test_save_creates_missing_output_directory(tmp_path):
    """Каталог вывода создаётся вместе с родителями — иначе шаг падал бы на первом запуске."""
    target = tmp_path / "вложенный" / "output"
    original = files.output_dir()
    files.configure(target)
    try:
        result = files.save("сводка", "итог", "md")
        assert target.is_dir()
        assert Path(result["filepath"]).is_file()
    finally:
        files.configure(original)


def test_configure_without_argument_keeps_directory(tmp_path):
    """``configure(None)`` не сбрасывает каталог: сервер вызывает его без флага ``--output-dir``."""
    original = files.output_dir()
    files.configure(tmp_path)
    try:
        files.configure(None)
        assert files.output_dir() == tmp_path
    finally:
        files.configure(original)


@pytest.mark.parametrize("format", ["md", "json"])
def test_size_bytes_matches_file_on_disk(storage, format):
    """``size_bytes`` — реальный размер записанного файла, а ``filepath`` ведёт внутрь каталога."""
    content = "сводка про RAG и эмбеддинги"
    result = storage.save(content, "итог", format)
    path = Path(result["filepath"])
    assert path.is_file()
    assert path.parent == Path(storage.output_dir())
    assert result["size_bytes"] == path.stat().st_size == len(path.read_bytes())


def test_saved_at_is_iso_utc(storage):
    """``saved_at`` — момент записи в ISO-8601 с нулевым смещением."""
    result = storage.save("сводка", "итог", "md")
    moment = datetime.fromisoformat(result["saved_at"])
    assert moment.utcoffset() == timezone.utc.utcoffset(None)
    assert moment.tzinfo is not None


@pytest.mark.parametrize("length,raises", [
    (config.FILE_CONTENT_MAX, False),
    (config.FILE_CONTENT_MAX + 1, True),
])
def test_content_length_boundary(storage, length, raises):
    """Текст на границе ``FILE_CONTENT_MAX`` принимается, на символ длиннее — отклоняется."""
    if raises:
        with pytest.raises(SaveFileError) as exc:
            storage.save("я" * length, "итог", "md")
        assert str(config.FILE_CONTENT_MAX) in str(exc.value)
    else:
        assert storage.save("я" * length, "итог", "md")["size_bytes"] > length


def test_same_filename_overwrites_previous_save(storage):
    """Повторная запись под тем же именем перезаписывает файл последним текстом."""
    first = storage.save("первый прогон", "итог", "md")
    second = storage.save("второй прогон", "итог", "md")
    assert first["filepath"] == second["filepath"]
    assert _read(second) == "второй прогон\n"


# ---------- список файлов каталога вывода ----------
def test_list_files_missing_directory_is_empty(tmp_path):
    """Отсутствующий каталог — пустой список, а не ошибка: сохранять ещё нечего."""
    original = files.output_dir()
    files.configure(tmp_path / "нет-такого")
    try:
        assert files.list_files() == []
    finally:
        files.configure(original)


def test_list_files_sorts_newest_first(storage, tmp_path):
    """Файлы идут свежими вверх: отчёт печатает именно первый из списка."""
    older = tmp_path / "старый.md"
    newer = tmp_path / "новый.md"
    older.write_text("первый", encoding="utf-8")
    newer.write_text("второй", encoding="utf-8")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert [item["filename"] for item in storage.list_files()] == ["новый.md", "старый.md"]


@pytest.mark.parametrize("limit,expected", [
    (0, config.LIST_LIMIT_MIN),
    (1, 1),
    (999, 3),
])
def test_list_files_clamps_limit(storage, limit, expected):
    """``limit`` подтягивается к границам ``LIST_LIMIT_MIN..LIST_LIMIT_MAX``."""
    for index in range(3):
        storage.save(f"текст {index}", f"файл{index}", "md")
    assert len(storage.list_files(limit)) == expected


def test_list_files_reports_format_and_skips_directories(storage, tmp_path):
    """Список описывает обычные файлы: имя, путь, размер, формат и момент записи."""
    storage.save("текст", "итог", "md")
    (tmp_path / "заметка.log").write_text("лог", encoding="utf-8")
    (tmp_path / "папка").mkdir()
    items = {item["filename"]: item for item in storage.list_files()}
    assert set(items) == {"итог.md", "заметка.log"}
    assert items["итог.md"]["format"] == "md"
    assert items["заметка.log"]["format"] == ""
    assert items["итог.md"]["size_bytes"] == (tmp_path / "итог.md").stat().st_size
    assert items["итог.md"]["filepath"].endswith("итог.md")
    assert datetime.fromisoformat(items["итог.md"]["saved_at"]).tzinfo is not None


# ---------- чтение сохранённого файла ----------
def test_load_returns_saved_text(storage):
    """Сохранённый файл читается тем же текстом: ``chars`` считает символы."""
    storage.save("сводка про RAG", "итог", "md")
    loaded = storage.load("итог.md")
    assert loaded["filename"] == "итог.md"
    assert loaded["format"] == "md"
    assert loaded["text"] == "сводка про RAG\n"
    assert loaded["chars"] == len("сводка про RAG\n")


def test_load_reads_json_file_as_is(storage):
    """``json``-файл читается как есть, а ``format`` берётся из расширения."""
    storage.save("сводка", "итог", "json")
    loaded = storage.load("итог.json")
    assert loaded["format"] == "json"
    assert json.loads(loaded["text"])["content"] == "сводка"


@pytest.mark.parametrize("name", ["../секрет.md", "папка/файл.md", "папка\\файл.md", "", "  "])
def test_load_rejects_path_in_name(storage, name):
    """Путь, «..» и пустое имя запрещены: читать можно только каталог вывода."""
    with pytest.raises(LoadFileError):
        storage.load(name)


def test_load_reports_missing_file(storage):
    """Отсутствующего файла нет — ошибка с его именем, а не пустой текст."""
    with pytest.raises(LoadFileError) as exc:
        storage.load("нет-такого.md")
    assert "нет-такого.md" in str(exc.value)
