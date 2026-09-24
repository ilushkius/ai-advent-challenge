"""Источник внешней ленты инструмента ``search`` (день 19): ``posts`` и ``users``.

Проверяется форма элементов ленты jsonplaceholder (``post:<id>``/``user:<id>``,
обрезанное содержимое, адрес и метаданные), фильтр по текстовым полям, порядок
«фильтр, потом ``limit``» и перевод сбоя внешнего API в понятную ошибку источника.

В сеть тесты не ходят: клиент jsonplaceholder подменяется заглушкой из
``tests/search_sources_fakes.py`` (там же материал лент). Источник-файл — в
``test_search_sources.py``, таблица SQLite — в ``test_search_sources_sqlite.py``.
"""
from __future__ import annotations

import pytest

from mcp_server import config
from mcp_server.api_client import ExternalAPIError
from mcp_server.search_sources import SearchSourceError, search_items

from search_sources_fakes import install_fake_api


@pytest.fixture
def fake_api(monkeypatch):
    """Ставит заглушку клиента jsonplaceholder вместо процесса-клиента модуля."""
    return install_fake_api(monkeypatch)


def test_api_posts_items_shape(fake_api):
    """Пост ленты: ``post:<id>``, обрезанное тело, адрес и автор в метаданных."""
    client = fake_api()

    kind, items = search_items("", "posts", 5)

    assert kind == "api"
    assert [item["id"] for item in items] == ["post:1", "post:2"]
    assert items[0]["title"] == "RAG и документы"
    assert len(items[0]["content"]) == config.SEARCH_CONTENT_MAX
    assert items[0]["url"] == "https://jsonplaceholder.test/api/posts/1"
    assert items[0]["metadata"] == {"source": "posts", "user_id": 7}
    assert client.calls == [("posts", config.SEARCH_API_ROWS)]


def test_api_users_items_shape(fake_api):
    """Пользователь ленты: ``user:<id>``, контакты с городом и компанией в содержимом."""
    client = fake_api()

    _, items = search_items("", "users", 5)

    assert [item["id"] for item in items] == ["user:1", "user:2"]
    assert items[0]["title"] == "Leanne Graham"
    assert items[0]["content"] == "bret@test.io; Gwenborough; Romaguera"
    assert items[0]["url"] == "https://jsonplaceholder.test/api/users/1"
    assert items[0]["metadata"] == {"source": "users", "username": "Bret"}
    assert client.calls == [("users", config.SEARCH_API_ROWS)]


def test_api_user_without_address_does_not_break(fake_api):
    """Запись без ``address``/``company``/``username`` читается: пустые поля, а не сбой."""
    fake_api(users=[{"id": 9, "name": "Без адреса", "email": "plain@test.io"}])

    _, items = search_items("", "users", 5)

    assert items[0]["content"] == "plain@test.io; ; "
    assert items[0]["metadata"] == {"source": "users", "username": ""}


def test_api_post_without_author_gets_zero(fake_api):
    """Запись без ``userId`` не роняет поиск: автор по умолчанию 0."""
    fake_api(posts=[{"id": 5, "title": "Без автора", "body": "текст"}])

    _, items = search_items("", "posts", 5)

    assert items[0]["metadata"] == {"source": "posts", "user_id": 0}


@pytest.mark.parametrize("source,query,expected", [
    ("posts", "flask", ["post:2"]),
    ("posts", "СЕРВЕР", ["post:2"]),
    ("posts", "квантовые вычисления", []),
    ("users", "deckow", ["user:2"]),
    ("users", "bret@test.io", ["user:1"]),
    ("users", "Gwenborough", ["user:1"]),
    ("users", "нет-такого", []),
])
def test_api_filters_page_by_query(fake_api, source, query, expected):
    """Фильтр ищет подстроку в заголовке и содержимом записи без учёта регистра."""
    fake_api()

    _, items = search_items(query, source, 5)

    assert [item["id"] for item in items] == expected


def test_api_limit_applies_after_filtering(fake_api):
    """``limit`` отсекает выдачу после фильтра: вторая подходящая запись не теряется."""
    fake_api()

    _, all_matches = search_items("flask", "posts", 5)
    _, capped = search_items("flask", "posts", 1)

    assert [item["id"] for item in all_matches] == ["post:2"]
    assert [item["id"] for item in capped] == ["post:2"]


def test_api_error_becomes_source_error(fake_api):
    """Сбой внешнего API превращается в ``SearchSourceError`` с текстом для модели."""
    fake_api(error=ExternalAPIError("Внешний API недоступен: таймаут"))

    with pytest.raises(SearchSourceError) as exc:
        search_items("", "posts", 5)

    assert "недоступен" in str(exc.value)


@pytest.mark.parametrize("source,count", [("posts", 2), ("users", 2)])
def test_search_items_returns_kind_and_items(fake_api, source, count):
    """Вид источника возвращается рядом с элементами (поле ``source_kind`` результата)."""
    fake_api()

    kind, items = search_items("", source, 5)

    assert kind == "api"
    assert len(items) == count
