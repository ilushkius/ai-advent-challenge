"""Разбор цели MCP-подключения (день 16): URL сервера или команда запуска.

Транспорт выбирается по виду строки (``transport="auto"``) либо задаётся явно:

- ``http://...`` / ``https://...`` — Streamable HTTP, современный транспорт MCP
  (один POST-эндпоинт, ответ — SSЕ-поток того же соединения);
- ``sse://host:port/sse`` — SSE, ранний транспорт MCP; схема ``sse://``
  переводится в ``http://``, потому что SSE-эндпоинт — обычный HTTP-ресурс;
- ``stdio: <команда>`` — сервер запускается дочерним процессом, обмен по stdin
  и stdout (транспорт stdio);
- любая другая строка — тоже stdio: ``npx -y @modelcontextprotocol/server-filesystem .``.

Разбор команды не зависит от платформы: ``shlex.split(..., posix=False)``
сохраняет обратные слэши Windows-путей (при ``posix=True`` они были бы съедены),
а кавычки снимаются отдельно, поэтому ``npx -y pkg "C:\\temp\\dir"`` даёт ровно
три аргумента. Модуль чистый: ни MCP SDK, ни HTTP здесь нет.
"""
from __future__ import annotations

import enum
import shlex
from dataclasses import dataclass


class MCPTransport(enum.Enum):
    """Транспорт MCP-подключения; ``AUTO`` — выбор по виду цели."""

    AUTO = "auto"
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "http"

    @property
    def label(self) -> str:
        """Человекочитаемое имя транспорта для UI, лога и отчёта."""
        return _TRANSPORT_LABELS[self]


_TRANSPORT_LABELS = {
    MCPTransport.AUTO: "авто",
    MCPTransport.STDIO: "stdio (дочерний процесс)",
    MCPTransport.SSE: "SSE (HTTP)",
    MCPTransport.STREAMABLE_HTTP: "Streamable HTTP",
}

HTTP_PREFIXES = ("http://", "https://")
SSE_PREFIX = "sse://"
STDIO_PREFIX = "stdio:"


class MCPTargetError(ValueError):
    """Цель подключения не разобрана (пустая строка, неизвестный транспорт)."""


@dataclass(frozen=True, slots=True)
class MCPTarget:
    """Разобранная цель: транспорт плюс URL либо команда с аргументами."""

    raw: str
    transport: MCPTransport
    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()

    def label(self) -> str:
        """Строка цели для статуса и лога: URL либо команда с аргументами."""
        if self.url:
            return self.url
        return " ".join((self.command, *self.args)).strip()


def split_command(command_line: str) -> tuple[str, tuple[str, ...]]:
    """``'npx -y pkg "C:\\dir"'`` → ``('npx', ('-y', 'pkg', 'C:\\dir'))``."""
    text = command_line.strip()
    if not text:
        raise MCPTargetError("Пустая команда запуска MCP-сервера")
    try:
        parts = shlex.split(text, posix=False)
    except ValueError as exc:
        raise MCPTargetError(f"Не удалось разобрать команду запуска: {exc}") from exc
    cleaned = [token for token in (_strip_quotes(part) for part in parts) if token]
    if not cleaned:
        raise MCPTargetError(f"В команде запуска нет исполняемого файла: {command_line!r}")
    return cleaned[0], tuple(cleaned[1:])


def detect_transport(raw: str) -> MCPTransport:
    """Транспорт по виду строки: URL → HTTP/SSE, всё остальное → stdio."""
    text = raw.strip()
    if text.startswith(SSE_PREFIX):
        return MCPTransport.SSE
    if text.startswith(HTTP_PREFIXES):
        return MCPTransport.STREAMABLE_HTTP
    return MCPTransport.STDIO


def parse_transport(value: MCPTransport | str) -> MCPTransport:
    """Приводит значение из API/UI к ``MCPTransport`` (неизвестное — ошибка)."""
    if isinstance(value, MCPTransport):
        return value
    try:
        return MCPTransport(str(value).strip().lower())
    except ValueError:
        known = ", ".join(item.value for item in MCPTransport)
        raise MCPTargetError(f"Неизвестный транспорт {value!r}; допустимы: {known}") from None


def parse_target(raw: str, transport: MCPTransport | str = MCPTransport.AUTO) -> MCPTarget:
    """Разбирает цель подключения: ``MCPTarget`` либо ``MCPTargetError``.

    Явно заданный транспорт сильнее автоопределения: пользователь мог поставить
    SSE-эндпоинт на нестандартный путь, который по виду строки не отличить от
    Streamable HTTP.
    """
    text = (raw or "").strip()
    if not text:
        raise MCPTargetError("Пустая цель подключения: укажите URL MCP-сервера или команду запуска")
    chosen = parse_transport(transport)
    if chosen is MCPTransport.AUTO:
        chosen = detect_transport(text)
    if chosen in (MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP):
        return _parse_url_target(text, chosen)
    if text.startswith(HTTP_PREFIXES):
        raise MCPTargetError(
            f"Транспорт {chosen.label} требует команду запуска сервера, "
            f"а не URL: {text!r}"
        )
    return _parse_stdio_target(text)


def _parse_url_target(text: str, transport: MCPTransport) -> MCPTarget:
    """Цель-URL: у SSE схема ``sse://`` переводится в ``http://``."""
    url = text
    if transport is MCPTransport.SSE and text.startswith(SSE_PREFIX):
        url = "http://" + text[len(SSE_PREFIX):]
    if not url.startswith(HTTP_PREFIXES):
        raise MCPTargetError(
            f"Транспорт {transport.label} требует URL http:// или https://, а не {text!r}"
        )
    if not url.split("://", 1)[-1].strip("/"):
        raise MCPTargetError(f"В цели {text!r} нет адреса сервера")
    return MCPTarget(raw=text, transport=transport, url=url)


def _parse_stdio_target(text: str) -> MCPTarget:
    """Цель-stdio: команда запуска (префикс ``stdio:`` необязателен)."""
    body = text[len(STDIO_PREFIX):].strip() if text.startswith(STDIO_PREFIX) else text
    command, args = split_command(body)
    return MCPTarget(raw=text, transport=MCPTransport.STDIO, command=command, args=args)


def _strip_quotes(token: str) -> str:
    """Снимает парные кавычки, оставленные ``shlex`` в режиме ``posix=False``."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token
