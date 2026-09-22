"""Тестовый MCP-сервер по stdio (ассет тестов, не тест).

`tests/integration/test_mcp_stdio.py` запускает этот файл дочерним процессом
того же интерпретатора (``sys.executable``) и проверяет настоящий путь stdio:
JSON-RPC по stdin/stdout, ``initialize``, ``tools/list``. Сеть и установка
пакетов не нужны — сервер собран на ``mcp.server.mcpserver.MCPServer`` (mcp 2.x).

Два инструмента с разными схемами: ``echo`` (строка + флаг) и ``add`` (два
целых) — по ним видно, что ``input_schema`` действительно приходит от сервера.

Запуск руками (сервер ждёт JSON-RPC на stdin):

    uv run python tests/mcp_echo_server.py
"""
import sys
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer(name="day17-echo-server", version="1.0.0")


@server.tool()
def echo(text: str, uppercase: bool = False) -> str:
    """Возвращает переданный текст (флаг uppercase — в верхнем регистре)."""
    return text.upper() if uppercase else text


@server.tool()
def add(a: int, b: int) -> int:
    """Складывает два целых числа и возвращает сумму."""
    return a + b


if __name__ == "__main__":
    server.run(transport="stdio")
