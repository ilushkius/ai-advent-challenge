"""Инструмент ``search_web`` сервера поиска (день 20): лента API и Википедия.

Два внешних источника читаются по HTTP:

- ``source=posts`` / ``source=users`` — лента jsonplaceholder (``--api-base``):
  читается страница ``/posts?_limit=100`` или ``/users?_limit=100``, запрос ищется
  подстрокой без учёта регистра в заголовке и тексте записи, ``limit`` отсекает
  выдачу уже после фильтра;
- ``source=wikipedia`` — API opensearch русской Википедии (``--wiki-base``):
  возвращает ``[запрос, заголовки, описания, адреса]``, из которых собираются
  элементы статей.

Сеть можно подменить: ``configure(http_client=...)`` принимает любой объект с
методом ``get(url, params=...)`` (тесты подставляют фейк и не ходят в интернет).

Ошибка инструмента — ``ToolError`` с текстом для модели: клиент превращает его в
результат ``isError``, поэтому причина («источник не поддержан», «внешний API
недоступен») доходит до модели, а не теряется в трассировке ``httpx``.
"""
from __future__ import annotations

from typing import Any, List

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.search_server import config
from mcp_servers.search_server.schemas import SearchItem, WebSearchResult

#: Виды лент внешнего API: источник → путь ручки.
FEED_SOURCES = ("posts", "users")

#: Вид источника для ответа: лента внешнего API или Википедия.
SOURCE_KIND_API = "api"
SOURCE_KIND_WIKI = "wiki"

#: Настройки процесса: адреса источников, таймаут и подменённый HTTP-клиент.
_api_base: str = config.DEFAULT_API_BASE
_wiki_base: str = config.WIKI_API_BASE
_timeout: float = config.DEFAULT_TIMEOUT
_http_client: Any = None


def configure(api_base: str | None = None, wiki_base: str | None = None,
              timeout: float | None = None, http_client: Any = None) -> None:
    """Задаёт адреса источников, таймаут и HTTP-клиент (аргументы сервера и тесты)."""
    global _api_base, _wiki_base, _timeout, _http_client
    if api_base is not None:
        _api_base = str(api_base).rstrip("/")
    if wiki_base is not None:
        _wiki_base = str(wiki_base)
    if timeout is not None:
        _timeout = float(timeout)
    if http_client is not None:
        _http_client = http_client


def search_web(query: str, source: str = "posts", limit: int = 5) -> WebSearchResult:
    """Ищет данные в ленте внешнего API или в Википедии.

    Параметры: query — что искать (подстрока без учёта регистра; пустая строка —
    первые записи источника); source — где искать: ``posts`` (посты
    jsonplaceholder, по умолчанию), ``users`` (пользователи jsonplaceholder) или
    ``wikipedia`` (статьи русской Википедии по названию); limit — сколько
    элементов вернуть (1..20, по умолчанию 5).

    Возвращает объект с полями query, source, source_kind (``api`` для ленты,
    ``wiki`` для Википедии), count и items — массив найденного (id, title,
    content, url, metadata). Пример: search_web(query="RAG", source="posts",
    limit=5).

    Если источник не поддержан или внешний API не ответил, инструмент сообщает об
    ошибке с причиной.
    """
    kind = (source or "").strip().lower()
    size = clamp_limit(limit)
    if kind in FEED_SOURCES:
        items = _search_feed(query, kind, size)
        return WebSearchResult(query=query, source=kind, source_kind=SOURCE_KIND_API,
                               count=len(items), items=items)
    if kind == "wikipedia":
        items = _search_wiki(query, size)
        return WebSearchResult(query=query, source="wikipedia",
                               source_kind=SOURCE_KIND_WIKI, count=len(items),
                               items=items)
    raise ToolError(
        f"Источник «{source}» не поддержан. Допустимы: posts, users, wikipedia"
    )


