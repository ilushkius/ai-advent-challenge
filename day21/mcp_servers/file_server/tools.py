"""Тела шести инструментов MCP-сервера файлов проекта (день 34).

Инструменты работают с ФАЙЛАМИ папки дня: перечислить каталог (``list_files``),
найти образец по файлам (``search_in_files``), прочитать файл (``read_file``),
создать или дописать (``write_file``), заменить фрагмент (``apply_patch``) и
получить diff относительно ``HEAD`` (``get_file_diff``). Так ассистент файлов
исполняет план, который сам же предложил: прочитал → нашёл → изменил → показал diff.

Почему имена инструментов не совпадают с флотом дня 20. У ``dev_server`` уже есть
``list_files`` и ``get_git_diff``, но они отвечают про РЕПОЗИТОРИЙ: пути от корня
``ai-challenge/``, diff всего рабочего дерева. Здесь область — папка дня, а к
чтению добавлены ЗАПИСЬ и замена. Сервер вне флота (``mcp_servers.json`` не
меняется), поэтому одинаковые имена разных процессов никого не путают: служба
подключается своим клиентом именно к этому серверу.

Граница рабочей области — ``configure(file_root)`` (аргумент ``--file-root``
сервера). ``_resolve`` разворачивает путь через ``Path.resolve()`` и проверяет
принадлежность корню, поэтому ``../../etc/passwd`` и ``C:\\Windows\\win.ini`` не
читаются, даже если модель попросит; путь аргументов относителен корню.

Ошибки инструмента — ``ToolError`` с русским текстом: ошибка приходит модели
данными (``is_error``), и по этому тексту она может исправить следующий шаг
(например, перечитать файл, если ``old_text`` не найден). Каждый вызов
логируется на уровне INFO: полный путь, шаблон поиска, время и размер результата.
Содержимое файлов и текст правок в лог НЕ попадают.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from shared.logging_utils import get_logger

from mcp_servers.file_server import config, diffing
from mcp_servers.file_server.schemas import FileContent, PatchResult, WriteResult

logger = get_logger(__name__)

__all__ = ["apply_patch", "configure", "file_root", "get_file_diff", "list_files",
           "read_file", "search_in_files", "write_file"]

#: Корень рабочей области инструментов: по умолчанию папка дня, меняется
#: аргументом ``--file-root`` (тесты работают на временном каталоге).
_file_root: Path = config.DAY_ROOT


def configure(file_root: str | Path | None = None) -> None:
    """Задаёт корень рабочей области инструментов (аргумент ``--file-root``)."""
    global _file_root
    _file_root = Path(file_root).resolve() if file_root is not None else config.DAY_ROOT
    logger.info("file_server: корень рабочей области — %s", _file_root)


def file_root() -> Path:
    """Текущий корень рабочей области (нужен тестам и отчёту прогона)."""
    return _file_root


# ---------- разрешение путей ----------
def _rel(path: Path) -> str:
    """Путь для ответа инструмента: POSIX-строка относительно корня рабочей области."""
    try:
        return path.relative_to(_file_root).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve(path: Any) -> Path:
    """Путь внутри корня рабочей области; выход за корень — ``ToolError``.

    ``Path.resolve()`` разворачивает и ``..``, и абсолютный путь, поэтому проверка
    принадлежности корню ловит обе попытки выйти наружу. Пустой аргумент отвергается
    отдельно: пустая строка разрешилась бы в сам корень, и инструмент молча
    ответил бы не про тот файл, который просила модель.
    """
    raw = str(path or "").strip()
    if not raw:
        raise ToolError("Пустой путь: укажите путь относительно корня проекта")
    target = Path(raw).expanduser()
    resolved = (target if target.is_absolute() else _file_root / target).resolve()
    if resolved != _file_root and _file_root not in resolved.parents:
        raise ToolError(f"Путь вне проекта: {path}")
    return resolved


def _existing_file(path: Any) -> Path:
    """Разрешённый путь к СУЩЕСТВУЮЩЕМУ файлу; каталог или отсутствие — ``ToolError``."""
    target = _resolve(path)
    if not target.is_file():
        raise ToolError(f"Файл не найден: {path}")
    return target


def _existing_dir(directory: Any) -> Path:
    """Разрешённый путь к СУЩЕСТВУЮЩЕМУ каталогу; иначе ``ToolError``."""
    target = _resolve(directory)
    if not target.is_dir():
        raise ToolError(f"Каталог не найден: {directory}")
    return target


def _skipped(path: Path) -> bool:
    """Служебный ли путь: любой его каталог входит в ``config.SKIP_DIRS``."""
    try:
        parts = path.relative_to(_file_root).parts[:-1]
    except ValueError:
        return True
    return any(part in config.SKIP_DIRS for part in parts)


def _iso(stamp: float) -> str:
    """Метка времени файла в ISO-8601 UTC (как ``as_utc`` у строк хранилища)."""
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def _seconds(started: float) -> float:
    """Сколько занял вызов, секунды (для строки лога)."""
    return round(time.perf_counter() - started, 3)


# ---------- чтение и поиск ----------
def read_file(path: str, max_bytes: int = config.DEFAULT_MAX_BYTES) -> FileContent:
    """Возвращает содержимое файла проекта и его размеры.

    Параметры: ``path`` — путь от корня проекта (``"backend/api/main.py"``);
    ``max_bytes`` — сколько байт вернуть, зажимается в ``1…config.MAX_BYTES``
    (``config.DEFAULT_MAX_BYTES`` по умолчанию).

    Возвращает словарь: ``path``, ``size_bytes`` (размер файла ЦЕЛИКОМ), ``chars``
    (сколько символов вернулось), ``lines`` (строк в возвращённом тексте),
    ``truncated`` (файл длиннее лимита), ``extension``, ``modified_at`` (ISO-8601
    UTC) и ``content``. Байты читаются как UTF-8 с заменой нечитаемых символов:
    файл с чужой кодировкой читается, а не роняет вызов.

    Пример: ``read_file(path="docs/usage.md", max_bytes=2000)`` → ``{"path":
    "docs/usage.md", "size_bytes": 48120, "chars": 2000, "lines": 42,
    "truncated": true, …}``.

    Ошибка: файла нет или путь вне проекта — ``ToolError``.
    """
    started = time.perf_counter()
    target = _existing_file(path)
    limit = max(1, min(int(max_bytes or 0) or config.DEFAULT_MAX_BYTES, config.MAX_BYTES))
    data = target.read_bytes()
    text = data[:limit].decode(config.ENCODING, errors="replace")
    stat = target.stat()
    logger.info("read_file: %s (%.1f КБ, %d символов, %.3f с)",
                _rel(target), len(data) / 1024, len(text), _seconds(started))
    return FileContent(
        path=_rel(target),
        size_bytes=len(data),
        chars=len(text),
        lines=len(text.splitlines()),
        truncated=len(data) > limit,
        extension=target.suffix,
        modified_at=_iso(stat.st_mtime),
        content=text,
    )


def search_in_files(pattern: str, directory: str, file_glob: str = "*.py") -> list[dict]:
    """Ищет регулярное выражение по файлам каталога проекта (рекурсивно).

    Параметры: ``pattern`` — регулярное выражение Python (многострочный режим);
    ``directory`` — путь от корня проекта (``"."`` — вся папка дня);
    ``file_glob`` — маска имён файлов (``"*.py"`` по умолчанию).

    Возвращает список совпадений, отсортированный по пути и номеру строки; на
    каждое совпадение: ``path``, ``line_number``, ``match`` (найденный текст),
    ``line`` (строка целиком) и ``context_before``/``context_after`` — по
    ``config.CONTEXT_LINES`` строк вокруг. Файлы обходятся по возрастанию пути,
    служебные каталоги ``config.SKIP_DIRS`` пропускаются, просматривается не
    больше ``config.MAX_SEARCH_FILES`` файлов, а возвращается не больше
    ``config.MAX_SEARCH_MATCHES`` совпадений: длины этого списка достаточно, чтобы
    найти все места вызова компонента, а не выгрузить весь проект в контекст
    модели (у списка нет поля ``truncated``, предел зафиксирован здесь).

    Пример: ``search_in_files("IndexService", ".")`` → ``[{"path":
    "backend/services/index_service.py", "line_number": 42, "match": "IndexService",
    "line": "class IndexService:", "context_before": [...], "context_after": [...]}]``.

    Ошибка: каталога нет или путь вне проекта — ``ToolError``; негодное регулярное
    выражение — тоже ``ToolError`` с текстом от ``re``.
    """
    started = time.perf_counter()
    base = _existing_dir(directory)
    try:
        regex = re.compile(str(pattern or ""), re.MULTILINE)
    except re.error as exc:
        raise ToolError(f"Некорректное регулярное выражение: {exc}") from exc
    files = sorted((item for item in base.rglob(str(file_glob or "*"))
                    if item.is_file() and not _skipped(item)),
                   key=lambda item: item.as_posix())
    scanned = files[:config.MAX_SEARCH_FILES]
    matches: list[dict] = []
    for item in scanned:
        text = item.read_text(encoding=config.ENCODING, errors="replace")
        lines = text.splitlines()
        for number, line in enumerate(lines):
            found = regex.search(line)
            if found is None:
                continue
            matches.append({
                "path": _rel(item),
                "line_number": number + 1,
                "match": found.group(0),
                "line": line,
                "context_before": lines[max(0, number - config.CONTEXT_LINES):number],
                "context_after": lines[number + 1:number + 1 + config.CONTEXT_LINES],
            })
            if len(matches) >= config.MAX_SEARCH_MATCHES:
                logger.info("search_in_files: %r — предел совпадений (%d), файлов %d, %.3f с",
                            pattern, config.MAX_SEARCH_MATCHES, len(scanned),
                            _seconds(started))
                return matches
    logger.info("search_in_files: %r — файлов %d, совпадений %d, %.3f с",
                pattern, len(scanned), len(matches), _seconds(started))
    return matches


def list_files(directory: str, extension: str = "") -> list[str]:
    """Перечисляет имена файлов одного каталога проекта (нерекурсивно).

    Параметры: ``directory`` — путь от корня проекта (``"."`` — корень папки дня);
    ``extension`` — фильтр по расширению, ведущая точка не нужна (``"py"`` и
    ``".py"`` равнозначны), пустая строка — все файлы.

    Возвращает имена (НЕ полные пути) по возрастанию, не больше ``config.MAX_FILES``:
    дальше в каталоге уже не список файлов, а выгрузка, и читать её модели незачем.

    Пример: ``list_files("backend/api", "py")`` → ``["__init__.py", "agents.py", …]``.

    Ошибка: каталога нет или путь вне проекта — ``ToolError``.
    """
    started = time.perf_counter()
    base = _existing_dir(directory)
    suffix = str(extension or "").strip().lstrip(".").lower()
    names = sorted(
        item.name for item in base.iterdir()
        if item.is_file() and (not suffix or item.suffix.lstrip(".").lower() == suffix)
    )[:config.MAX_FILES]
    logger.info("list_files: %s (фильтр %r) — имён %d, %.3f с",
                _rel(base), suffix, len(names), _seconds(started))
    return names


# ---------- запись и правка ----------
def write_file(path: str, content: str, mode: str = "overwrite") -> WriteResult:
    """Создаёт или дописывает файл проекта, создавая недостающие каталоги.

    Параметры: ``path`` — путь от корня проекта; ``content`` — текст целиком (не
    больше ``config.MAX_WRITE_CHARS`` символов); ``mode`` — ``"overwrite"``
    (перезаписать) или ``"append"`` (дописать в конец).

    Каталоги создаются (``mkdir(parents=True, exist_ok=True)``): новый ADR в
    ``docs/adr/`` — обычный сценарий, и отдельный шаг «создай папку» модель бы
    придумывала на пустом месте. В режиме ``append`` перед текстом добавляется
    перевод строки, если файл не заканчивается на ``\\n``: иначе дописанный раздел
    склеился бы с последней строкой.

    Возвращает словарь: ``path``, ``mode``, ``created`` (файла до записи не было),
    ``size_bytes``, ``chars``, ``lines`` (файла ПОСЛЕ записи) и ``written_at``.

    Пример: ``write_file("docs/adr/0001.md", "# ADR\\n…", "overwrite")`` →
    ``{"path": "docs/adr/0001.md", "mode": "overwrite", "created": true, …}``.

    Ошибка: неизвестный ``mode`` или слишком длинное содержимое — ``ToolError``;
    путь вне проекта — тоже ``ToolError``.
    """
    started = time.perf_counter()
    if mode not in config.MODES:
        raise ToolError(f"Неизвестный режим записи {mode!r}: доступны "
                        f"{', '.join(config.MODES)}")
    text = str(content or "")
    if len(text) > config.MAX_WRITE_CHARS:
        raise ToolError(f"Слишком длинное содержимое: {len(text)} символов при пределе "
                        f"{config.MAX_WRITE_CHARS}")
    target = _resolve(path)
    if target.is_dir():
        raise ToolError(f"Это каталог, а не файл: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    append = mode == "append"
    created = not target.exists()
    current = (target.read_text(encoding=config.ENCODING, errors="replace")
               if append and not created else "")
    payload = f"\n{text}" if append and current and not current.endswith("\n") else text
    with target.open("a" if append else "w", encoding=config.ENCODING,
                     newline="\n") as handle:
        handle.write(payload)
    full = current + payload
    stat = target.stat()
    logger.info("write_file: %s (режим %s, создан: %s, %d символов, %.3f с)",
                _rel(target), mode, created, len(full), _seconds(started))
    return WriteResult(
        path=_rel(target),
        mode=mode,
        created=created,
        size_bytes=stat.st_size,
        chars=len(full),
        lines=len(full.splitlines()),
        written_at=_iso(stat.st_mtime),
    )


def apply_patch(path: str, old_text: str, new_text: str) -> PatchResult:
    """Заменяет ПЕРВОЕ вхождение фрагмента в файле проекта.

    Параметры: ``path`` — путь от корня проекта; ``old_text`` — фрагмент, который
    надо найти (непустой); ``new_text`` — чем заменить (пустая строка — удалить
    фрагмент).

    Заменяется ровно первое вхождение, а ``occurrences`` показывает, сколько их
    нашлось всего: если вхождений больше одного, модель видит неоднозначность и
    может уточнить якорь — молчаливая замена всех вхождений испортила бы файл там,
    где это не имелось в виду.

    Возвращает словарь: ``path``, ``replaced`` (всегда 1), ``occurrences``,
    ``size_bytes``, ``chars``, ``lines`` (файла после правки) и ``patched_at``.

    Пример: ``apply_patch("docs/usage.md", "## 16. Частые ошибки", "## 17. …")`` →
    ``{"path": "docs/usage.md", "replaced": 1, "occurrences": 1, …}``.

    Ошибка: файла нет, ``old_text`` пуст или фрагмент не найден — ``ToolError``;
    текст «не найден» прямо просит перечитать файл и повторить, потому что якорь
    надо брать дословно из прочитанного содержимого.
    """
    started = time.perf_counter()
    target = _existing_file(path)
    anchor = str(old_text or "")
    if not anchor:
        raise ToolError(f"Пустой old_text: нечего заменять в файле {_rel(target)}")
    current = target.read_text(encoding=config.ENCODING, errors="replace")
    occurrences = current.count(anchor)
    if not occurrences:
        raise ToolError(f"Текст для замены не найден в файле {_rel(target)}: "
                        "прочитайте файл и повторите")
    patched = current.replace(anchor, str(new_text or ""), 1)
    target.write_text(patched, encoding=config.ENCODING, newline="\n")
    stat = target.stat()
    logger.info("apply_patch: %s (заменено 1 из %d вхождений, %d символов, %.3f с)",
                _rel(target), occurrences, len(patched), _seconds(started))
    return PatchResult(
        path=_rel(target),
        replaced=1,
        occurrences=occurrences,
        size_bytes=stat.st_size,
        chars=len(patched),
        lines=len(patched.splitlines()),
        patched_at=_iso(stat.st_mtime),
    )


# ---------- diff ----------
def get_file_diff(path: str) -> str:
    """Возвращает unified diff файла относительно ``HEAD``.

    Параметры: ``path`` — путь от корня проекта; файл обязан существовать.

    Три ветки ответа:

    1. файл лежит вне репозитория git (например, рабочая область ``--file-root``
       во временном каталоге) → строка ``config.NOT_TRACKED_NOTE``: исключения нет,
       потому что это не ошибка вызова, а честный факт о файле;
    2. файл отслеживается git (``git ls-files --error-unmatch``) → вывод
       ``git diff --no-color HEAD -- <путь>``; пустой вывод (файл не менялся) →
       ``config.NO_CHANGES``;
    3. файл не отслеживается, но существует (только что создан) → diff
       синтезируется в Python: ``git diff HEAD`` неотслеживаемые файлы не
       показывает, и без этой ветки новый ADR остался бы без diff-а в отчёте.

    Пример: ``get_file_diff("docs/usage.md")`` → ``"diff --git a/docs/usage.md
    b/docs/usage.md\\n--- a/docs/usage.md\\n+++ b/docs/usage.md\\n@@ …"``.

    Ошибка: файла нет — ``ToolError``; git не найден в PATH или истёк таймаут —
    тоже ``ToolError``.
    """
    started = time.perf_counter()
    target = _existing_file(path)
    resolved = target.resolve()
    if resolved != config.REPO_ROOT and config.REPO_ROOT not in resolved.parents:
        logger.info("get_file_diff: %s — вне репозитория git, %.3f с",
                    _rel(target), _seconds(started))
        return config.NOT_TRACKED_NOTE.format(path=_rel(target))
    rel = resolved.relative_to(config.REPO_ROOT).as_posix()
    if diffing.is_tracked(rel):
        output = diffing.git_diff(rel)
        logger.info("get_file_diff: %s — git diff HEAD, %d символов, %.3f с",
                    rel, len(output), _seconds(started))
        return output or config.NO_CHANGES
    text = target.read_text(encoding=config.ENCODING, errors="replace")
    diff = diffing.synthetic_diff(rel, text)
    logger.info("get_file_diff: %s — новый файл, diff синтезирован, %d символов, %.3f с",
                rel, len(diff), _seconds(started))
    return diff
