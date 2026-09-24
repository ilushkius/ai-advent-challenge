"""Инструмент ``save_to_file`` (день 19): запись результата пайплайна на диск.

Каталог вывода настраивается ``configure()`` (аргумент ``--output-dir`` сервера),
по умолчанию — ``day19/output/``. Имя файла чистится: путь и ``..`` запрещены,
поэтому инструмент не может выйти за каталог вывода, даже если модель передала
``../../etc/passwd``.

Формат определяет вид файла: ``txt`` и ``md`` — текст как есть с завершающим
переводом строки, ``json`` — объект с именем, форматом, моментом записи и самим
текстом (``ensure_ascii=False``: сводки на русском читаются глазами).

Ошибка записи — ``SaveFileError`` с текстом для человека: инструмент превращает её
в ``ToolError``, и шаг пайплайна завершается со статусом ``failed``, а не падением
процесса.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mcp_server import config
from mcp_server.schemas import SavedFile

#: Каталог вывода процесса (переопределяется ``--output-dir``).
_output_dir: Path = config.OUTPUT_DIR


class SaveFileError(RuntimeError):
    """Формат не поддержан, имя файла опасное или текст слишком длинный."""


def configure(output_dir: str | Path | None = None) -> None:
    """Задаёт каталог вывода (``--output-dir`` сервера)."""
    global _output_dir
    if output_dir is not None:
        _output_dir = Path(output_dir)


def output_dir() -> Path:
    """Текущий каталог вывода (нужен тестам и отчёту прогона)."""
    return _output_dir


def normalize_format(fmt: str) -> str:
    """Формат файла в нижнем регистре без точки; чужой формат — ошибка."""
    value = (fmt or "").strip().lower().lstrip(".")
    if value not in config.SAVE_FORMATS:
        raise SaveFileError(
            f"Формат «{fmt}» не поддержан. Допустимы: " + ", ".join(config.SAVE_FORMATS)
        )
    return value


def sanitize_filename(name: str, fmt: str) -> str:
    """Имя файла: без пути и ``..``, с расширением запрошенного формата.

    Расширение ЗАМЕНЯЕТСЯ, а не добавляется: «отчёт.txt» при формате ``md``
    становится «отчёт.md» — иначе формат в аргументе и формат на диске разошлись
    бы, и файл было бы нечем открыть.
    """
    value = (name or "").strip()
    if not value:
        raise SaveFileError("Имя файла пустое")
    if "/" in value or "\\" in value or ".." in value:
        raise SaveFileError("Имя файла не должно содержать путь или «..»")
    stem = value.rsplit(".", 1)[0] if "." in value else value
    stem = stem.strip()
    if not stem:
        raise SaveFileError("Имя файла пустое")
    return f"{stem[:config.FILE_NAME_MAX]}.{fmt}"


def render_content(content: str, fmt: str, saved_at: str, filename: str = "") -> str:
    """Содержимое файла по формату: текст с переводом строки или JSON-объект."""
    if fmt == "json":
        return json.dumps(
            {"filename": filename, "format": "json", "saved_at": saved_at,
             "content": content},
            ensure_ascii=False, indent=2,
        )
    return content if content.endswith("\n") else content + "\n"


def save(content: str, filename: str = "pipeline_result.md",
         format: str = config.SAVE_FORMAT_DEFAULT) -> SavedFile:
    """Записывает текст в файл каталога вывода и возвращает сведения о нём."""
    fmt = normalize_format(format)
    text = content if isinstance(content, str) else str(content)
    if len(text) > config.FILE_CONTENT_MAX:
        raise SaveFileError(
            f"Текст длиннее {config.FILE_CONTENT_MAX} символов: получено {len(text)}"
        )
    name = sanitize_filename(filename, fmt)
    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    target = Path(_output_dir) / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = render_content(text, fmt, saved_at, name)
        target.write_text(data, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise SaveFileError(f"Не удалось записать файл {name}: {exc}") from exc
    return SavedFile(
        filename=name,
        filepath=target.as_posix(),
        size_bytes=len(data.encode("utf-8")),
        format=fmt,
        saved_at=saved_at,
    )
