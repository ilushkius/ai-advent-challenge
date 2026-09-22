"""Ошибки MCP-клиента и понятные тексты (день 17).

Отдельный модуль, потому что тексты ошибок — это контракт с пользователем:
одну и ту же строку показывают Streamlit (красная плашка), API (``detail`` при
400/409/502) и консольные скрипты. Исключениями приходят только отказы
транспорта — нет соединения (``MCPNotConnectedError``), сбой связи
(``MCPConnectionError``), ошибка каталога (``MCPToolsError``) и ошибка вызова
(``MCPCallError``); ошибка самого инструмента — это данные ответа
(``MCPToolResult.is_error``), и она пользователю показывается текстом
инструмента, а не исключением.

Здесь же лежит разворачивание ``ExceptionGroup``: транспорты MCP SDK запускают
сервер в task-group anyio, поэтому ``FileNotFoundError`` (команды нет в PATH) и
таймаут приходят завёрнутыми, а показать пользователю нужно причину, а не обёртку.

Модуль не импортирует SDK: классы исключений и форматирование текста тестируются
без сети и без процессов.
"""
from __future__ import annotations

import asyncio

from ..domain.mcp_target import MCPTarget, MCPTransport


class MCPError(Exception):
    """Общая ошибка MCP-клиента; текст пригоден для показа в UI и в ответе API."""


class MCPConnectionError(MCPError):
    """Соединение не установлено: сервер недоступен, команда не найдена, таймаут."""


class MCPNotConnectedError(MCPError):
    """Обращение к серверу без соединения (список инструментов недоступен)."""


class MCPToolsError(MCPError):
    """Соединение есть, но список инструментов получить не удалось."""


class MCPCallError(MCPError):
    """Соединение есть, но вызвать инструмент не удалось (обрыв, таймаут, сбой)."""


#: Первая часть сообщения об ошибке: что именно делал клиент.
ACTION_LABELS = {
    "connect": "Не удалось подключиться к MCP-серверу",
    "tools": "Не удалось получить список инструментов MCP-сервера",
    "call": "Не удалось вызвать инструмент MCP-сервера",
    "serve": "Соединение с MCP-сервером оборвалось",
}


def leaf_errors(exc: BaseException | None) -> list[BaseException]:
    """Разворачивает ``ExceptionGroup`` транспорта до конкретных ошибок."""
    if exc is None:
        return [RuntimeError("соединение с MCP-сервером потеряно")]
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(leaf_errors(sub))
        return leaves or [exc]
    return [exc]


def error_message(
    exc: BaseException | None,
    target: MCPTarget,
    timeout: float,
    action: str = "connect",
) -> str:
    """Понятный текст ошибки: что делали, что случилось и что проверить.

    Подсказки добавляются по конкретной причине: нет команды — про PATH, таймаут —
    про время ожидания, HTTP-транспорт — про URL. Так пользователь без чтения
    traceback понимает, что исправить.
    """
    leaves = leaf_errors(exc)
    detail = str(leaves[0]).strip() or type(leaves[0]).__name__
    hints: list[str] = []
    if any(isinstance(item, FileNotFoundError) for item in leaves):
        hints.append(
            f"команда {target.command!r} не найдена — проверьте, что она установлена "
            "и есть в PATH (npx или uvx)"
        )
    if any(isinstance(item, (asyncio.TimeoutError, TimeoutError)) for item in leaves):
        hints.append(f"истёк таймаут {timeout:.0f} с — сервер не ответил")
    if target.transport in (MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP):
        hints.append("проверьте URL и что сервер поднят")
    message = (
        f"{ACTION_LABELS.get(action, ACTION_LABELS['connect'])} "
        f"[{target.transport.label}] {target.label()}: {detail}"
    )
    return f"{message} ({'; '.join(hints)})" if hints else message
