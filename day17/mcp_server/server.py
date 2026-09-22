"""Собственный MCP-сервер дня 17: три инструмента поверх jsonplaceholder.

Сервер собран на ``mcp.server.mcpserver.MCPServer`` (mcp 2.x) и общается с
клиентом по stdio: JSON-RPC идёт через stdin/stdout, ошибки и логи — в stderr.
Из чего SDK собирает контракт инструмента:

- **имя** — имя функции;
- **описание** — её докстринг (его читает модель, поэтому там и параметры, и
  пример вызова);
- **inputSchema** — типизированные параметры (``user_id: int`` → ``integer``);
- **outputSchema** — аннотация возврата ``TypedDict`` (``mcp_server/schemas.py``),
  а ``structuredContent`` ответа становится самим словарём.

Инструменты не знают про транспорт: их тела — одна строка вызова
``mcp_server/api_client.py``, поэтому правила чтения внешнего API и тексты ошибок
живут в одном модуле, а не размазаны по трём функциям.

Запуск руками (сервер ждёт JSON-RPC на stdin — это транспорт протокола, а не
зависание; ``--api-base`` подменяет внешний API, что нужно тестам):

    uv run python mcp_server/server.py
    uv run python mcp_server/server.py --api-base http://127.0.0.1:8080 --timeout 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Пакетный контекст: при запуске файлом (``python mcp_server/server.py``) корень
# дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from mcp_server.api_client import ExternalAPIError, configure, get_client  # noqa: E402
from mcp_server.config import (  # noqa: E402
    DEFAULT_API_BASE,
    DEFAULT_TIMEOUT,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_VERSION,
)
from mcp_server.schemas import PostInfo, UserInfo, UserPosts  # noqa: E402

server = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
)


def _run(call, *args):
    """Вызов внешнего API с переводом его ошибки в ошибку инструмента.

    ``ToolError`` SDK превращает в результат ``isError`` с нашим текстом —
    именно так объяснение («у jsonplaceholder 10 пользователей») доходит до
    модели. Необёрнутое исключение стало бы для клиента строкой
    ``Error executing tool get_user``: причина теряется.
    """
    try:
        return call(*args)
    except ExternalAPIError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def get_user(user_id: int) -> UserInfo:
    """Возвращает данные пользователя по его id.

    Параметр user_id — целое число (у jsonplaceholder 10 пользователей, id от 1
    до 10). Возвращает объект с полями id, name, username, email, city, phone,
    website, company. Пример вызова: get_user(user_id=1).

    Если пользователя с таким id нет, инструмент сообщает об ошибке (HTTP 404).
    """
    return _run(get_client().get_user, user_id)


@server.tool()
def get_post(post_id: int) -> PostInfo:
    """Возвращает пост по его id.

    Параметр post_id — целое число (у jsonplaceholder 100 постов, id от 1 до
    100). Возвращает объект с полями id, user_id, title, body: user_id — автор
    поста. Пример вызова: get_post(post_id=1).

    Если поста с таким id нет, инструмент сообщает об ошибке (HTTP 404).
    """
    return _run(get_client().get_post, post_id)


@server.tool()
def list_user_posts(user_id: int, limit: int = 5) -> UserPosts:
    """Возвращает посты пользователя.

    Параметры: user_id — целое число (кто автор), limit — сколько постов вернуть
    (от 1 до 20, по умолчанию 5). Возвращает объект с полями user_id, count и
    posts — список записей с id и title. Пример: list_user_posts(user_id=1,
    limit=3).
    """
    return _run(get_client().list_user_posts, user_id, limit)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки сервера (основной транспорт — stdio)."""
    parser = argparse.ArgumentParser(
        prog="server.py",
        description=(
            "MCP-сервер дня 17: инструменты get_user, get_post, list_user_posts "
            "поверх jsonplaceholder.typicode.com."
        ),
        epilog=(
            "Транспорт — stdio: сервер читает JSON-RPC со stdin и пишет ответы в "
            "stdout. Запускать вручную нужно для отладки; в приложении дня его "
            "поднимает MCP-клиент дочерним процессом:\n"
            "  uv run python mcp_server/server.py"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-base", default=DEFAULT_API_BASE,
        help=f"адрес внешнего API (по умолчанию {DEFAULT_API_BASE})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"таймаут HTTP-запроса к внешнему API, с (по умолчанию {DEFAULT_TIMEOUT:g})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Настраивает клиента внешнего API и запускает сервер по stdio."""
    args = parse_args(argv)
    configure(args.api_base, args.timeout)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
