"""Ручная проверка MCP-сервера разработки (день 31): один вызов инструмента по stdio.

Скрипт поднимает ``mcp_servers/dev_server/server.py`` настоящим клиентом дня 17
(``MCPClient``) — тем же, что использует служба ассистента, — и печатает каталог
инструментов и структурированный результат одного вызова. Так проверяются сразу
четыре вещи, которые иначе видно только через ответ модели: сервер запускается,
каталог собирается из аннотаций функций, вызов доходит до инструмента и результат
приходит не пустым.

Запуск из папки day21/::

    uv run python scripts/dev_mcp_probe.py                          # ветка и статус
    uv run python scripts/dev_mcp_probe.py --tool get_git_diff
    uv run python scripts/dev_mcp_probe.py --tool list_files \
        --args '{"directory": "day21/backend/domain", "extension": ".py"}'
    uv run python scripts/dev_mcp_probe.py --tool get_project_structure --args '{"max_depth": 2}'

Коды возврата: 0 — вызов прошёл, 1 — инструмент вернул ошибку или подключение не
удалось, 2 — негодный ``--args`` (не JSON-объект).
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
from backend.domain import dev_assistant  # noqa: E402
from backend.services.mcp_client import MCPClient  # noqa: E402
from backend.services.mcp_errors import MCPError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Аргументы пробы: инструмент, его аргументы JSON и цель подключения."""
    parser = argparse.ArgumentParser(
        description="Вызвать инструмент MCP-сервера разработки и напечатать результат.",
    )
    parser.add_argument("--tool", choices=dev_assistant.TOOLS,
                        default=dev_assistant.TOOL_GIT_BRANCH,
                        help="имя инструмента (по умолчанию get_git_branch)")
    parser.add_argument("--args", default="{}",
                        help='аргументы инструмента JSON-объектом, например \'{"lines": 20}\'')
    parser.add_argument("--target", default=dev_assistant.DEV_SERVER_TARGET,
                        help=f"цель подключения (по умолчанию {dev_assistant.DEV_SERVER_TARGET})")
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
        print("аргументы должны быть JSON-объектом, например '{\"max_depth\": 2}'")
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
    except MCPError as exc:
        print(f"подключение не удалось: {exc}")
        return 1
    finally:
        print("закрываю сервер")
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
