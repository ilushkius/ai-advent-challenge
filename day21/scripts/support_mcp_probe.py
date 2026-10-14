"""Ручная проверка MCP-сервера поддержки (день 33): один вызов инструмента по stdio.

Скрипт поднимает ``mcp_servers/support_server/server.py`` настоящим клиентом дня 17
(``MCPClient``) — тем же, что использует служба поддержки, — и печатает каталог
инструментов и структурированный результат одного вызова. Так проверяются сразу
четыре вещи, которые иначе видно только через ответ модели: сервер запускается,
каталог собирается из аннотаций функций, вызов доходит до инструмента и результат
приходит не пустым.

Запуск из папки day21/::

    uv run python scripts/support_mcp_probe.py --tool get_user --args '{"user_id": "user_003"}'
    uv run python scripts/support_mcp_probe.py --tool get_ticket --args '{"ticket_id": "ticket_007"}'
    uv run python scripts/support_mcp_probe.py --tool list_user_tickets --args '{"user_id": "user_003"}'
    uv run python scripts/support_mcp_probe.py --tool get_product_info --args '{"product_area": "auth"}'
    uv run python scripts/support_mcp_probe.py --tool list_users
    uv run python scripts/support_mcp_probe.py --tool get_user --args '{"user_id": "user_999"}'

Коды возврата: 0 — вызов прошёл и запись найдена, 1 — инструмент вернул ошибку,
запись не найдена (``error`` в результате) или подключение не удалось, 2 — негодный
``--args`` (не JSON-объект).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня и в
# корне репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.core import config  # noqa: E402
from backend.domain import support  # noqa: E402
from backend.services.mcp_client import MCPClient  # noqa: E402
from backend.services.mcp_errors import MCPError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Аргументы пробы: инструмент, его аргументы JSON и цель подключения."""
    parser = argparse.ArgumentParser(
        description="Вызвать инструмент MCP-сервера поддержки и напечатать результат.",
    )
    parser.add_argument("--tool", choices=support.TOOLS, default=support.TOOL_GET_USER,
                        help="имя инструмента (по умолчанию get_user)")
    parser.add_argument("--args", default="{}",
                        help='аргументы инструмента JSON-объектом, например \'{"user_id": "user_003"}\'')
    parser.add_argument("--target", default=support.SUPPORT_SERVER_TARGET,
                        help=f"цель подключения (по умолчанию {support.SUPPORT_SERVER_TARGET})")
    return parser


def main(argv=None) -> int:
    """Подключается к серверу, вызывает инструмент и печатает результат."""
    args = build_parser().parse_args(argv)
    try:
        arguments = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(f"аргументы не разобраны: {exc}")
        return 2
    if not isinstance(arguments, dict):
        print("аргументы должны быть JSON-объектом, например '{\"user_id\": \"user_003\"}'")
        return 2
    client = MCPClient(args.target, cwd=config.MCP_FLEET_CWD)
    try:
        client.connect()
        tools = client.list_tools()
        print(f"инструменты ({len(tools)}): " + ", ".join(tool.name for tool in tools))
        result = client.call_tool(args.tool, arguments)
        print(f"вызов {args.tool} — {result.duration_ms} мс:")
        if result.structured is not None:
            print(json.dumps(result.structured, ensure_ascii=False, indent=2))
        elif result.text:
            print(result.text)
        if result.is_error:
            print(f"инструмент вернул ошибку: {result.text}")
            return 1
        if isinstance(result.structured, dict) and result.structured.get("error"):
            print(f"запись не найдена: {result.structured['error']}")
            return 1
    except MCPError as exc:
        print(f"подключение не удалось: {exc}")
        return 1
    finally:
        print("закрываю сервер")
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
