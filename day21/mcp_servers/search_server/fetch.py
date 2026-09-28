"""Инструмент ``fetch_url`` сервера поиска (день 20): страница по HTTP → текст.

Читается только ``http://`` и ``https://`` (``file://`` и прочие схемы отвергаются
до запроса — инструмент не должен открывать локальные файлы). Ответ отдаётся
текстом: HTML очищается от ``<script>``/``<style>``, комментариев и тегов, затем
раскодировываются HTML-сущности; прочие типы содержимого отдаются как есть.

Текст обрезается до ``max_chars`` (границы ``200..20000``) с признаком
``truncated``: страница целиком модели не нужна, а «сколько было» видно по флагу.
Подменённый HTTP-клиент задаётся ``configure(http_client=...)`` — тесты берут
страницу у локального стенда и в сеть не ходят.
"""
from __future__ import annotations

import html
import re
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.search_server import config
from mcp_servers.search_server.schemas import FetchUrlResult

#: Схемы, которые инструмент готов читать.
ALLOWED_SCHEMES = ("http://", "https://")

#: Блоки script/style и комментарии удаляются ЦЕЛИКОМ: их содержимое — не текст
#: страницы, и модель не должна принимать код за данные.
_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_TAG = re.compile(r"(?s)<[^>]*>")

#: Настройки процесса: таймаут и подменённый HTTP-клиент.
_timeout: float = config.DEFAULT_TIMEOUT
_http_client: Any = None


def configure(timeout: float | None = None, http_client: Any = None) -> None:
    """Задаёт таймаут запроса и HTTP-клиент (аргументы сервера и тесты)."""
    global _timeout, _http_client
    if timeout is not None:
        _timeout = float(timeout)
    if http_client is not None:
        _http_client = http_client


def fetch_url(url: str, max_chars: int = config.FETCH_MAX_CHARS_DEFAULT) -> FetchUrlResult:
    """Читает страницу по адресу http:// или https:// и возвращает её текст.

    Параметры: url — адрес страницы, начинающийся с ``http://`` или ``https://``;
    max_chars — до скольких символов обрезать текст (200..20000, по умолчанию
    4000; флаг ``truncated`` в ответе говорит, что текст был длиннее).

    Возвращает объект с полями url, status (код ответа), content_type, chars
    (длина текста после обрезки), truncated и text — текстом страницы без тегов.
    Пример: fetch_url(url="https://example.com", max_chars=2000).

    Если схема не http(s), сервер ответил не-2xx или запрос не прошёл, инструмент
    сообщает об ошибке с причиной.
    """
    target = (url or "").strip()
    if not target.startswith(ALLOWED_SCHEMES):
        raise ToolError(f"URL «{url}» должен начинаться с http:// или https://")
    size = clamp_max_chars(max_chars)
    response = _request(target)
    status = int(getattr(response, "status_code", 200) or 200)
    if not 200 <= status < 300:
        raise ToolError(f"URL {target} ответил кодом {status}")
    content_type = _content_type(response)
    raw = _body(response)
    cleaned = html_to_text(raw) if "html" in content_type.lower() else raw.strip()
    truncated = len(cleaned) > size
    text = cleaned[:size]
    return FetchUrlResult(
        url=target,
        status=status,
        content_type=content_type,
        chars=len(text),
        truncated=truncated,
        text=text,
    )


def clamp_max_chars(max_chars: Any) -> int:
    """Приводит ``max_chars`` к целому в границах ``200..20000``."""
    try:
        value = int(max_chars)
    except (TypeError, ValueError):
        raise ToolError(f"max_chars должен быть целым числом, получено {max_chars!r}")
    return max(config.FETCH_MAX_CHARS_MIN, min(value, config.FETCH_MAX_CHARS_MAX))


def html_to_text(raw: str) -> str:
    """HTML → текст: без script/style, комментариев и тегов, без лишних пустых строк."""
    text = _SCRIPT_STYLE.sub(" ", raw)
    text = _COMMENT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _request(url: str):
    """Выполняет GET подменённым клиентом или httpx; сбой — ошибка инструмента."""
    client = _http_client
    try:
        if client is not None:
            return client.get(url, follow_redirects=True)
        return httpx.get(url, timeout=_timeout, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001 — сетевой сбой объясняем одной строкой
        raise ToolError(f"Не удалось запросить {url}: {exc}") from exc


def _content_type(response) -> str:
    """Тип содержимого из заголовков ответа (пустая строка, если заголовка нет)."""
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("content-type", "")
    except Exception:  # noqa: BLE001 — заголовки фейка могут быть любыми
        value = ""
    return str(value or "")


def _body(response) -> str:
    """Тело ответа строкой: ``text`` httpx или раскодированные байты."""
    text = getattr(response, "text", None)
    if text is not None:
        return str(text)
    content = getattr(response, "content", b"")
    if isinstance(content, (bytes, bytearray)):
        return bytes(content).decode("utf-8", "replace")
    return str(content)
