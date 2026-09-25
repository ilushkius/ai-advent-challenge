"""Файлы результатов ``storage_server``: запись, список и чтение (день 20).

Здесь живут инструменты ``save_to_file``, ``list_saved`` (часть «file») и
``load_from_file``. Каталог вывода настраивается ``configure()`` (аргумент
``--output-dir`` сервера), по умолчанию — ``day20/output/``.

Правила имён те же, что у инструмента дня 19: путь и ``..`` запрещены, расширение
ЗАМЕНЯЕТСЯ под запрошенный формат. Поэтому сервер не может выйти за каталог вывода,
даже если модель передала ``../../etc/passwd``; ``load`` проверяет это ещё раз,
разрешая только файлы ВНУТРИ каталога.

Ошибка записи — ``SaveFileError``, ошибка чтения — ``LoadFileError``: инструменты
превращают их в ``ToolError`` с понятным текстом, и вызов возвращает ошибку
данными, а не падением процесса.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mcp_servers.storage_server import config
from mcp_servers.storage_server.schemas import LoadedFile, SavedFile, SavedFileInfo

#: Каталог вывода процесса (переопределяется ``--output-dir``).
_output_dir: Path = config.OUTPUT_DIR


class SaveFileError(RuntimeError):
    """Формат не поддержан, имя файла опасное или текст слишком длинный."""


class LoadFileError(RuntimeError):
    """Имя файла опасное, файл вне каталога вывода или его нет."""


def configure(output_dir: str | Path | None = None) -> None:
    """Задаёт каталог вывода (``--output-dir`` сервера)."""
    global _output_dir
    if output_dir is not None:
        _output_dir = Path(output_dir)


def output_dir() -> Path:
    """Текущий каталог вывода (нужен тестам и отчёту прогона)."""
    return _output_dir


def clamp_limit(limit: int) -> int:
    """Приводит ``limit`` к границам ``LIST_LIMIT_MIN..LIST_LIMIT_MAX``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = config.LIST_LIMIT_DEFAULT
    return max(config.LIST_LIMIT_MIN, min(config.LIST_LIMIT_MAX, value))


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


def _file_info(path: Path, mtime: float) -> SavedFileInfo:
    """Сведения о файле для ``list_saved``: имя, путь, размер, формат, момент."""
    extension = path.suffix.lstrip(".").lower()
    return SavedFileInfo(
        filename=path.name,
        filepath=path.as_posix(),
        size_bytes=path.stat().st_size,
        format=extension if extension in config.SAVE_FORMATS else "",
        saved_at=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds"),
    )


def list_files(limit: int = config.LIST_LIMIT_DEFAULT) -> list[SavedFileInfo]:
    """Список файлов каталога вывода: свежие сверху, не больше ``limit``.

    Учитываются только обычные файлы; отсутствующий каталог — пустой список
    (первый запуск ещё ничего не сохранил, и это не ошибка).
    """
    root = Path(_output_dir)
    if not root.is_dir():
        return []
    found: list[tuple[float, str, Path]] = []
    try:
        for entry in root.iterdir():
            if entry.is_file():
                found.append((entry.stat().st_mtime, entry.name, entry))
    except OSError as exc:
        raise LoadFileError(f"Не удалось прочитать каталог {root}: {exc}") from exc
    found.sort(key=lambda item: (-item[0], item[1]))
    return [_file_info(path, mtime) for mtime, _name, path in found[:clamp_limit(limit)]]


def load(filename: str) -> LoadedFile:
    """Читает сохранённый файл по имени и возвращает его текст.

    Имя чистится теми же правилами, что у ``save_to_file``: путь и ``..``
    запрещены. Разрешены только файлы ВНУТРИ каталога вывода; отсутствие файла —
    ``LoadFileError`` с его именем, а не «тихий» пустой результат.
    """
    name = (filename or "").strip()
    if not name:
        raise LoadFileError("Имя файла пустое")
    if "/" in name or "\\" in name or ".." in name:
        raise LoadFileError("Имя файла не должно содержать путь или «..»")
    root = Path(_output_dir).resolve()
    target = Path(_output_dir) / name
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise LoadFileError(f"Не удалось разобрать путь {name}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise LoadFileError(f"Файл вне каталога вывода: {name}")
    if not resolved.is_file():
        raise LoadFileError(f"Файл не найден: {name}")
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadFileError(f"Не удалось прочитать {name}: {exc}") from exc
    extension = resolved.suffix.lstrip(".").lower()
    return LoadedFile(
        filename=name,
        filepath=resolved.as_posix(),
        chars=len(text),
        format=extension if extension in config.SAVE_FORMATS else "",
        text=text,
    )


def save(content: str, filename: str = "orchestration_result.md",
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
