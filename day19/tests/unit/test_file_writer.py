"""Инструмент ``save_to_file`` (день 19): имя, формат и запись на диск.

Проверяются правила, из-за которых файл результата пайплайна остаётся читаемым:
расширение ЗАМЕНЯЕТСЯ под запрошенный формат, путь и ``..`` в имени запрещены,
``json`` — объект с самим текстом, а не строка, ``saved_at`` — момент записи в UTC.
Размер файла сверяется с диском: отчёт прогона печатает именно его.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_server import config, file_writer
from mcp_server.file_writer import SaveFileError


@pytest.fixture
def writer(tmp_path):
    """Изолированный каталог вывода: инструмент пишет только в него."""
    original = file_writer.output_dir()
    file_writer.configure(tmp_path)
    yield file_writer
    file_writer.configure(original)


def _read(result):
    """Содержимое сохранённого файла текстом (для сверки с ожидаемым)."""
    return Path(result["filepath"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("format", ["txt", "md"])
@pytest.mark.parametrize("content", ["текст сводки", "текст сводки\n"])
def test_text_formats_end_with_single_newline(writer, format, content):
    """``txt`` и ``md`` — текст как есть ровно с одним завершающим переводом строки."""
    result = writer.save(content, "сводка", format)
    assert _read(result) == "текст сводки\n"
    assert not _read(result).endswith("\n\n")


def test_json_is_object_with_content(writer):
    """``json`` — объект из четырёх полей, а не строка с экранированным текстом."""
    result = writer.save("сводка про RAG", "сводка.md", "json")
    payload = json.loads(_read(result))
    assert set(payload) == {"filename", "format", "saved_at", "content"}
    assert payload["format"] == "json"
    assert payload["filename"] == "сводка.json"
    assert payload["content"] == "сводка про RAG"
    assert payload["saved_at"] == result["saved_at"]


def test_json_keeps_cyrillic_readable(writer):
    """JSON пишется с ``ensure_ascii=False``: русский текст видно в файле."""
    writer.save("сводка", "сводка", "json")
    raw = Path(writer.output_dir() / "сводка.json").read_text(encoding="utf-8")
    assert "сводка" in raw
    assert "\\u" not in raw


@pytest.mark.parametrize("name,format,expected", [
    ("отчёт.txt", "md", "отчёт.md"),
    ("отчёт", "md", "отчёт.md"),
    ("report.MD", "json", "report.json"),
    ("report.tar.gz", "txt", "report.tar.txt"),
])
def test_extension_is_replaced_by_requested_format(writer, name, format, expected):
    """Расширение заменяется под формат: иначе формат на диске разошёлся бы с аргументом."""
    assert writer.sanitize_filename(name, format) == expected


def test_long_filename_is_cut_to_limit(writer):
    """Длинное имя обрезается до ``FILE_NAME_MAX`` перед добавлением расширения."""
    name = writer.sanitize_filename("я" * 200, "md")
    assert name == "я" * config.FILE_NAME_MAX + ".md"


@pytest.mark.parametrize("name", ["папка/файл.md", "папка\\файл.md", "../секрет.md", "a..b.md"])
def test_path_in_filename_is_rejected(writer, name):
    """Путь и «..» в имени запрещены: инструмент не выходит за каталог вывода."""
    with pytest.raises(SaveFileError) as exc:
        writer.sanitize_filename(name, "md")
    assert "путь" in str(exc.value)


@pytest.mark.parametrize("name", ["", "   ", ".md"])
def test_empty_filename_is_rejected(writer, name):
    """Пустое имя (в том числе без основы) — ошибка, а не файл «.md»."""
    with pytest.raises(SaveFileError):
        writer.sanitize_filename(name, "md")


@pytest.mark.parametrize("format,expected", [(".JSON", "json"), (" Txt ", "txt"), ("MD", "md")])
def test_format_normalization_tolerates_dot_and_case(writer, format, expected):
    """Формат читается с точкой и в любом регистре."""
    assert file_writer.normalize_format(format) == expected


@pytest.mark.parametrize("format", ["pdf", "", "jsonl"])
def test_unknown_format_lists_allowed_values(writer, format):
    """Чужой формат отклоняется, а текст ошибки перечисляет допустимые."""
    with pytest.raises(SaveFileError) as exc:
        file_writer.normalize_format(format)
    for allowed in config.SAVE_FORMATS:
        assert allowed in str(exc.value)


def test_save_creates_missing_output_directory(tmp_path):
    """Каталог вывода создаётся вместе с родителями — иначе шаг падал бы на первом запуске."""
    target = tmp_path / "вложенный" / "output"
    original = file_writer.output_dir()
    file_writer.configure(target)
    try:
        result = file_writer.save("сводка", "итог", "md")
        assert target.is_dir()
        assert Path(result["filepath"]).is_file()
    finally:
        file_writer.configure(original)


def test_configure_without_argument_keeps_directory(tmp_path):
    """``configure(None)`` не сбрасывает каталог: сервер вызывает его без флага ``--output-dir``."""
    original = file_writer.output_dir()
    file_writer.configure(tmp_path)
    try:
        file_writer.configure(None)
        assert file_writer.output_dir() == tmp_path
    finally:
        file_writer.configure(original)


@pytest.mark.parametrize("format", ["md", "json"])
def test_size_bytes_matches_file_on_disk(writer, format):
    """``size_bytes`` — реальный размер записанного файла, а ``filepath`` ведёт внутрь каталога."""
    content = "сводка про RAG и эмбеддинги"
    result = writer.save(content, "итог", format)
    path = Path(result["filepath"])
    assert path.is_file()
    assert path.parent == Path(writer.output_dir())
    assert result["size_bytes"] == path.stat().st_size == len(path.read_bytes())


def test_saved_at_is_iso_utc(writer):
    """``saved_at`` — момент записи в ISO-8601 с нулевым смещением."""
    result = writer.save("сводка", "итог", "md")
    moment = datetime.fromisoformat(result["saved_at"])
    assert moment.utcoffset() == timezone.utc.utcoffset(None)
    assert moment.tzinfo is not None


@pytest.mark.parametrize("length,raises", [
    (config.FILE_CONTENT_MAX, False),
    (config.FILE_CONTENT_MAX + 1, True),
])
def test_content_length_boundary(writer, length, raises):
    """Текст на границе ``FILE_CONTENT_MAX`` принимается, на символ длиннее — отклоняется."""
    if raises:
        with pytest.raises(SaveFileError) as exc:
            writer.save("я" * length, "итог", "md")
        assert str(config.FILE_CONTENT_MAX) in str(exc.value)
    else:
        assert writer.save("я" * length, "итог", "md")["size_bytes"] > length


def test_same_filename_overwrites_previous_save(writer):
    """Повторная запись под тем же именем перезаписывает файл последним текстом."""
    first = writer.save("первый прогон", "итог", "md")
    second = writer.save("второй прогон", "итог", "md")
    assert first["filepath"] == second["filepath"]
    assert _read(second) == "второй прогон\n"
