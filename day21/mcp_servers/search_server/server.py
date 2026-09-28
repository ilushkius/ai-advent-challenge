"""MCP-сервер поиска данных дня 20: ``search_web``, ``search_local``, ``fetch_url``.

Один из трёх независимых серверов флота. Поднимается ОТДЕЛЬНЫМ процессом по stdio
(JSON-RPC через stdin/stdout, логи — в stderr), а вызовы к нему маршрутизирует
реестр дня по имени инструмента. Сервер не знает ни про ``backend/``, ни про
соседние серверы флота: связывает их протокол MCP и конфигурация
``mcp_servers.json``.

Из чего SDK собирает контракт инструмента:

- **имя** — имя функции;
- **описание** — её докстринг (его читает модель, поэтому там и параметры, и
  пример вызова);
- **inputSchema** — типизированные параметры (``limit: int`` → ``integer``);
- **outputSchema** — аннотация возврата ``TypedDict`` (``schemas.py``), а
  ``structuredContent`` ответа становится самим словарём.

Тела инструментов живут каждый в своём модуле рядом со своей логикой
(``web.py`` — лента API и Википедия, ``local.py`` — файл папки дня, ``fetch.py`` —
страница по HTTP), а здесь — только имя, версия, инструкция и разбор аргументов.

Запуск руками (сервер ждёт JSON-RPC на stdin — это транспорт протокола, а не
зависание; ``--api-base`` подменяет ленту внешнего API, ``--wiki-base`` — API
Википедии, ``--file-root`` — корень источников ``search_local``):

    uv run python mcp_servers/search_server/server.py
    uv run python mcp_servers/search_server/server.py --api-base http://127.0.0.1:8080
    uv run python mcp_servers/search_server/server.py --file-root . --timeout 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Пакетный контекст: при запуске файлом (``python mcp_servers/search_server/server.py``)
# корень дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[2]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from mcp_servers.search_server import fetch, local, web  # noqa: E402
from mcp_servers.search_server.config import (  # noqa: E402
    DEFAULT_API_BASE,
    DEFAULT_TIMEOUT,
    FILE_ROOT,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_VERSION,
    WIKI_API_BASE,
)

server = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
)

# Регистрация: тела и докстринги инструментов лежат в своих модулях, поэтому
# обёрток здесь нет — иначе описание параметров пришлось бы держать в двух местах.
server.tool()(web.search_web)
server.tool()(local.search_local)
server.tool()(fetch.fetch_url)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки сервера (основной транспорт — stdio)."""
    parser = argparse.ArgumentParser(
        prog="server.py",
        description=(
            "MCP-сервер поиска данных дня 20: search_web (лента jsonplaceholder "
            "или Википедия), search_local (файл внутри папки дня), fetch_url "
            "(страница по HTTP → текст)."
        ),
        epilog=(
            "Транспорт — stdio: сервер читает JSON-RPC со stdin и пишет ответы в "
            "stdout. Запускать вручную нужно для отладки; в приложении дня его "
            "поднимает реестр MCP-серверов дочерним процессом:\n"
            "  uv run python mcp_servers/search_server/server.py\n"
            "Тесты подменяют внешние адреса локальным стендом (--api-base) и "
            "каталог источников (--file-root), поэтому в сеть не ходят."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-base", default=DEFAULT_API_BASE,
        help=f"адрес ленты внешнего API (по умолчанию {DEFAULT_API_BASE})",
    )
    parser.add_argument(
        "--wiki-base", default=WIKI_API_BASE,
        help=f"адрес API Википедии (по умолчанию {WIKI_API_BASE})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"таймаут HTTP-запроса, с (по умолчанию {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--file-root", default=str(FILE_ROOT),
        help=(
            "корень локальных источников search_local: читать разрешено только "
            f"файлы внутри него (по умолчанию {FILE_ROOT})"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Настраивает источники по аргументам и запускает сервер по stdio."""
    args = parse_args(argv)
    web.configure(api_base=args.api_base, wiki_base=args.wiki_base,
                  timeout=args.timeout)
    fetch.configure(timeout=args.timeout)
    local.configure(file_root=args.file_root)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
