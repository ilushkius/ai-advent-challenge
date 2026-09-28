"""Демонстрация MCP-клиента дня 17: подключение и список инструментов.

Минимальный код, который делает всю суть дня (MCP SDK):

    from backend.services.mcp_client import MCPClient

    client = MCPClient("uvx mcp-server-fetch")   # stdio; для HTTP — http://…
    client.connect()                             # initialize + согласование
    tools = client.list_tools()                  # tools/list → name, description,
                                                 # input_schema
    client.disconnect()                          # закрыть соединение

Всё остальное в файле — обвязка для консоли: разбор аргументов, читаемый вывод
и понятное сообщение об ошибке подключения (код выхода 1).

Запуск из папки day17/:

    uv run python scripts/mcp_demo.py
    uv run python scripts/mcp_demo.py --target "npx -y @modelcontextprotocol/server-filesystem ."
    uv run python scripts/mcp_demo.py --target http://127.0.0.1:9000/mcp --transport http
    uv run python scripts/mcp_demo.py --json
    uv run python scripts/mcp_demo.py --target "uvx mcp-server-fetch" --timeout 5

Ошибка подключения (неверный URL, нет команды, таймаут) печатается одной строкой
и не оставляет дочерних процессов: клиент закрывает соединение в ``finally``.
"""
import argparse
import json
import sys
from pathlib import Path

# Скрипты лежат в day17/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.core import config  # noqa: E402
from backend.services.mcp_client import MCPClient, MCPError  # noqa: E402

#: Строки, которые печатаются под шапкой: ровно тот код, что идёт в видео.
MINIMAL_CODE = [
    'client = MCPClient("uvx mcp-server-fetch")',
    "client.connect()",
    "tools = client.list_tools()",
    "client.disconnect()",
]


def render_tools(tools) -> None:
    """Печатает инструменты: имя, описание и схему аргументов."""
    for number, tool in enumerate(tools, start=1):
        print(f"\n{number}. {tool.name}")
        print(f"   описание: {tool.description or '—'}")
        schema = json.dumps(tool.input_schema, ensure_ascii=False, indent=2)
        print("   input_schema:")
        print("\n".join(f"     {line}" for line in schema.splitlines()))


def run_demo(target: str, transport: str, timeout: float, as_json: bool) -> int:
    """Подключается, печатает список инструментов и закрывает соединение."""
    client = MCPClient(target, transport=transport, timeout=timeout)
    try:
        client.connect()
        tools = client.list_tools()
        status = {
            "target": client.target.label(),
            "transport": client.target.transport.value,
            "state": client.state.value,
            "server_name": client.server_info.get("name", ""),
            "server_version": client.server_info.get("version", ""),
            "protocol": client.server_info.get("protocol", ""),
            "count": len(tools),
            "tools": [tool.to_dict() for tool in tools],
        }
        if as_json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print(f"цель:       {status['target']}")
            print(f"транспорт:  {client.target.transport.label}")
            print(f"состояние:  {status['state']}")
            print(f"сервер:     {status['server_name']} {status['server_version']}")
            print(f"протокол:   {status['protocol'] or '—'}")
            print(f"инструментов: {status['count']}")
            render_tools(tools)
        return 0
    except MCPError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()  # диалог «закрыть соединение»: stdio-сервер не остаётся висеть


def main() -> int:
    """Разбирает аргументы и запускает демонстрацию."""
    parser = argparse.ArgumentParser(
        description="Подключиться к MCP-серверу и напечатать список его инструментов.",
    )
    parser.add_argument("--target", default=config.MCP_DEFAULT_TARGET,
                        help=f"URL или команда запуска (по умолчанию {config.MCP_DEFAULT_TARGET!r})")
    parser.add_argument("--transport", default="auto",
                        choices=["auto", "stdio", "sse", "http"],
                        help="транспорт; auto — по виду цели")
    parser.add_argument("--timeout", type=float, default=config.MCP_TIMEOUT,
                        help=f"таймаут подключения и запросов, с (по умолчанию {config.MCP_TIMEOUT:g})")
    parser.add_argument("--json", action="store_true",
                        help="напечатать результат как JSON (то же, что отдаёт GET /mcp/tools)")
    args = parser.parse_args()

    print("=== MCP-демо дня 17 ===")
    print("минимальный код:")
    for line in MINIMAL_CODE:
        print(f"    {line}")
    print()
    return run_demo(args.target, args.transport, args.timeout, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
