"""Структуры ответов инструментов MCP-сервера (``TypedDict``).

Аннотация возврата инструмента — источник ``outputSchema`` в каталоге
``tools/list``: MCP SDK разбирает её и публикует клиенту, а ``structuredContent``
ответа становится самим словарём (``wrap_output=False``). Поэтому поля описаны
здесь один раз, а инструмент в ``server.py`` только собирает такой словарь.

Структуры плоские: у вложенного поста берётся только ``id`` и ``title`` —
длинные ``body`` в списке постов не нужны, а модель получает обозримый JSON.
"""
from typing import List, TypedDict


class UserInfo(TypedDict):
    """Пользователь jsonplaceholder: id, имя, контакты, город и компания."""

    id: int
    name: str
    username: str
    email: str
    city: str
    phone: str
    website: str
    company: str


class PostInfo(TypedDict):
    """Пост jsonplaceholder: id, автор, заголовок и текст."""

    id: int
    user_id: int
    title: str
    body: str


class PostSummary(TypedDict):
    """Краткая запись поста для списка: id и заголовок."""

    id: int
    title: str


class UserPosts(TypedDict):
    """Посты пользователя: кому принадлежат, сколько их и сами записи."""

    user_id: int
    count: int
    posts: List[PostSummary]
