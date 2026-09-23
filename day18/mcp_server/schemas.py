"""Структуры ответов инструментов MCP-сервера (``TypedDict``).

Аннотация возврата инструмента — источник ``outputSchema`` в каталоге
``tools/list``: MCP SDK разбирает её и публикует клиенту, а ``structuredContent``
ответа становится самим словарём (``wrap_output=False``). Поэтому поля описаны
здесь один раз, а инструмент в ``server.py`` только собирает такой словарь.

Структуры плоские: у вложенного поста берётся только ``id`` и ``title`` —
длинные ``body`` в списке постов не нужны, а модель получает обозримый JSON.
У инструментов планировщика (день 18) в ответе — номер поставленной задачи,
подтверждение и то, что инструмент уже успел сделать: напоминание сохранено,
лента сбора прочитана, сводка посчитана.
"""
from typing import Any, Dict, List, TypedDict


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


class ReminderScheduled(TypedDict):
    """Напоминание сохранено и поставлено в планировщик."""

    task_id: int
    reminder_id: int
    text: str
    remind_at: str
    status: str
    next_run_at: str
    message: str


class CollectionStarted(TypedDict):
    """Периодический сбор данных запущен, первая запись уже сохранена."""

    task_id: int
    name: str
    source_url: str
    interval_seconds: int
    next_run_at: str
    records_saved: int
    message: str


class SummaryReady(TypedDict):
    """Первая сводка посчитана, дальше она повторяется по расписанию."""

    task_id: int
    summary_id: int
    name: str
    period_start: str
    period_end: str
    total_records: int
    summary_text: str
    key_metrics: Dict[str, Any]
    next_run_at: str
    message: str
