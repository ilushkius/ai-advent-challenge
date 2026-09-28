"""Инструмент ``search_web`` сервера поиска (день 20): лента API и Википедия.

Лента проверяется на локальном стенде (``stub_api_base``) — HTTP-запросы и разбор
ответов настоящие, а сети нет. Википедия проверяется на подменённом HTTP-клиенте
(``configure(http_client=...)``): её ответ — ``[запрос, заголовки, описания,
адреса]``, и такая форма стендом не эмулируется. Ошибки инструмента проверяются
как ``ToolError``: клиент отдаёт их модели текстом, а не трассировкой.
"""
from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.search_server import config, web

#: Ответ opensearch русской Википедии: запрос, заголовки, описания, адреса.
WIKI_PAYLOAD = [
    "RAG",
    ["RAG — Википедия", "Retrieval-augmented generation"],
    ["подход к генерации с опорой на найденное", "второе описание"],
    ["https://ru.wikipedia.org/wiki/RAG", "https://ru.wikipedia.org/wiki/Retrieval"],
]


class FakeResponse:
    """Ответ подменённого HTTP-клиента: код и разобранный JSON."""

    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        """Отдаёт заранее заданное тело ответа."""
        return self.payload


class FakeHttpClient:
    """Подменённый HTTP-клиент: помнит вызовы и отвечает заданным телом."""

    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **params) -> FakeResponse:
        """Записывает вызов и возвращает заданный ответ (в сеть не ходит)."""
        self.calls.append((url, params))
        return FakeResponse(self.payload, self.status_code)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """Снимок настроек модуля: ``configure`` внутри теста не течёт в соседние тесты."""
    for name in ("_api_base", "_wiki_base", "_timeout", "_http_client"):
        monkeypatch.setattr(web, name, getattr(web, name))
    return web


def test_posts_search_filters_page_by_query(stub_api_base):
    """Пост ленты: ``post:<id>``, тело, адрес и автор в метаданных, фильтр по запросу."""
    web.configure(api_base=stub_api_base)
    result = web.search_web("Post 4", source="posts", limit=5)

    assert result["query"] == "Post 4"
    assert result["source"] == "posts" and result["source_kind"] == "api"
    # «Post 4» подходит и к постам 40..49: фильтр идёт по странице, лимит — после него.
    assert result["count"] == 5
    assert [item["id"] for item in result["items"]] == [
        "post:4", "post:40", "post:41", "post:42", "post:43",
    ]
    first = result["items"][0]
    assert first["title"] == "Post 4"
    assert first["content"] == "Body of post 4"
    assert first["url"] == f"{stub_api_base}/posts/4"
    assert first["metadata"] == {"source": "posts", "user_id": "1"}


def test_filter_is_case_insensitive(stub_api_base):
    """Запрос ищется подстрокой без учёта регистра."""
    web.configure(api_base=stub_api_base)
    result = web.search_web("bOdY Of PoSt 73", source="posts", limit=5)
    assert [item["id"] for item in result["items"]] == ["post:73"]


def test_empty_query_returns_first_rows(stub_api_base):
    """Пустой запрос — первые записи страницы, а не пустой результат."""
    web.configure(api_base=stub_api_base)
    result = web.search_web("", source="posts", limit=3)
    assert result["count"] == 3
    assert [item["id"] for item in result["items"]] == ["post:1", "post:2", "post:3"]


def test_limit_is_clamped_to_max_items(stub_api_base):
    """Слишком большой ``limit`` зажимается до ``MAX_ITEMS``, а не игнорируется."""
    web.configure(api_base=stub_api_base)
    result = web.search_web("", source="posts", limit=999)
    assert result["count"] == config.MAX_ITEMS


def test_users_source_searches_contacts(stub_api_base):
    """Пользователь ленты: ``user:<id>``, контакты в содержимом, фильтр по e-mail."""
    web.configure(api_base=stub_api_base)
    result = web.search_web("user7@example.com", source="users", limit=5)

    assert result["source_kind"] == "api" and result["count"] == 1
    item = result["items"][0]
    assert item["id"] == "user:7"
    assert item["title"] == "Leanne Graham 7"
    assert "user7@example.com" in item["content"] and "City 7" in item["content"]
    assert item["url"] == f"{stub_api_base}/users/7"
    assert item["metadata"] == {"source": "users", "username": "user7"}


def test_unknown_source_is_a_tool_error():
    """Неизвестный источник — ``ToolError`` с перечнем допустимых."""
    with pytest.raises(ToolError) as exc:
        web.search_web("RAG", source="telepathy")
    assert "не поддержан" in str(exc.value)
    assert "posts" in str(exc.value) and "wikipedia" in str(exc.value)


def test_bad_limit_is_a_tool_error():
    """Нецелый ``limit`` — ошибка инструмента, а не трассировка ``int()``."""
    with pytest.raises(ToolError) as exc:
        web.search_web("RAG", source="posts", limit="много")
    assert "limit" in str(exc.value)


def test_unreachable_api_is_reported():
    """Недоступный внешний API — ``ToolError`` с причиной, а не исключение httpx."""
    web.configure(api_base="http://127.0.0.1:1", timeout=1.0)
    with pytest.raises(ToolError) as exc:
        web.search_web("RAG", source="posts", limit=5)
    assert "недоступен" in str(exc.value)


def test_bad_status_is_reported():
    """Ответ не-2xx от ленты — ``ToolError`` с кодом в тексте."""
    fake = FakeHttpClient({"error": "boom"}, status_code=500)
    web.configure(api_base="http://api.local", http_client=fake)
    with pytest.raises(ToolError) as exc:
        web.search_web("RAG", source="posts", limit=5)
    assert "недоступен" in str(exc.value) and "500" in str(exc.value)
    assert fake.calls[0][0] == "http://api.local/posts"


def test_wikipedia_uses_opensearch_parameters():
    """Википедия: запрос уходит с ``action=opensearch``, элементы берутся из ответа."""
    fake = FakeHttpClient(WIKI_PAYLOAD)
    web.configure(wiki_base="http://wiki.local/w/api.php", http_client=fake)
    result = web.search_web("RAG", source="wikipedia", limit=5)

    url, params = fake.calls[0]
    assert url == "http://wiki.local/w/api.php"
    assert params["params"] == {
        "action": "opensearch", "search": "RAG", "limit": 5, "format": "json",
    }
    assert result["source"] == "wikipedia" and result["source_kind"] == "wiki"
    assert result["count"] == 2
    first = result["items"][0]
    assert first["id"] == "wiki:0"
    assert first["title"] == "RAG — Википедия"
    assert first["content"] == "подход к генерации с опорой на найденное"
    assert first["url"] == "https://ru.wikipedia.org/wiki/RAG"
    assert first["metadata"] == {"source": "wikipedia"}


def test_wikipedia_respects_limit():
    """``limit`` отсекает статьи Википедии, а не только ленты."""
    fake = FakeHttpClient(WIKI_PAYLOAD)
    web.configure(wiki_base="http://wiki.local/w/api.php", http_client=fake)
    result = web.search_web("RAG", source="wikipedia", limit=1)
    assert result["count"] == 1
    assert [item["id"] for item in result["items"]] == ["wiki:0"]


def test_wikipedia_bad_payload_is_reported():
    """Ответ не формы opensearch — ``ToolError``: распарсить его нечем."""
    fake = FakeHttpClient({"error": "unavailable"})
    web.configure(wiki_base="http://wiki.local/w/api.php", http_client=fake)
    with pytest.raises(ToolError) as exc:
        web.search_web("RAG", source="wikipedia", limit=5)
    assert "недоступен" in str(exc.value)
