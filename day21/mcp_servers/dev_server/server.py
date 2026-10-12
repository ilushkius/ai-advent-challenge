"""Сборка MCP-сервера разработки (день 31): каталог инструментов и точка входа.

Сервер stateless: ему нечего настраивать аргументами командной строки. Корни
зафиксированы (``config.REPO_ROOT`` для git, ``config.DAY_ROOT`` для дерева), а
всё, что меняется от вызова к вызову, приходит аргументами инструмента. Поэтому
здесь нет ни ``argparse``, ни конфигурации процесса — только регистрация четырёх
функций ``tools.py`` и запуск по stdio.

Регистрация внешних функций (``server.tool()(tools.get_git_branch)``), а не
объявления в этом файле: тела инструментов лежат в ``tools.py``, потому что их
читают и тестируют отдельно от сборки сервера, а SDK собирает контракт из самой
функции — имя, докстринг и аннотации.

Запуск (обычно его поднимает клиент ассистента разработчика):

    uv run python mcp_servers/dev_server/server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Пакетный контекст: при запуске файлом (``python mcp_servers/dev_server/server.py``)
# корень дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[2]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from mcp_servers.dev_server import tools  # noqa: E402
from mcp_servers.dev_server.config import (  # noqa: E402
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_VERSION,
)

server = MCPServer(name=SERVER_NAME, version=SERVER_VERSION,
                   instructions=SERVER_INSTRUCTIONS)
server.tool()(tools.get_git_branch)
server.tool()(tools.list_files)
server.tool()(tools.get_git_diff)
server.tool()(tools.get_project_structure)


def main(argv=None) -> int:
    """Запускает сервер по stdio: JSON-RPC по stdin/stdout, без сети и портов."""
    del argv
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