def clamp_limit(limit: Any) -> int:
    """Приводит ``limit`` к целому в границах ``1..MAX_ITEMS``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise ToolError(f"limit должен быть целым числом, получено {limit!r}")
    return max(1, min(value, config.MAX_ITEMS))


# ---------- лента внешнего API ----------
def _search_feed(query: str, source: str, limit: int) -> List[SearchItem]:
    """Читает страницу ленты и фильтрует записи подстрокой запроса."""
    url = f"{_api_base}/{source}"
    payload = _fetch_json(url, {"_limit": config.MAX_PAGE_ROWS})
    if not isinstance(payload, list):
        raise ToolError(f"Внешний API «{url}» недоступен: ожидался список записей")
    needle = (query or "").strip().lower()
    items: List[SearchItem] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        if needle and needle not in _haystack(row, source):
            continue
        items.append(_feed_item(row, source))
        if len(items) >= limit:
            break
    return items


def _haystack(row: dict, source: str) -> str:
    """Текст записи, по которому идёт фильтр: заголовок и тело (или контакты)."""
    fields = ("title", "body") if source == "posts" else ("name", "username", "email")
    return " ".join(str(row.get(field, "")) for field in fields).lower()


def _feed_item(row: dict, source: str) -> SearchItem:
    """Запись ленты → элемент результата (пост или пользователь)."""
    row_id = int(row.get("id", 0) or 0)
    if source == "posts":
        return SearchItem(
            id=f"post:{row_id}",
            title=str(row.get("title", ""))[:config.TITLE_MAX],
            content=str(row.get("body", ""))[:config.CONTENT_MAX],
            url=f"{_api_base}/posts/{row_id}",
            metadata={"source": "posts", "user_id": str(row.get("userId", 0) or 0)},
        )
    address = row.get("address") or {}
    company = row.get("company") or {}
    content = (f"{row.get('email', '')}; {address.get('city', '')}; "
               f"{company.get('name', '')}")
    return SearchItem(
        id=f"user:{row_id}",
        title=str(row.get("name", ""))[:config.TITLE_MAX],
        content=content[:config.CONTENT_MAX],
        url=f"{_api_base}/users/{row_id}",
        metadata={"source": "users", "username": str(row.get("username", ""))},
    )


# ---------- Википедия ----------
def _search_wiki(query: str, limit: int) -> List[SearchItem]:
    """Ищет статьи через opensearch: ``[запрос, заголовки, описания, адреса]``."""
    payload = _fetch_json(_wiki_base, {
        "action": "opensearch", "search": query, "limit": limit, "format": "json",
    })
    if not isinstance(payload, list) or len(payload) < 4:
        raise ToolError(
            f"Внешний API «{_wiki_base}» недоступен: неожиданный ответ opensearch"
        )
    _, titles, descriptions, urls = payload[0], payload[1], payload[2], payload[3]
    if not all(isinstance(part, list) for part in (titles, descriptions, urls)):
        raise ToolError(
            f"Внешний API «{_wiki_base}» недоступен: неожиданный ответ opensearch"
        )
    items: List[SearchItem] = []
    for index, title in enumerate(titles[:limit]):
        description = str(descriptions[index]) if index < len(descriptions) else ""
        url = str(urls[index]) if index < len(urls) else ""
        items.append(SearchItem(
            id=f"wiki:{index}",
            title=str(title)[:config.TITLE_MAX],
            content=description[:config.CONTENT_MAX],
            url=url,
            metadata={"source": "wikipedia"},
        ))
    return items


# ---------- HTTP ----------
def _fetch_json(url: str, params: dict) -> Any:
    """Читает JSON по адресу; сбой сети, статус или разбор — ошибка инструмента."""
    response = _request(url, params)
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001 — ответ не JSON: причина едет модели
        raise ToolError(
            f"Внешний API «{url}» недоступен: ответ не разобран как JSON ({exc})"
        ) from exc


def _request(url: str, params: dict):
    """Выполняет GET подменённым клиентом или httpx и проверяет код ответа."""
    client = _http_client
    try:
        if client is not None:
            response = client.get(url, params=params)
        else:
            response = httpx.get(url, params=params, timeout=_timeout,
                                 follow_redirects=True)
    except Exception as exc:  # noqa: BLE001 — сетевой сбой объясняем одной строкой
        raise ToolError(f"Внешний API «{url}» недоступен: {exc}") from exc
    status = int(getattr(response, "status_code", 200) or 200)
    if status >= 400:
        raise ToolError(f"Внешний API «{url}» недоступен: HTTP {status}")
    return response
