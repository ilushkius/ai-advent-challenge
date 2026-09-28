"""Стенд внешнего API для тестов дня 17: jsonplaceholder без сети.

MCP-сервер дня читает jsonplaceholder.typicode.com, а тесты ходить в интернет не
должны: HTTPS-стенд не поднять, зато можно поставить локальный HTTP-сервер с теми
же ручками и передать его адрес серверу аргументом ``--api-base``. Отсюда и
фикстура ``stub_api_base``: тест получает базовый URL, живущий ровно один тест.

Отвечают ровно те ручки, которыми пользуются инструменты:
``GET /users/{id}`` (id 1..10), ``GET /posts/{id}`` (id 1..100),
``GET /posts?userId=N&_limit=K`` (посты автора) и ``GET /posts?_limit=K`` /
``GET /users?_limit=K`` (страница ленты целиком). Несуществующий id отдаёт 404 —
так проверяется, что ошибка внешнего API доезжает до модели текстом, а не
трассировкой.

День 20 добавил ручку ``GET /html``: HTML-страница с ``<script>``, ``<style>`` и
тегами — на ней проверяется инструмент ``fetch_url`` сервера поиска (теги
снимаются, а содержимое script/style в текст не попадает).

Стенд не эмулирует «настоящий» API целиком: неизвестный путь — 404, пагинации нет.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from urllib.parse import parse_qs, urlparse

#: Сколько сущностей объявлено у стенда — как у jsonplaceholder.
USER_COUNT = 10
POST_COUNT = 100

#: HTML-страница стенда: теги, скрытые блоки script/style и HTML-сущности. Тексты
#: SCRIPT_TEXT/STYLE_TEXT не должны попасть в результат ``fetch_url``, а ``&laquo;``
#: должен раскодироваться — на этом стоит проверка очистки страницы.
SCRIPT_TEXT = "alert('script must be dropped')"
STYLE_TEXT = "body { color: red }"
HTML_PAGE = (
    "<!DOCTYPE html>\n<html><head><title>Стенд дня 20</title>"
    f"<style>{STYLE_TEXT}</style><script>var hidden = \"{SCRIPT_TEXT}\";</script>"
    "</head><body>"
    "<h1>Заголовок стенда</h1>"
    "<p>Первый абзац &laquo;страницы&raquo; для чтения.</p>"
    "<div><ul><li>пункт один</li><li>пункт два</li></ul></div>"
    "<p>Второй абзац: RAG и поиск по документам, нарезка на чанки и векторный "
    "индекс для быстрого отбора фрагментов перед генерацией ответа.</p>"
    "<p>Третий абзац: страница нарочно длиннее двухсот символов, чтобы инструмент "
    "fetch_url можно было проверить на обрезку текста до предела max_chars и "
    "увидеть в ответе флаг truncated, а не молчаливое усечение.</p>"
    "<p>Четвёртый абзац: HTML-сущности &quot;кавычки&quot; и &amp; амперсанд "
    "раскодируются, а теги снимаются — в тексте ответа остаются только слова.</p>"
    "</body></html>"
)


def user_payload(user_id: int) -> dict:
    """Пользователь в форме jsonplaceholder (те же поля, что читает api_client)."""
    return {
        "id": user_id,
        "name": f"Leanne Graham {user_id}",
        "username": f"user{user_id}",
        "email": f"user{user_id}@example.com",
        "address": {"city": f"City {user_id}"},
        "phone": f"1-000-000-{user_id:04d}",
        "website": f"site{user_id}.example",
        "company": {"name": f"Company {user_id}"},
    }


def post_payload(post_id: int) -> dict:
    """Пост в форме jsonplaceholder: id, автор (userId), заголовок и текст."""
    return {
        "id": post_id,
        "userId": (post_id - 1) // 10 + 1,
        "title": f"Post {post_id}",
        "body": f"Body of post {post_id}",
    }


class _Handler(BaseHTTPRequestHandler):
    """Ручки внешнего API: пользователь, пост и посты пользователя."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 — имя задано базовым классом
        parsed = urlparse(self.path)
        parts = [item for item in parsed.path.split("/") if item]
        if len(parts) == 2 and parts[0] == "users":
            self._reply(self._find("user", parts[1], USER_COUNT, user_payload))
        elif len(parts) == 2 and parts[0] == "posts":
            self._reply(self._find("post", parts[1], POST_COUNT, post_payload))
        elif parts == ["posts"]:
            self._reply(self._list_posts(parse_qs(parsed.query)))
        elif parts == ["users"]:
            self._reply(self._list_users(parse_qs(parsed.query)))
        elif parsed.path == "/html":
            self._html(200, HTML_PAGE)
        else:
            self._json(404, {})

    def _find(self, kind: str, raw_id: str, count: int, builder):
        """Сущность по id или 404: у стенда объявлено ``count`` записей."""
        try:
            item_id = int(raw_id)
        except ValueError:
            return 404, {}
        if not 1 <= item_id <= count:
            return 404, {}
        return 200, builder(item_id)

    def _limit_of(self, query: dict) -> int:
        """Ограничение ``_limit`` из строки запроса (0 — без ограничения)."""
        try:
            return int((query.get("_limit") or ["0"])[0])
        except ValueError:
            return 0

    def _list_posts(self, query: dict):
        """Список постов: с ``userId`` — посты автора, без него — вся лента.

        Ограничение ``_limit`` применяется после отбора, как у jsonplaceholder.
        Ручка без ``userId`` нужна серверу поиска дня 20: его ``search_web``
        читает страницу ``/posts?_limit=100`` и фильтрует её сам.
        """
        limit = self._limit_of(query)
        raw_user = (query.get("userId") or [""])[0]
        posts = [post_payload(post_id) for post_id in range(1, POST_COUNT + 1)]
        if raw_user:
            user_id = int(raw_user)
            posts = [post for post in posts if post["userId"] == user_id]
        return 200, posts[:limit] if limit > 0 else posts

    def _list_users(self, query: dict):
        """Список пользователей с ограничением ``_limit`` (ручка дня 20)."""
        limit = self._limit_of(query)
        users = [user_payload(user_id) for user_id in range(1, USER_COUNT + 1)]
        return 200, users[:limit] if limit > 0 else users

    def _reply(self, result) -> None:
        """Отправляет пару (код, тело), где телом может быть любая структура."""
        status, payload = result
        self._json(status, payload)

    def _html(self, status: int, text: str) -> None:
        """Отвечает HTML-страницей (тип содержимого — ``text/html``)."""
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        """Отвечает JSON-ом с нужным кодом (кодировка — UTF-8, как у jsonplaceholder)."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        """Молчит: вывод сервера не должен засорять вывод тестов."""


@contextmanager
def stub_api() -> Iterator[str]:
    """Поднимает стенд на свободном порту и отдаёт его базовый URL.

    Сервер живёт в потоке-демоне, поэтому забытый ``finally`` не заблокирует
    завершение тестов; закрывается он всегда — иначе порт остался бы занят.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
