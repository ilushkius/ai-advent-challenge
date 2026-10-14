"""Структуры ответов инструментов сервера поддержки (``TypedDict``).

Из аннотаций возврата SDK собирает ``outputSchema`` инструмента, а
``structuredContent`` ответа становится самим словарём — поэтому ответы описаны
типами, а не склеенными строками. Все поля обязательны: инструмент заполняет их
всегда (пустые значения — пустая строка, пустой список или ``False``), а
ненайденная запись отличается НЕПУСТЫМ полем ``error`` (``config.NOT_FOUND``), а не
отсутствием полей: схема с необязательными полями заставила бы и клиента, и
модель проверять каждое поле на существование.

Почему ``list_user_tickets`` отдаёт объект, а не список. SDK публикует
``outputSchema`` только для объекта в корне: аннотация-список пришла бы клиенту
неструктурированным текстом, и служба не увидела бы ни ``count``, ни ``error``.
Так же сделан ``SavedList`` у ``storage_server.list_saved``.
"""
from typing import List, TypedDict


class UserProfile(TypedDict):
    """Профиль клиента поддержки; ``error`` пуст, когда запись найдена."""

    id: str
    name: str
    email: str
    plan: str
    registered_at: str
    last_seen: str
    error: str


class TicketMessage(TypedDict):
    """Одно сообщение тикета: кто написал, текст и время."""

    author: str
    text: str
    timestamp: str


class Ticket(TypedDict):
    """Тикет целиком: тема, статус, приоритет, дата и история сообщений."""

    id: str
    user_id: str
    subject: str
    status: str
    priority: str
    created_at: str
    messages: List[TicketMessage]
    error: str


class TicketSummary(TypedDict):
    """Тикет в списке: тема и статус без истории сообщений, ``messages`` — их число."""

    id: str
    subject: str
    status: str
    priority: str
    created_at: str
    messages: int


class UserTickets(TypedDict):
    """Тикеты пользователя: сколько их и сами записи; ``error`` — причина отказа."""

    user_id: str
    count: int
    tickets: List[TicketSummary]
    error: str


class UserList(TypedDict):
    """Все пользователи базы: число и профили (у каждого ``error`` пуст)."""

    count: int
    users: List[UserProfile]
    error: str


class ProductInfo(TypedDict):
    """Раздел продукта: область, название, описание и короткий FAQ."""

    area: str
    title: str
    description: str
    faq: List[str]
    error: str
