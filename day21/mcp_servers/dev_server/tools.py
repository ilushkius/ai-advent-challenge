"""Тела четырёх инструментов MCP-сервера разработки (день 31).

Инструменты отвечают про РЕПОЗИТОРИЙ, а не про данные проекта: состояние рабочего
дерева (``get_git_branch``), последние строки diff (``get_git_diff``), содержимое
каталога (``list_files``) и дерево папки дня (``get_project_structure``). Ассистент
разработчика вызывает их, когда вопрос касается ветки, коммита, изменённых файлов
или структуры проекта.

Почему ``subprocess``, а не библиотека git. Одна команда git — это одна строка
ввода-вывода: ``rev-parse``, ``log -1``, ``status --porcelain``, ``diff HEAD``.
Библиотека добавила бы зависимость ради разбора того же текста, а внешний вызов
даёт ровно то, что видит разработчик в терминале, и падает тем же текстом, если
git не в PATH.

Границы аргументов проверяются здесь, а не в схеме инструмента: схема описывает
ТИПЫ (SDK собирает её из аннотаций), а «``lines`` больше 500» или «каталог вне
репозитория» — правила предметной области. Каждая такая проверка бросает
``ToolError`` с русским текстом: ошибка инструмента приходит модели данными
(``is_error``), и она же видна в разделе «🛠 MCP-инструменты».
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.dev_server import config
from mcp_servers.dev_server.config import (  # noqa: F401  (реэкспорт корней для скриптов)
    DAY_ROOT,
    REPO_ROOT,
)
from mcp_servers.dev_server.schemas import FileList, GitBranchInfo

__all__ = ["DAY_ROOT", "REPO_ROOT", "get_git_branch", "get_git_diff",
           "get_project_structure", "list_files"]

#: Что показать, когда рабочее дерево и индекс совпадают с HEAD.
NO_CHANGES = "Изменений в рабочем дереве нет."


def _git(*args: str) -> str:
    """Вывод команды git в корне репозитория; сбой — ``ToolError``.

    ``errors="replace"`` не даёт упасть на выводе с чужой кодировкой (git может
    вернуть пути в CP1251), а таймаут важнее полноты: подвисшая команда оставила бы
    вызов инструмента без ответа.
    """
    try:
        completed = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True, timeout=config.GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"git не сработал: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"git не сработал: таймаут {config.GIT_TIMEOUT:g} с") from exc
    except subprocess.CalledProcessError as exc:
        stderr = str(exc.stderr or "").strip()
        raise ToolError(f"git не сработал: {stderr or exc}") from exc
    return completed.stdout or ""


def _modified_paths(status_text: str) -> list[str]:
    """Пути из вывода ``git status --porcelain``: у переименования — новый путь.

    Формат строки — два символа состояния, пробел и путь. У переименования в пути
    стоит ``old -> new``: разработчику нужен новый путь, иначе изменённый файл
    «не находится» в репозитории.
    """
    paths = []
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if "->" in path:
            path = path.split("->", 1)[1].strip()
        path = path.strip('"')
        if path:
            paths.append(path)
    return paths


def get_git_branch() -> GitBranchInfo:
    """Возвращает ветку, последний коммит и изменённые файлы репозитория.

    Параметров нет: вопрос «где мы сейчас» один на весь репозиторий, а корень
    зафиксирован (``config.REPO_ROOT``).

    Возвращает словарь: ``branch`` — имя ветки, ``last_commit`` — строка
    ``git log -1 --oneline``, ``modified_files`` — пути изменённых файлов
    (не больше ``config.MAX_MODIFIED``), ``clean`` — признак чистого рабочего
    дерева, ``repo_root`` — корень репозитория.

    Пример: ``get_git_branch()`` → ``{"branch": "main", "last_commit": "day30: …",
    "modified_files": ["day21/app.py"], "clean": false, "repo_root": "…"}``.

    Ошибка: git не найден в PATH, команда не выполнена или истёк таймаут —
    ``ToolError`` с текстом «git не сработал: …».
    """
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    last_commit = _git("log", "-1", "--oneline").strip()
    modified = _modified_paths(_git("status", "--porcelain"))
    return GitBranchInfo(
        branch=branch,
        last_commit=last_commit,
        modified_files=modified[:config.MAX_MODIFIED],
        clean=not modified,
        repo_root=str(REPO_ROOT),
    )


def list_files(directory: str, extension: str = "") -> FileList:
    """Перечисляет файлы одного каталога репозитория (нерекурсивно).

    Параметры: ``directory`` — путь от корня репозитория (``"day21/backend"``);
    ``extension`` — фильтр по расширению, ведущая точка не нужна (``".py"`` и
    ``"py"`` равнозначны), пустая строка — все файлы.

    Возвращает словарь: ``directory`` — запрошенный путь, ``extension`` — фильтр,
    ``count`` — число имён в ``files``, ``truncated`` — файлов было больше
    ``config.MAX_FILES``, ``files`` — имена файлов по алфавиту.

    Пример: ``list_files(directory="day21/backend/domain", extension=".py")`` →
    ``{"directory": "day21/backend/domain", "extension": ".py", "count": 40,
    "truncated": false, "files": ["chunking.py", …]}``.

    Ошибка: путь уводит за корень репозитория (``"Путь вне репозитория: …"``) или
    каталога нет (``"Каталог не найден: …"``) — ``ToolError``.
    """
    target = _inside_repo(directory)
    if not target.is_dir():
        raise ToolError(f"Каталог не найден: {directory}")
    suffix = str(extension or "").strip().lstrip(".").lower()
    names = sorted(path.name for path in target.iterdir()
                   if path.is_file() and _matches(path, suffix))
    return FileList(directory=str(directory), extension=str(extension or ""),
                    count=len(names[:config.MAX_FILES]),
                    truncated=len(names) > config.MAX_FILES,
                    files=names[:config.MAX_FILES])


def get_git_diff(lines: int = 50) -> str:
    """Возвращает последние строки diff рабочего дерева и индекса относительно HEAD.

    Параметры: ``lines`` — сколько последних строк diff вернуть, от
    ``config.MIN_DIFF_LINES`` до ``config.MAX_DIFF_LINES``.

    Возвращает текст diff (без заголовка коммита) или ``"Изменений в рабочем дереве
    нет."``, если рабочее дерево совпадает с HEAD.

    Пример: ``get_git_diff(lines=100)`` → ``"@@ -1,3 +1,4 @@\\n+новая строка…"``.

    Ошибка: ``lines`` вне границ — ``ToolError`` (схема инструмента ловит только
    тип); сбой git — тот же ``ToolError`` «git не сработал: …».
    """
    limit = int(lines)
    if not config.MIN_DIFF_LINES <= limit <= config.MAX_DIFF_LINES:
        raise ToolError(f"lines вне границ {config.MIN_DIFF_LINES}–"
                        f"{config.MAX_DIFF_LINES}: {limit}")
    diff = _git("diff", "HEAD")
    if not diff.strip():
        return NO_CHANGES
    return "\n".join(diff.rstrip("\n").splitlines()[-limit:])


def get_project_structure(max_depth: int = 3) -> dict:
    """Возвращает дерево папки дня: каталоги, файлы и их число.

    Параметры: ``max_depth`` — глубина обхода от ``config.MIN_DEPTH`` до
    ``config.MAX_DEPTH`` (1 — только каталоги и файлы корня папки дня).

    Возвращает словарь ``{"root": str, "max_depth": int, "directories": int,
    "files": int, "tree": {"name": str, "kind": "dir"|"file", "children": [...]}}``.
    ``directories`` считает обойдённые каталоги вместе с корнем, ``files`` — все
    найденные файлы (в ``children`` попадают первые ``config.MAX_TREE_FILES`` имён
    на каталог), служебные каталоги ``config.SKIP_DIRS`` пропускаются, каталоги
    идут перед файлами и обходятся до предела глубины.

    Пример: ``get_project_structure(max_depth=1)`` → ``{"root": "…/day21",
    "max_depth": 1, "directories": 8, "files": 12, "tree": {"name": "day21",
    "kind": "dir", "children": [{"name": "backend", "kind": "dir",
    "children": []}, …]}}``.

    Ошибка: ``max_depth`` вне границ — ``ToolError``. Недоступный каталог не
    роняет обход: его ветка приходит пустой.
    """
    depth = int(max_depth)
    if not config.MIN_DEPTH <= depth <= config.MAX_DEPTH:
        raise ToolError(f"max_depth вне границ {config.MIN_DEPTH}–"
                        f"{config.MAX_DEPTH}: {depth}")
    budget = {"directories": 1, "files": 0}
    tree = _branch(DAY_ROOT, depth, budget)
    return {"root": str(DAY_ROOT), "max_depth": depth,
            "directories": budget["directories"], "files": budget["files"],
            "tree": tree}


def _inside_repo(directory: str) -> Path:
    """Каталог внутри корня репозитория: разрешённый путь или ``ToolError``.

    ``Path.resolve()`` разворачивает и ``..``, и абсолютный путь, поэтому проверка
    принадлежности корню ловит обе попытки выйти наружу.
    """
    target = Path(str(directory or "")).expanduser()
    resolved = (target if target.is_absolute() else REPO_ROOT / target).resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise ToolError(f"Путь вне репозитория: {directory}")
    return resolved


def _matches(path: Path, suffix: str) -> bool:
    """Подходит ли файл под фильтр расширения (пустой фильтр — любой файл)."""
    return not suffix or path.suffix.lstrip(".").lower() == suffix


def _branch(path: Path, depth: int, budget: dict) -> dict:
    """Ветка дерева: каталоги (рекурсивно до ``depth``) и имена файлов.

    Порядок детерминирован (сортировка по имени): отчёт прогона не должен
    меняться от порядка обхода файловой системы.
    """
    node = {"name": path.name, "kind": "dir", "children": []}
    try:
        entries = list(path.iterdir())
    except OSError:
        return node
    folders = sorted((item for item in entries
                      if item.is_dir() and item.name not in config.SKIP_DIRS),
                     key=lambda item: item.name)
    files = sorted((item for item in entries if item.is_file()),
                   key=lambda item: item.name)
    for folder in folders:
        budget["directories"] += 1
        child = ({"name": folder.name, "kind": "dir", "children": []}
                 if depth <= 1 else _branch(folder, depth - 1, budget))
        node["children"].append(child)
    budget["files"] += len(files)
    for item in files[:config.MAX_TREE_FILES]:
        node["children"].append({"name": item.name, "kind": "file", "children": []})
    return node
