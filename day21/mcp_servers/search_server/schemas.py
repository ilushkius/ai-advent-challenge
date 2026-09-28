"""Структуры ответов инструментов сервера поиска (``TypedDict``).

Из аннотаций возврата SDK собирает ``outputSchema`` инструмента, а
``structuredContent`` ответа становится самим словарём — поэтому ответы описаны
типами, а не склеенными строками. Все поля обязательны: инструмент заполняет их
всегда (пустые значения — пустая строка или пустой список).
"""
from typing import Dict, List, TypedDict


class SearchItem(TypedDict):
    """Найденный элемент: id, заголовок, содержимое, адрес и метаданные источника.

    ``metadata`` — плоский словарь строк (источник, автор, путь, номер блока):
    модель читает его как подпись к элементу, поэтому значения приводятся к ``str``.
    """

    id: str
    title: str
    content: str
    url: str
    metadata: Dict[str, str]


class WebSearchResult(TypedDict):
    """Результат поиска в сети: запрос, источник, вид источника, число и элементы."""

    query: str
    source: str
    source_kind: str
    count: int
    items: List[SearchItem]


class LocalSearchResult(TypedDict):
    """Результат поиска по файлу дня: запрос, путь, число и найденные блоки."""

    query: str
    path: str
    count: int
    items: List[SearchItem]


class FetchUrlResult(TypedDict):
    """Прочитанная страница: адрес, код ответа, тип содержимого и текст.

    ``chars`` — длина текста ПОСЛЕ обрезки, ``truncated`` — признак того, что
    исходный текст был длиннее ``max_chars``.
    """

    url: str
    status: int
    content_type: str
    chars: int
    truncated: bool
    text: str
