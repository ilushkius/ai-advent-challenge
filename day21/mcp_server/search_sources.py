"""Источники инструмента ``search`` (день 19): внешний API, файл дня и SQLite дня.

Единственное место, где ищутся данные для пайплайна. Источник задаётся строкой
одного из трёх видов:

- ``posts`` / ``users`` — лента jsonplaceholder (тот же клиент, что у инструментов
  дня 17: ``mcp_server/api_client.py``), фильтр — подстрока по текстовым полям;
- ``file:<путь>`` — локальный файл ВНУТРИ папки дня: относительный путь,
  разбиение на блоки по пустым строкам, фильтр — подстрока в блоке;
- ``sqlite:<таблица>`` — таблица дня, открытая ТОЛЬКО на чтение (``mode=ro``),
  белый список таблиц и их текстовых колонок — ``config.SQLITE_SOURCES``.

Пути и каталоги настраиваются ``configure()`` (аргументы ``--file-root`` и
``--db-path`` сервера): по умолчанию это папка дня и её ``agents.db``.

Ошибка источника — ``SearchSourceError`` с текстом для человека: инструмент
превращает её в ``ToolError``, поэтому модель видит «таблицы нет в базе дня», а не
трассировку ``sqlite3``. Модуль не знает про MCP SDK: правила тестируются офлайн.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from mcp_server import config
from mcp_server.api_client import ExternalAPIError, get_client
from mcp_server.schemas import SearchItem

#: Виды источников, поддержанные инструментом.
SOURCE_API = "api"
SOURCE_FILE = "file"
SOURCE_SQLITE = "sqlite"

#: Виды лент внешнего API, доступные как источники.
API_SOURCES = ("posts", "users")

#: Список источников для текста ошибки (он же — подсказка модели).
AVAILABLE_HINT = "posts, users, file:<путь>, sqlite:<таблица>"

#: Настройки процесса: каталог локальных источников и база дня.
_file_root: Path = config.FILE_ROOT
_db_path: Path = config.DB_PATH


def configure(file_root: str | Path | None = None,
              db_path: str | Path | None = None) -> None:
    """Задаёт каталог источников ``file:`` и базу источника ``sqlite:``."""
    global _file_root, _db_path
    if file_root is not None:
        _file_root = Path(file_root).resolve()
    if db_path is not None:
        _db_path = Path(db_path)


class SearchSourceError(RuntimeError):
    """Источник не поддержан, недоступен или данных в нём нет по причинам окружения."""


def parse_source(source: str) -> tuple[str, str]:
    """Разбирает источник в ``(вид, уточнение)``.

    ``"posts"`` → ``("api", "posts")``, ``"file:output/x.md"`` →
    ``("file", "output/x.md")``, ``"sqlite:collected_data"`` →
    ``("sqlite", "collected_data")``. Неизвестный вид — ``SearchSourceError``.
    """
    value = (source or "").strip()
    if value in API_SOURCES:
        return SOURCE_API, value
    for prefix, kind in (("file:", SOURCE_FILE), ("sqlite:", SOURCE_SQLITE)):
        if value.startswith(prefix):
            return kind, value[len(prefix):].strip()
    raise SearchSourceError(
        f"Источник «{value}» не поддержан. Доступны: {AVAILABLE_HINT}"
    )


def search_items(query: str, source: str, limit: int) -> tuple[str, list[SearchItem]]:
    """Ищет элементы: возвращает ``(вид источника, элементы)``.

    ``query`` обрезается до ``SEARCH_QUERY_MAX`` (длинный запрос — не ошибка: по
    нему всё равно ищут подстроку), ``source`` длиннее ``SEARCH_SOURCE_MAX`` —
    ошибка (это признак склеенной строки, а не источника), ``limit`` зажимается в
    границы ``SEARCH_LIMIT_MIN``..``SEARCH_LIMIT_MAX``.
    """
    if len(source or "") > config.SEARCH_SOURCE_MAX:
        raise SearchSourceError(
            f"Источник длиннее {config.SEARCH_SOURCE_MAX} символов"
        )
    kind, detail = parse_source(source)
    text = (query or "").strip()[:config.SEARCH_QUERY_MAX]
    size = max(config.SEARCH_LIMIT_MIN, min(int(limit), config.SEARCH_LIMIT_MAX))
    if kind == SOURCE_API:
        return kind, _search_api(text, detail, size)
    if kind == SOURCE_FILE:
        return kind, _search_file(text, detail, size)
    return kind, _search_sqlite(text, detail, size)


# ---------- источники ----------
def _search_api(query: str, detail: str, limit: int) -> list[SearchItem]:
    """Лента jsonplaceholder: читает страницу и фильтрует записи подстрокой."""
    client = get_client()
    try:
        rows = (client.list_posts(config.SEARCH_API_ROWS) if detail == "posts"
                else client.list_users(config.SEARCH_API_ROWS))
    except ExternalAPIError as exc:
        raise SearchSourceError(str(exc)) from exc
    base = client.base_url.rstrip("/")
    items: list[SearchItem] = []
    for row in rows:
        item = _api_item(row, detail, base)
        if query and query.lower() not in item["content"].lower() \
                and query.lower() not in item["title"].lower():
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _api_item(row: dict, detail: str, base: str) -> SearchItem:
    """Запись ленты → элемент результата (пост или пользователь)."""
    row_id = int(row.get("id", 0))
    if detail == "posts":
        return SearchItem(
            id=f"post:{row_id}",
            title=str(row.get("title", "")),
            content=str(row.get("body", ""))[:config.SEARCH_CONTENT_MAX],
            url=f"{base}/posts/{row_id}",
            metadata={"source": "posts", "user_id": int(row.get("userId", 0) or 0)},
        )
    address = row.get("address") or {}
    company = row.get("company") or {}
    return SearchItem(
        id=f"user:{row_id}",
        title=str(row.get("name", "")),
        content=(
            f"{row.get('email', '')}; {address.get('city', '')}; "
            f"{company.get('name', '')}"
        )[:config.SEARCH_CONTENT_MAX],
        url=f"{base}/users/{row_id}",
        metadata={"source": "users", "username": str(row.get("username", ""))},
    )


def _search_file(query: str, detail: str, limit: int) -> list[SearchItem]:
    """Локальный файл дня: блоки по пустым строкам, фильтр — подстрока в блоке.

    Путь обязан быть относительным и после разрешения остаться внутри каталога
    дня: иначе инструмент читал бы произвольный файл машины (``../../etc/passwd``).
    """
    target = _resolve_file(detail)
    root = Path(detail).as_posix()
    text = target.read_text(encoding="utf-8", errors="replace")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text)]
    blocks = [block for block in blocks if block]
    items: list[SearchItem] = []
    for index, block in enumerate(blocks, start=1):
        if query and query.lower() not in block.lower():
            continue
        items.append(SearchItem(
            id=f"file:{root}#{index}",
            title=_first_line(block),
            content=block[:config.SEARCH_CONTENT_MAX],
            url="",
            metadata={"path": root, "block": index, "total_blocks": len(blocks)},
        ))
        if len(items) >= limit:
            break
    return items


def _resolve_file(detail: str) -> Path:
    """Путь источника: относительный, внутри каталога дня и существующий."""
    raw = Path(detail)
    if not detail or raw.is_absolute():
        raise SearchSourceError(
            f"Источник «file:{detail}» должен быть относительным путём внутри папки дня"
        )
    target = (Path(_file_root) / raw).resolve()
    if Path(_file_root).resolve() not in target.parents and target != Path(_file_root):
        raise SearchSourceError(
            f"Источник «file:{detail}» выходит за пределы папки дня"
        )
    if not target.is_file():
        raise SearchSourceError(f"Файл источника не найден: {detail}")
    return target


def _first_line(block: str) -> str:
    """Заголовок блока — его первая непустая строка, обрезанная до лимита."""
    for line in block.splitlines():
        if line.strip():
            return line.strip()[:config.SEARCH_TITLE_MAX]
    return ""


def _search_sqlite(query: str, detail: str, limit: int) -> list[SearchItem]:
    """Таблица дня: белый список таблиц и колонок, соединение только на чтение."""
    table = detail
    columns = config.SQLITE_SOURCES.get(table)
    if columns is None:
        raise SearchSourceError(
            f"Таблица «{table}» недоступна. Доступны: "
            + ", ".join(sorted(config.SQLITE_SOURCES))
        )
    selected = [name for name in columns if name != "id"]
    where = ""
    params: list[str] = []
    if query:
        where = " WHERE (" + " OR ".join(f"{name} LIKE ?" for name in selected) + ")"
        params = [f"%{query}%"] * len(selected)
    sql = (
        f"SELECT id, {', '.join(selected)} FROM {table}{where} "
        f"ORDER BY id DESC LIMIT ?"
    )
    try:
        connection = sqlite3.connect(
            f"file:{Path(_db_path).as_posix()}?mode=ro", uri=True
        )
    except sqlite3.Error as exc:
        raise SearchSourceError(
            f"Таблица «{table}» недоступна в базе дня: {exc}"
        ) from exc
    try:
        with connection:
            rows = connection.execute(sql, [*params, limit]).fetchall()
    except sqlite3.Error as exc:
        raise SearchSourceError(
            f"Таблица «{table}» недоступна в базе дня: {exc}"
        ) from exc
    finally:
        connection.close()
    return [_sqlite_item(table, selected, row) for row in rows]


def _sqlite_item(table: str, columns: list[str], row: tuple) -> SearchItem:
    """Строка таблицы → элемент результата (значения склеены через ``|``)."""
    row_id = row[0]
    values = ["" if value is None else str(value) for value in row[1:]]
    filled = next((value for value in values if value.strip()), "")
    source_url = ""
    if "source_url" in columns:
        source_url = values[columns.index("source_url")]
    return SearchItem(
        id=f"sqlite:{table}:{row_id}",
        title=f"{table}: {filled[:config.SEARCH_TITLE_MAX]}",
        content=" | ".join(values)[:config.SEARCH_CONTENT_MAX],
        url=source_url,
        metadata={"table": table, "columns": ["id", *columns]},
    )
