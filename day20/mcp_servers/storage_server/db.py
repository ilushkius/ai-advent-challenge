"""База ``storage_server``: строки ``storage.db`` на ``sqlite3`` (день 20).

Модуль ведёт одну таблицу ``saved_records``: вид записи, заголовок, текст,
источник, метаданные (JSON-строкой) и момент создания. Это НЕ ``agents.db``:
в базу дня пишет ровно один процесс (бэкенд FastAPI), а ``storage_server`` —
отдельный процесс по stdio, поэтому у него свой файл и, значит, один писатель.

Здесь нет SQLAlchemy — серверу хватает стандартного ``sqlite3``: одна таблица,
простая схема, никакой миграционной машинерии. Соединение открывается на каждый
вызов, коммитится и закрывается; ошибка ``sqlite3`` превращается в
``SavedRecordError`` с понятным русским текстом.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mcp_servers.storage_server import config
from mcp_servers.storage_server.schemas import SavedRecord, SavedRecordInfo

#: Файл базы процесса (переопределяется ``--db-path``).
_db_path: Path = config.DB_PATH

#: Схема таблицы: колонки совпадают с полями ``SavedRecord``.
CREATE_TABLE_SQL = (
    f"CREATE TABLE IF NOT EXISTS {config.DB_TABLE} ("          # noqa: S608 — имя из константы
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "kind TEXT NOT NULL, "
    "title TEXT NOT NULL, "
    "content TEXT NOT NULL, "
    "source TEXT NOT NULL, "
    "metadata TEXT NOT NULL, "
    "created_at TEXT NOT NULL)"
)


class SavedRecordError(RuntimeError):
    """Вид или заголовок пусты, текст слишком длинный или база недоступна."""


def configure(db_path: str | Path | None = None) -> None:
    """Задаёт файл базы (``--db-path`` сервера)."""
    global _db_path
    if db_path is not None:
        _db_path = Path(db_path)


def db_path() -> Path:
    """Текущий файл базы (нужен тестам и отчёту прогона)."""
    return _db_path


def _connect() -> sqlite3.Connection:
    """Открывает соединение с базой процесса (строки — как словари)."""
    connection = sqlite3.connect(str(_db_path))
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> str:
    """Момент времени в ISO-8601 UTC с секундами."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp_limit(limit: int) -> int:
    """Приводит ``limit`` к границам ``LIST_LIMIT_MIN..LIST_LIMIT_MAX``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = config.LIST_LIMIT_DEFAULT
    return max(config.LIST_LIMIT_MIN, min(config.LIST_LIMIT_MAX, value))


def ensure_schema() -> None:
    """Создаёт таблицу ``saved_records``, если её ещё нет (идемпотентно)."""
    connection = None
    try:
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = _connect()
        connection.execute(CREATE_TABLE_SQL)
        connection.commit()
    except sqlite3.Error as exc:
        raise SavedRecordError(f"Не удалось подготовить базу {_db_path}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def insert(kind: str, title: str, content: str, source: str = "",
           metadata: dict | None = None) -> SavedRecord:
    """Записывает строку в базу и возвращает сведения о ней.

    Вид и заголовок обязательны (пустые — ошибка) и обрезаются до ``KIND_MAX`` /
    ``TITLE_MAX``; ``source`` обрезается до ``SOURCE_MAX``; текст длиннее
    ``FILE_CONTENT_MAX`` отклоняется — «простыню» в базу не пишут. Метаданные
    сохраняются JSON-строкой (``ensure_ascii=False``: русский текст читается глазами).
    """
    kind_value = (kind or "").strip()
    title_value = (title or "").strip()
    if not kind_value:
        raise SavedRecordError("Вид записи пуст")
    if not title_value:
        raise SavedRecordError("Заголовок записи пуст")
    text = content if isinstance(content, str) else str(content)
    if len(text) > config.FILE_CONTENT_MAX:
        raise SavedRecordError(
            f"Текст длиннее {config.FILE_CONTENT_MAX} символов: получено {len(text)}"
        )
    kind_value = kind_value[: config.KIND_MAX]
    title_value = title_value[: config.TITLE_MAX]
    source_value = (source or "").strip()[: config.SOURCE_MAX]
    metadata_value = json.dumps(metadata if metadata is not None else {},
                                ensure_ascii=False)
    created_at = _now()
    ensure_schema()
    connection = None
    try:
        connection = _connect()
        cursor = connection.execute(
            f"INSERT INTO {config.DB_TABLE} "                       # noqa: S608 — имя из константы
            "(kind, title, content, source, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (kind_value, title_value, text, source_value, metadata_value, created_at),
        )
        row_id = int(cursor.lastrowid)
        connection.commit()
    except sqlite3.Error as exc:
        raise SavedRecordError(f"Не удалось записать строку в базу {_db_path}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    return SavedRecord(
        row_id=row_id,
        kind=kind_value,
        title=title_value,
        source=source_value,
        size_bytes=len(text.encode("utf-8")),
        created_at=created_at,
    )


def list_rows(limit: int = config.LIST_LIMIT_DEFAULT,
              kind: str | None = None) -> list[SavedRecordInfo]:
    """Список строк базы: свежие сверху, с необязательным фильтром по виду.

    ``kind`` равный ``None`` или ``"all"`` снимает фильтр; ``limit``
    ограничивается границами ``LIST_LIMIT_MIN..LIST_LIMIT_MAX``.
    """
    ensure_schema()
    clause = ""
    params: list = []
    kind_value = (kind or "").strip()
    if kind_value and kind_value != "all":
        clause = " WHERE kind = ?"
        params.append(kind_value)
    params.append(clamp_limit(limit))
    connection = None
    try:
        connection = _connect()
        rows = connection.execute(
            f"SELECT id, kind, title, source, created_at FROM {config.DB_TABLE}"  # noqa: S608
            f"{clause} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
    except sqlite3.Error as exc:
        raise SavedRecordError(f"Не удалось прочитать базу {_db_path}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    return [
        SavedRecordInfo(
            row_id=int(row["id"]),
            kind=row["kind"],
            title=row["title"],
            source=row["source"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
