"""Инструмент ``search_local`` сервера поиска (день 20): файлы внутри папки дня.

Файл читается только ВНУТРИ корня дня (``--file-root``, по умолчанию ``day20/``):
путь разрешается через ``Path.resolve()`` и проверяется на принадлежность корню,
поэтому ``../../etc/passwd`` не читается, даже если модель попросит.

Содержимое делится на блоки по пустым строкам — блок это абзац заметки. Запрос
ищется подстрокой без учёта регистра в блоке, ``limit`` отсекает выдачу после
фильтра. Заголовок блока — его первая непустая строка, содержимое — весь блок.

Ошибка инструмента — ``ToolError`` с текстом для человека и модели: «файл вне
папки дня» и «файл источника не найден» — разные причины, и обе видит модель.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.search_server import config
from mcp_servers.search_server.schemas import LocalSearchResult, SearchItem
from mcp_servers.search_server.web import clamp_limit

#: Разделитель блоков: пустая строка, возможно с пробелами.
BLOCK_SPLIT = re.compile(r"\n\s*\n")

#: Настройки процесса: корень, внутри которого разрешено читать файлы.
_file_root: Path = Path(config.FILE_ROOT)


def configure(file_root: str | Path | None = None) -> None:
    """Задаёт корень локальных источников (аргумент ``--file-root`` сервера)."""
    global _file_root
    if file_root is not None:
        _file_root = Path(file_root).resolve()


def file_root() -> Path:
    """Текущий корень локальных источников (нужен тестам и отчёту прогона)."""
    return _file_root


def search_local(query: str, path: str = "mcp_server/data/notes.md",
                 limit: int = 5) -> LocalSearchResult:
    """Ищет блоки текста в файле внутри папки дня.

    Параметры: query — что искать (подстрока без учёта регистра в блоке; пустая
    строка — первые блоки файла); path — путь к файлу: относительный (от корня
    папки дня, по умолчанию ``mcp_server/data/notes.md``) или абсолютный ВНУТРИ
    папки дня; limit — сколько блоков вернуть (1..20, по умолчанию 5).

    Возвращает объект с полями query, path, count и items — массивом найденного
    (id, title — первая строка блока, content — блок целиком, url пуст,
    metadata с путём и номером блока). Номер блока считается с единицы по всему
    файлу, поэтому одинаковые запросы дают те же id. Пример:
    search_local(query="RAG", path="mcp_server/data/notes.md", limit=3).

    Если путь выходит за папку дня или файла нет, инструмент сообщает об ошибке.
    """
    target = resolve_path(path)
    text = target.read_text(encoding="utf-8", errors="replace")
    blocks = [block.strip() for block in BLOCK_SPLIT.split(text)]
    blocks = [block for block in blocks if block]
    needle = (query or "").strip().lower()
    size = clamp_limit(limit)
    items: List[SearchItem] = []
    for index, block in enumerate(blocks, start=1):
        if needle and needle not in block.lower():
            continue
        items.append(SearchItem(
            id=f"file:{path}#{index}",
            title=first_line(block),
            content=block[:config.CONTENT_MAX],
            url="",
            metadata={"path": path, "block": str(index)},
        ))
        if len(items) >= size:
            break
    return LocalSearchResult(query=query, path=path, count=len(items), items=items)


def resolve_path(path: Any) -> Path:
    """Путь к файлу дня: существующий и лежащий внутри корня локальных источников."""
    raw = str(path or "").strip()
    if not raw:
        raise ToolError("Путь к файлу пуст")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path(_file_root) / candidate
    resolved = candidate.resolve()
    root = Path(_file_root).resolve()
    if not resolved.is_relative_to(root):
        raise ToolError(
            f"Файл «{raw}» вне папки дня: разрешены только файлы внутри {root}"
        )
    if not resolved.is_file():
        raise ToolError(f"Файл источника не найден: {raw}")
    return resolved


def first_line(block: str) -> str:
    """Заголовок блока — его первая непустая строка, обрезанная до лимита."""
    for line in block.splitlines():
        if line.strip():
            return line.strip()[:config.TITLE_MAX]
    return ""
