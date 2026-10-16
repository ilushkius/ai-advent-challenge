"""Сборка MCP-сервера файлов (день 34): каталог инструментов и точка входа.

Одиннадцать инструментов регистрируются здесь — шесть инструментов файлов из
``tools.py`` и пять инструментов git-истории из ``git_history.py``: так их читают и
тестируют отдельно от сборки сервера, а SDK собирает контракт из самой функции —
имя, докстринг и аннотации. Регистрация внешних функций
(``server.tool()(tools.read_file)``), а не объявления в этом файле, по той же
причине, что у серверов дней 31 и 33.

Отличие от остальных серверов дня — аргумент ``--file-root``: рабочая область
инструментов (по умолчанию папка дня ``day21/``) задаётся при запуске. Тестам он
нужен обязательно: интеграционный тест поднимает сервер на ВРЕМЕННОМ каталоге и не
должен трогать рабочее дерево дня. Так же сделан ``--file-root`` у
``search_server/server.py``.

``configure_logging`` вызывается здесь, потому что ``get_logger`` (общий для всех
дней) не ставит хендлеров: без явного вызова требования «логирование каждого
вызова» не было бы видно, а вывод идёт в stderr — stdout занят JSON-RPC транспорта.

Запуск (обычно его поднимает клиент ассистента файлов):

    uv run python mcp_servers/file_server/server.py
    uv run python mcp_servers/file_server/server.py --file-root .
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Пакетный контекст: при запуске файлом (``python mcp_servers/file_server/server.py``)
# корень дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[2]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

# ``config`` импортируется ДО ``shared``: он добавляет корень репозитория в
# ``sys.path``, и только после этого общий пакет ``shared/`` находится при запуске
# файлом (сервер стартует отдельным процессом с рабочим каталогом ``day21/``).
from mcp_servers.file_server import config  # noqa: E402
from shared.logging_utils import configure_logging  # noqa: E402

from mcp_servers.file_server import git_history  # noqa: E402
from mcp_servers.file_server import tools  # noqa: E402

server = MCPServer(name=config.SERVER_NAME, version=config.SERVER_VERSION,
                   instructions=config.SERVER_INSTRUCTIONS)
server.tool()(tools.read_file)
server.tool()(tools.search_in_files)
server.tool()(tools.list_files)
server.tool()(tools.write_file)
server.tool()(tools.apply_patch)
server.tool()(tools.get_file_diff)
server.tool()(git_history.get_tags)
server.tool()(git_history.get_commits_between)
server.tool()(git_history.get_changed_files_between)
server.tool()(git_history.get_commit_stats)
server.tool()(git_history.get_project_metrics)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки сервера (основной транспорт — stdio)."""
    parser = argparse.ArgumentParser(
        description="MCP-сервер файлов проекта дня 34 (read/search/list/write/patch/diff) "
                    "и git-истории релиза дня 35 (tags/commits/changed-files/stats/metrics).",
    )
    parser.add_argument("--file-root", default=str(config.DAY_ROOT),
                        help="корень рабочей области инструментов "
                             "(по умолчанию папка дня day21/)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Настраивает рабочую область и запускает сервер по stdio."""
    args = parse_args(argv)
    tools.configure(file_root=Path(args.file_root))
    configure_logging(logging.INFO)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
