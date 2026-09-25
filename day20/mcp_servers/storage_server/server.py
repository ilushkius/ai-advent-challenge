"""MCP-сервер ``storage_server`` (день 20): четыре инструмента сохранения и выдачи.

Сервер говорит по stdio (JSON-RPC через stdin/stdout) и запускается клиентом-
оркестратором отдельным процессом. Инструменты:

- ``save_to_file`` — текст файлом в каталог ``output/`` (``--output-dir``);
- ``save_to_db`` — строка в базу ``storage.db`` (``--db-path``);
- ``list_saved`` — список сохранённого: файлы, строки базы или и то и другое;
- ``load_from_file`` — чтение сохранённого файла по имени.

Контракт тот же, что у инструментов дня 19 (AGENTS.md): параметры типизированы (из
аннотаций SDK собирает ``inputSchema``), докстринг описывает параметры и пример
вызова (его читает модель), возврат — ``TypedDict`` из ``schemas.py`` (из него
собирается ``outputSchema``), а ошибка — данные: ``ToolError`` с понятным текстом.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

# Пакетный контекст: при запуске файлом (``python mcp_servers/storage_server/server.py``)
# корень дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[2]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

# Импорт config идёт первым: он добавляет корень репозитория в sys.path, без чего
# общий пакет shared/ не виден из процесса MCP-сервера.
from mcp_servers.storage_server import config, db, files  # noqa: E402
from mcp_servers.storage_server.schemas import (  # noqa: E402
    LoadedFile,
    SavedFile,
    SavedList,
    SavedRecord,
)
from shared.logging_utils import get_logger  # noqa: E402

logger = get_logger(__name__)

server = MCPServer(
    name=config.SERVER_NAME,
    version=config.SERVER_VERSION,
    instructions=config.SERVER_INSTRUCTIONS,
)


@server.tool()
def save_to_file(content: str, filename: str = "orchestration_result.md",
                 format: str = config.SAVE_FORMAT_DEFAULT) -> SavedFile:
    """Сохраняет текст файлом в каталог дня ``output/``.

    Параметры: content — текст для записи (до 20000 символов, обычно сводка шага
    оркестрации); filename — имя файла без пути и «..» (по умолчанию
    ``orchestration_result.md``; расширение заменяется на запрошенный формат);
    format — ``md`` (по умолчанию), ``txt`` или ``json``.

    Возвращает объект с полями filename, filepath (абсолютный путь — по нему файл
    открывают), size_bytes, format и saved_at (ISO-8601 UTC). Пример:
    save_to_file(content="# Сводка\\nRAG — это …", filename="rag-summary.md").

    Слишком длинный текст, чужой формат и опасное имя — ошибка с причиной.
    """
    text = content if isinstance(content, str) else str(content)
    if len(text) > config.FILE_CONTENT_MAX:
        raise ToolError(f"Текст длиннее допустимого ({config.FILE_CONTENT_MAX} символов)")
    try:
        return files.save(text, filename, format)
    except files.SaveFileError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def save_to_db(kind: str, title: str, content: str, source: str = "",
               metadata: Dict[str, Any] | None = None) -> SavedRecord:
    """Записывает строку в базу ``storage.db`` и возвращает сведения о ней.

    Параметры: kind — вид записи (например ``orchestration``; до 64 символов);
    title — заголовок (до 200 символов); content — текст (до 20000 символов);
    source — источник записи (например ``search_web``; до 200 символов);
    metadata — необязательный объект с дополнительными полями (сохраняется
    JSON-строкой).

    Возвращает объект с полями row_id (id строки в базе), kind, title, source,
    size_bytes и created_at (ISO-8601 UTC). Пример: save_to_db(kind="orchestration",
    title="Сводка по RAG", content="…", source="search_web",
    metadata={"file": "output/rag.md"}).

    Пустой вид или заголовок и слишком длинный текст — ошибка с причиной.
    """
    try:
        db.ensure_schema()
        return db.insert(kind, title, content, source, metadata)
    except db.SavedRecordError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def list_saved(kind: str = "all", limit: int = config.LIST_LIMIT_DEFAULT) -> SavedList:
    """Возвращает список сохранённого: файлы каталога ``output/`` и строки базы.

    Параметры: kind — что показать: ``all`` (по умолчанию, и файлы, и строки),
    ``file`` (только файлы) или ``row`` (только строки базы); limit — сколько
    записей каждого вида вернуть (1..50, по умолчанию 10, значения вне границ
    подтягиваются к ним).

    Возвращает объект с полями files (свежие сверху), rows (свежие сверху), count
    (общее число записей обоих видов) и kind (вид выборки). Пример:
    list_saved(kind="row", limit=5).

    Чужой вид выборки — ошибка с перечнем допустимых.
    """
    kind_value = (kind or "").strip().lower() or "all"
    if kind_value not in config.LIST_KINDS:
        raise ToolError(
            f"Вид «{kind}» не поддержан. Допустимы: " + ", ".join(config.LIST_KINDS)
        )
    file_items = []
    if kind_value in ("all", "file"):
        try:
            file_items = files.list_files(limit)
        except (files.SaveFileError, files.LoadFileError) as exc:
            raise ToolError(str(exc)) from exc
    row_items = []
    if kind_value in ("all", "row"):
        try:
            row_items = db.list_rows(limit)
        except db.SavedRecordError as exc:
            raise ToolError(str(exc)) from exc
    return SavedList(
        files=file_items,
        rows=row_items,
        count=len(file_items) + len(row_items),
        kind=kind_value,
    )


@server.tool()
def load_from_file(filename: str) -> LoadedFile:
    """Читает сохранённый файл каталога ``output/`` по имени.

    Параметр: filename — имя файла без пути и «..» (например
    ``rag-summary.md``; имя чистится теми же правилами, что у ``save_to_file``).

    Возвращает объект с полями filename, filepath, chars (число символов), format
    и text (содержимое как есть). Пример: load_from_file(filename="rag-summary.md").

    Опасное имя, файл вне каталога вывода и отсутствие файла — ошибка с причиной.
    """
    try:
        return files.load(filename)
    except files.LoadFileError as exc:
        raise ToolError(str(exc)) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки сервера (основной транспорт — stdio)."""
    parser = argparse.ArgumentParser(
        prog="storage_server",
        description="MCP-сервер сохранения и выдачи дня 20 (транспорт stdio).",
    )
    parser.add_argument(
        "--output-dir", default=str(config.OUTPUT_DIR),
        help="каталог файлов результатов (по умолчанию day20/output/)",
    )
    parser.add_argument(
        "--db-path", default=str(config.DB_PATH),
        help="файл базы сохранённых строк (по умолчанию day20/storage.db)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Настраивает каталог вывода и базу и запускает сервер по stdio."""
    args = parse_args(argv)
    files.configure(args.output_dir)
    db.configure(args.db_path)
    logger.info("storage_server: каталог %s, база %s", files.output_dir(), db.db_path())
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
