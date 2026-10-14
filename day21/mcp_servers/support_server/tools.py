"""Тела пяти инструментов MCP-сервера поддержки (день 33).

Инструменты отвечают про КЛИЕНТОВ ПОДДЕРЖКИ, а не про проект: кто обратился
(``get_user``, ``list_users``), что у него в тикете (``get_ticket``), какие тикеты
за ним числятся (``list_user_tickets``) и что продукт говорит про раздел
(``get_product_info``). Источник данных один — JSON-база
``config.DB_PATH`` (``backend/data/support_db.json``).

Почему база читается на КАЖДЫЙ вызов. Файл — источник истины для поддержки:
правку базы (новый тикет, смена статуса) клиент обязан увидеть немедленно, а кэш в
процессе сервера дал бы расхождение ровно в тот момент, когда это важнее всего.
Файл небольшой (десятки килобайт), поэтому чтение дешевле кэша с инвалидацией.

Почему ненайденная запись — данные, а не ошибка. Профиль с опечаткой в id или
удалённый тикет — штатный случай: служба отвечает по документации, а причину
показывает предупреждением. Поэтому вместо ``ToolError`` инструменты возвращают
заполненную пустыми значениями запись с непустым ``error`` (``config.NOT_FOUND``).
Исключение остаётся там, где ответить нечем: пустой аргумент, недоступный или
нечитаемый файл базы — ``ToolError`` с русским текстом.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.support_server import config
from mcp_servers.support_server.config import (  # noqa: F401  (реэкспорт для скриптов)
    DAY_ROOT,
)
from mcp_servers.support_server.schemas import (
    ProductInfo,
    Ticket,
    TicketMessage,
    TicketSummary,
    UserList,
    UserProfile,
    UserTickets,
)

__all__ = ["DAY_ROOT", "get_product_info", "get_ticket", "get_user",
           "list_user_tickets", "list_users"]


def _load() -> dict:
    """Читает базу поддержки: сбой чтения или разбора — ``ToolError``.

    Ошибка содержит путь и причину: «база недоступна» без пути не отличима от
    опечатки в аргументе, а сервер запускается отдельным процессом, где рабочий
    каталог не тот, что у клиента.
    """
    if config.DB_PATH.suffix != config.FILE_SUFFIX:
        raise ToolError(f"база поддержки должна быть JSON-файлом: {config.DB_PATH}")
    try:
        raw = config.DB_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"база поддержки недоступна: {config.DB_PATH}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"база поддержки недоступна: {config.DB_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"база поддержки недоступна: {config.DB_PATH}: ожидался объект")
    return data


def _required(value: Any, name: str) -> str:
    """Обязательный строковый аргумент инструмента; пустой — ``ToolError``."""
    text = str(value or "").strip()
    if not text:
        raise ToolError(f"{name} не задан")
    return text


def _records(data: dict, key: str) -> list:
    """Список записей базы по имени раздела: не список — пустой список."""
    value = data.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _user_record(user_id: str, data: Optional[dict] = None) -> Optional[dict]:
    """Запись пользователя по id или ``None``; пустой аргумент — ``ToolError``."""
    key = _required(user_id, "user_id")
    records = _records(_load() if data is None else data, "users")
    return next((item for item in records if str(item.get("id")) == key), None)


def _ticket_record(ticket_id: str, data: Optional[dict] = None) -> Optional[dict]:
    """Запись тикета по id или ``None``; пустой аргумент — ``ToolError``."""
    key = _required(ticket_id, "ticket_id")
    records = _records(_load() if data is None else data, "tickets")
    return next((item for item in records if str(item.get("id")) == key), None)


def _product_record(area: str, data: Optional[dict] = None) -> Optional[dict]:
    """Запись раздела продукта по области или ``None``; пустой аргумент — ``ToolError``."""
    key = _required(area, "product_area")
    records = _records(_load() if data is None else data, "products")
    return next((item for item in records if str(item.get("area")) == key), None)


def _profile(record: dict, fallback_id: str) -> UserProfile:
    """Профиль из записи базы: поля обязательны, ``error`` пуст у найденной записи."""
    return UserProfile(
        id=str(record.get("id") or fallback_id),
        name=str(record.get("name") or ""),
        email=str(record.get("email") or ""),
        plan=str(record.get("plan") or ""),
        registered_at=str(record.get("registered_at") or ""),
        last_seen=str(record.get("last_seen") or ""),
        error="",
    )


def _summary(record: dict) -> TicketSummary:
    """Тикет в списке: ``messages`` — ЧИСЛО сообщений, а не их список."""
    messages = record.get("messages")
    return TicketSummary(
        id=str(record.get("id") or ""),
        subject=str(record.get("subject") or ""),
        status=str(record.get("status") or ""),
        priority=str(record.get("priority") or ""),
        created_at=str(record.get("created_at") or ""),
        messages=len(messages) if isinstance(messages, list) else 0,
    )


def _empty_user(user_id: str) -> UserProfile:
    """Заглушка ненайденного профиля: пустые поля и непустой ``error``."""
    return UserProfile(id=str(user_id), name="", email="", plan="", registered_at="",
                       last_seen="", error=config.NOT_FOUND)


def _empty_ticket(ticket_id: str) -> Ticket:
    """Заглушка ненайденного тикета: пустые поля и непустой ``error``."""
    return Ticket(id=str(ticket_id), user_id="", subject="", status="", priority="",
                  created_at="", messages=[], error=config.NOT_FOUND)


def _empty_product(area: str) -> ProductInfo:
    """Заглушка неизвестного раздела продукта: пустые поля и непустой ``error``."""
    return ProductInfo(area=str(area), title="", description="", faq=[],
                       error=config.NOT_FOUND)


def get_user(user_id: str) -> UserProfile:
    """Возвращает профиль клиента поддержки по идентификатору.

    Параметры: ``user_id`` — идентификатор из обращения (``"user_003"``).

    Возвращает словарь: ``id``, ``name``, ``email``, ``plan`` (free, pro или
    enterprise), ``registered_at``, ``last_seen`` и ``error`` (пусто у найденной
    записи).

    Пример: ``get_user(user_id="user_003")`` → ``{"id": "user_003", "name": "Мария
    Кузнецова", "email": "m.kuznetsova@example.com", "plan": "pro", "registered_at":
    "2026-05-21", "last_seen": "2026-10-14", "error": ""}``.

    Ошибка: пустой ``user_id`` или недоступная база — ``ToolError``. Ненайденный
    id — не ошибка: запись придёт пустой с ``error="not found"``.
    """
    key = _required(user_id, "user_id")
    record = _user_record(key)
    return _empty_user(key) if record is None else _profile(record, key)


def get_ticket(ticket_id: str) -> Ticket:
    """Возвращает тикет целиком вместе с историей сообщений.

    Параметры: ``ticket_id`` — идентификатор тикета (``"ticket_007"``).

    Возвращает словарь: ``id``, ``user_id``, ``subject``, ``status`` (open,
    in_progress, resolved, closed), ``priority`` (low, normal, high, urgent),
    ``created_at``, ``messages`` (список ``{author, text, timestamp}`` по
    возрастанию времени; ``author`` — user или support) и ``error``.

    Пример: ``get_ticket(ticket_id="ticket_007")`` → ``{"id": "ticket_007",
    "subject": "Не работает авторизация", "status": "open", "priority": "high",
    "messages": [{"author": "user", "text": "…", "timestamp": "…"}, …], "error": ""}``.

    Ошибка: пустой ``ticket_id`` или недоступная база — ``ToolError``. Ненайденный
    тикет — пустая запись с ``error="not found"``.
    """
    key = _required(ticket_id, "ticket_id")
    record = _ticket_record(key)
    if record is None:
        return _empty_ticket(key)
    messages = [TicketMessage(author=str(item.get("author") or ""),
                              text=str(item.get("text") or ""),
                              timestamp=str(item.get("timestamp") or ""))
                for item in record.get("messages") or [] if isinstance(item, dict)]
    return Ticket(
        id=str(record.get("id") or key),
        user_id=str(record.get("user_id") or ""),
        subject=str(record.get("subject") or ""),
        status=str(record.get("status") or ""),
        priority=str(record.get("priority") or ""),
        created_at=str(record.get("created_at") or ""),
        messages=messages,
        error="",
    )


def list_user_tickets(user_id: str) -> UserTickets:
    """Перечисляет тикеты клиента без истории сообщений.

    Параметры: ``user_id`` — идентификатор клиента (``"user_003"``).

    Возвращает словарь: ``user_id``, ``count`` (число тикетов), ``tickets`` (список
    ``{id, subject, status, priority, created_at, messages}``, где ``messages`` —
    ЧИСЛО сообщений) и ``error``. Тикеты идут в порядке базы.

    Пример: ``list_user_tickets(user_id="user_003")`` → ``{"user_id": "user_003",
    "count": 2, "tickets": [{"id": "ticket_007", "subject": "Не работает
    авторизация", "status": "open", "priority": "high", "created_at": "…",
    "messages": 3}, …], "error": ""}``.

    Ошибка: пустой ``user_id`` или недоступная база — ``ToolError``. Ненайденный
    пользователь — ``count=0`` и ``error="not found"``; у найденного без тикетов —
    ``count=0`` и пустой ``error``.
    """
    key = _required(user_id, "user_id")
    data = _load()
    if _user_record(key, data) is None:
        return UserTickets(user_id=key, count=0, tickets=[], error=config.NOT_FOUND)
    tickets = [_summary(item) for item in _records(data, "tickets")
               if str(item.get("user_id")) == key]
    return UserTickets(user_id=key, count=len(tickets), tickets=tickets, error="")


def get_product_info(product_area: str) -> ProductInfo:
    """Возвращает раздел продукта: описание и короткий FAQ по области.

    Параметры: ``product_area`` — область продукта: ``"auth"``, ``"billing"``,
    ``"api"``, ``"integrations"`` или ``"notifications"``.

    Возвращает словарь: ``area``, ``title``, ``description`` и ``faq`` (список
    строк «вопрос — ответ»), ``error`` (пусто у найденной области).

    Пример: ``get_product_info(product_area="auth")`` → ``{"area": "auth", "title":
    "Авторизация и вход", "description": "…", "faq": ["Как сменить пароль? — …", …],
    "error": ""}``.

    Ошибка: пустая область или недоступная база — ``ToolError``. Неизвестная
    область — пустая запись с ``error="not found"``.
    """
    key = _required(product_area, "product_area")
    record = _product_record(key)
    if record is None:
        return _empty_product(key)
    faq = record.get("faq")
    return ProductInfo(
        area=str(record.get("area") or key),
        title=str(record.get("title") or ""),
        description=str(record.get("description") or ""),
        faq=[str(item) for item in faq] if isinstance(faq, list) else [],
        error="",
    )


def list_users() -> UserList:
    """Перечисляет всех клиентов базы поддержки.

    Параметров нет: список нужен интерфейсу поддержки — селектор клиента строится
    из него, а не из константного перечня идентификаторов.

    Возвращает словарь: ``count`` (число профилей), ``users`` (список профилей
    ``get_user``, у каждого ``error`` пуст) и ``error`` (пусто при успехе; пустая
    база — это ``count=0`` и пустой ``error``, а не отказ).

    Пример: ``list_users()`` → ``{"count": 5, "users": [{"id": "user_001", "name":
    "Анна Смирнова", "plan": "free", …, "error": ""}, …], "error": ""}``.

    Ошибка: недоступная или нечитаемая база — ``ToolError``.
    """
    data = _load()
    users = [_profile(item, str(item.get("id") or "")) for item in _records(data, "users")]
    return UserList(count=len(users), users=users, error="")
