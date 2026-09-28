"""HTTP-часть MCP-сервера дня 17: клиент jsonplaceholder.typicode.com.

Единственное место, где сервер ходит в сеть. Снаружи видны три метода —
``get_user``, ``get_post``, ``list_user_posts``, — и они возвращают ровно те
словари, что описаны в ``mcp_server/schemas.py`` (из них SDK собирает
``structuredContent`` ответа инструмента).

Ошибка внешнего API — это ``ExternalAPIError`` с текстом для человека: модель
получает его как результат инструмента с ``isError``, поэтому 404 обязан
объяснять («у jsonplaceholder 10 пользователей, id от 1 до 10»), а не отдавать
трассировку ``httpx``. Сетевые сбои и прочие не-2xx сворачиваются в одну строку
«внешний API недоступен» — по ней сразу видно, что дело не в аргументах.

Клиент настраивается через ``configure()`` (аргументы командной строки сервера)
и живёт в модуле один на процесс: ``get_client()`` создаёт его лениво, поэтому
инструменты не заводят соединение на каждый вызов.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

from mcp_server.config import (
    DEFAULT_API_BASE,
    DEFAULT_TIMEOUT,
    MAX_POSTS_LIMIT,
    MAX_USER_ID,
    SEARCH_API_ROWS,
)
from mcp_server.schemas import PostInfo, PostSummary, UserInfo, UserPosts


class ExternalAPIError(RuntimeError):
    """Ошибка внешнего API с текстом, пригодным для показа модели и человеку."""


class JsonPlaceholderClient:
    """Чтение jsonplaceholder: пользователь, пост и посты пользователя."""

    def __init__(self, base_url: str = DEFAULT_API_BASE,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self._base_url = (base_url or DEFAULT_API_BASE).rstrip("/")
        self._timeout = float(timeout)

    @property
    def base_url(self) -> str:
        """Адрес внешнего API (нужен скриптам и отчёту)."""
        return self._base_url

    def get_user(self, user_id: int) -> UserInfo:
        """Пользователь по id: имя, контакты, город и компания."""
        payload = self._get(f"/users/{int(user_id)}", not_found=(
            f"Пользователь с id={user_id} не найден (HTTP 404): у jsonplaceholder "
            f"{MAX_USER_ID} пользователей, id от 1 до {MAX_USER_ID}."
        ))
        address = payload.get("address") or {}
        company = payload.get("company") or {}
        return UserInfo(
            id=int(payload.get("id", user_id)),
            name=str(payload.get("name", "")),
            username=str(payload.get("username", "")),
            email=str(payload.get("email", "")),
            city=str(address.get("city", "")),
            phone=str(payload.get("phone", "")),
            website=str(payload.get("website", "")),
            company=str(company.get("name", "")),
        )

    def get_post(self, post_id: int) -> PostInfo:
        """Пост по id: автор, заголовок и текст."""
        payload = self._get(f"/posts/{int(post_id)}", not_found=(
            f"Пост с id={post_id} не найден (HTTP 404): у jsonplaceholder "
            "100 постов, id от 1 до 100."
        ))
        return PostInfo(
            id=int(payload.get("id", post_id)),
            user_id=int(payload.get("userId", 0)),
            title=str(payload.get("title", "")),
            body=str(payload.get("body", "")),
        )

    def list_user_posts(self, user_id: int, limit: int = 5) -> UserPosts:
        """Посты пользователя: ``limit`` ограничивает ответ (1..MAX_POSTS_LIMIT)."""
        if not 1 <= int(limit) <= MAX_POSTS_LIMIT:
            raise ExternalAPIError(
                f"limit должен быть от 1 до {MAX_POSTS_LIMIT}, получено {limit}"
            )
        payload = self._get("/posts", params={"userId": int(user_id), "_limit": int(limit)})
        posts = [
            PostSummary(id=int(item.get("id", 0)), title=str(item.get("title", "")))
            for item in payload if isinstance(item, dict)
        ]
        return UserPosts(user_id=int(user_id), count=len(posts), posts=posts)

    def list_posts(self, limit: int = SEARCH_API_ROWS) -> List[Dict[str, Any]]:
        """Страница постов jsonplaceholder (день 19): сырые записи для поиска.

        Возвращаются записи как есть (``id``, ``userId``, ``title``, ``body``):
        поиск (``mcp_server/search_sources.py``) сам решает, что из них взять в
        заголовок, а что в содержимое.
        """
        return self._page("/posts", limit)

    def list_users(self, limit: int = SEARCH_API_ROWS) -> List[Dict[str, Any]]:
        """Страница пользователей jsonplaceholder (день 19): сырые записи для поиска."""
        return self._page("/users", limit)

    def _page(self, path: str, limit: int) -> List[Dict[str, Any]]:
        """Читает страницу ленты (``_limit`` записей) и отдаёт только словари."""
        payload = self._get(path, params={"_limit": max(1, int(limit))})
        if not isinstance(payload, list):
            raise ExternalAPIError(f"Внешний API {self._base_url} вернул не список: {path}")
        return [item for item in payload if isinstance(item, dict)]

    def _get(self, path: str, *, params: dict[str, Any] | None = None,
             not_found: str = "") -> Any:
        """GET внешнего API: JSON на 2xx, ``ExternalAPIError`` на всё остальное.

        ``not_found`` — текст 404 для конкретной ручки (у неё понятнее, что именно
        не нашлось); общий текст используется там, где уточнять нечего.
        """
        url = f"{self._base_url}{path}"
        try:
            response = httpx.get(url, params=params, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise ExternalAPIError(
                f"Внешний API {self._base_url} недоступен: {exc}"
            ) from exc
        if response.status_code == 404:
            raise ExternalAPIError(
                not_found or f"Внешний API {self._base_url} не нашёл {path} (HTTP 404)"
            )
        if response.status_code >= 400:
            raise ExternalAPIError(
                f"Внешний API {self._base_url} ответил ошибкой "
                f"HTTP {response.status_code}: {path}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalAPIError(
                f"Внешний API {self._base_url} вернул не JSON: {path}"
            ) from exc


_client: JsonPlaceholderClient | None = None


def configure(base_url: str | None = None,
              timeout: float | None = None) -> JsonPlaceholderClient:
    """Настраивает клиент процесса (аргументы командной строки сервера)."""
    global _client
    _client = JsonPlaceholderClient(
        base_url or DEFAULT_API_BASE,
        DEFAULT_TIMEOUT if timeout is None else timeout,
    )
    return _client


def get_client() -> JsonPlaceholderClient:
    """Клиент процесса; создаётся при первом обращении с настройками по умолчанию."""
    global _client
    if _client is None:
        _client = JsonPlaceholderClient()
    return _client
