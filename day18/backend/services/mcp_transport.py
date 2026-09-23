"""Адаптеры MCP SDK: транспорт и разбор его объектов (день 17).

Граница между кодом дня и SDK лежит здесь: ``MCPClient`` остаётся протоколом и
жизненным циклом, а всё, что зависит от конкретных классов ``mcp``, собрано в этом
модуле. Так у клиента один предмет — «соединение, каталог и вызов», а не «ещё и
знание о том, как SDK называет поля результата».

Три функции:

- ``transport_context(target)`` — асинхронный контекст транспорта по разобранной
  цели: stdio запускает сервер дочерним процессом, SSE и Streamable HTTP работают
  по URL;
- ``server_info(init)`` — имя, версия и протокол сервера из ``InitializeResult``
  (словарь с пустыми строками, если сервер их не прислал);
- ``raw_parts(raw)`` — структура, текст и признак ошибки из ``CallToolResult``:
  ``structured_content`` есть не у всякого сервера, поэтому текст возвращается
  всегда.

Модуль не знает ни про HttpClient дня, ни про БД, ни про Streamlit.
"""
from __future__ import annotations

from typing import Any, AsyncContextManager

from mcp import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from ..domain.mcp_target import MCPTarget, MCPTransport


def transport_context(target: MCPTarget) -> AsyncContextManager[Any]:
    """Контекст транспорта: stdio (дочерний процесс), SSE или Streamable HTTP."""
    if target.transport is MCPTransport.STDIO:
        params = StdioServerParameters(command=target.command, args=list(target.args))
        return stdio_client(params)
    if target.transport is MCPTransport.SSE:
        return sse_client(target.url)
    return streamable_http_client(target.url)


def server_info(init: Any) -> dict[str, str]:
    """Имя, версия и протокол сервера из ``InitializeResult`` (пусто — не прислал)."""
    info = getattr(init, "server_info", None)
    return {
        "name": getattr(info, "name", "") or "",
        "version": getattr(info, "version", "") or "",
        "protocol": getattr(init, "protocol_version", "") or "",
    }


def raw_parts(raw: Any) -> tuple[Any, str, bool]:
    """Разбирает ``CallToolResult``: структура, текст и признак ошибки.

    ``structured_content`` есть не у всякого сервера (инструмент без
    ``outputSchema`` отвечает только текстом), поэтому текст тоже возвращается: он
    попадает и в промпт, и в сообщение об ошибке инструмента.
    """
    structured = getattr(raw, "structured_content", None)
    blocks = getattr(raw, "content", None) or []
    text = "\n".join(
        item for item in (getattr(block, "text", None) for block in blocks) if item
    )
    return structured, text, bool(getattr(raw, "is_error", False))
