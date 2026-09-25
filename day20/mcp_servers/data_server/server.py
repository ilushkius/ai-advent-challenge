"""MCP-сервер обработки данных дня 20: четыре инструмента над списками и текстом.

Сервер объявляет инструменты ``summarize``, ``extract_keywords``,
``filter_by_date`` и ``aggregate``. Тела инструментов лежат рядом со своей логикой
(``summarize.py``, ``keywords.py``, ``dates.py``, ``aggregate.py``), а здесь —
имя, версия, инструкция и точка входа: сервер поднимается ОТДЕЛЬНЫМ процессом по
stdio и не знает ни о бэкенде дня, ни о двух других серверах флота.

Контракт инструмента (AGENTS.md):

- **имя** — имя функции;
- **описание** — её докстринг (его читает модель, поэтому там параметры и пример);
- **inputSchema** — типизированные параметры (``items: List[Dict[str, Any]]`` →
  ``array``);
- **outputSchema** — аннотация возврата ``TypedDict``
  (``mcp_servers/data_server/schemas.py``), а ``structuredContent`` ответа
  становится самим словарём;
- ошибка инструмента — данные: ``ToolError`` с понятным русским текстом.

Запуск руками (сервер ждёт JSON-RPC на stdin — это транспорт протокола, а не
зависание; ``--llm off`` выключает DeepSeek в ``summarize``, ``--timeout`` задаёт
таймаут его вызова):

    uv run python mcp_servers/data_server/server.py
    uv run python mcp_servers/data_server/server.py --llm off --timeout 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Пакетный контекст: при запуске файлом (``python mcp_servers/data_server/server.py``)
# корень дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[2]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from mcp_servers.data_server import (  # noqa: E402
    aggregate,
    dates,
    keywords,
    llm_client,
    summarize,
)
from mcp_servers.data_server.config import (  # noqa: E402
    LLM_TIMEOUT,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_VERSION,
)

server = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
)

# Регистрация инструментов: имя берётся из имени функции, схемы — из аннотаций, а
# докстринг становится описанием. Поэтому функций с нужными именами ровно четыре.
server.tool()(summarize.summarize)
server.tool()(keywords.extract_keywords)
server.tool()(dates.filter_by_date)
server.tool()(aggregate.aggregate)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки сервера (основной транспорт — stdio)."""
    parser = argparse.ArgumentParser(
        prog="server.py",
        description=(
            "MCP-сервер обработки данных дня 20: инструменты summarize (сводка "
            "списка элементов моделью DeepSeek, а без ключа — агрегацией), "
            "extract_keywords (ключевые слова по частоте), filter_by_date (отбор "
            "записей по дате) и aggregate (группировка и метрика)."
        ),
        epilog=(
            "Транспорт — stdio: сервер читает JSON-RPC со stdin и пишет ответы в "
            "stdout. Запускать вручную нужно для отладки; в приложении дня его "
            "поднимает MCP-клиент дочерним процессом:\n"
            "  uv run python mcp_servers/data_server/server.py --llm off\n"
            "Без ключа DeepSeek (и с --llm off) инструмент summarize всё равно "
            "работает: сводку собирает агрегация по заголовкам элементов."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--llm", choices=("auto", "off"), default="auto",
        help=(
            "использовать ли DeepSeek в инструменте summarize: auto — если найден "
            "ключ, off — всегда агрегация (демо и тесты идут без сети)"
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=LLM_TIMEOUT,
        help=f"таймаут вызова DeepSeek, с (по умолчанию {LLM_TIMEOUT:g})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Настраивает режим LLM и запускает сервер по stdio."""
    args = parse_args(argv)
    llm_client.configure(enabled=args.llm != "off", timeout=args.timeout)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
