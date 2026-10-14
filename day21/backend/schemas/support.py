"""Pydantic-схемы API ассистента поддержки (день 33).

Один файл на пять эндпоинтов раздела: вопрос ``POST /support/ask``, каталог
пользователей ``GET /support/users``, один профиль ``GET /support/users/{id}``,
тикеты клиента ``GET /support/tickets`` и один тикет ``GET /support/tickets/{id}``.
Поля ``answer``/``sources``/``user_context``/``ticket_context`` описаны отдельными
моделями, а не ``dict``: раздел интерфейса читает их по именам, и схема —
единственное место, где эти имена закреплены.

``provider`` уходит в запрос строкой, а не ``Literal``: список провайдеров живёт в
домене (``llm_provider.PROVIDERS``), и незнакомое имя — это 400 от службы с
перечнем доступных, а не 422 от Pydantic, который знал бы про них третьим местом.

``SupportUserOut`` и ``SupportTicketOut`` описывают контекст, который служба берёт
из MCP-сервера поддержки: профиль клиента и тикет с историей сообщений.
Служебное поле ``error`` инструментов в контекст не попадает — служба снимает его
до сборки промпта, а причину отказа показывает в ``warnings``.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..core import config


class SupportAskIn(BaseModel):
    """POST /support/ask — вопрос клиента поддержки с контекстом."""

    question: str = Field(
        ..., min_length=1, max_length=config.INDEX_QUERY_MAX,
        description="Вопрос клиента о продукте",
    )
    user_id: str = Field(
        "", max_length=64,
        description="Идентификатор клиента (напр. user_003); пусто — без профиля",
    )
    ticket_id: str = Field(
        "", max_length=64,
        description="Идентификатор тикета (напр. ticket_007); пусто — без тикета",
    )
    provider: str = Field(
        "deepseek", max_length=16,
        description=("Провайдер ответа: deepseek | local; по умолчанию deepseek. "
                     "Незнакомое имя — 400"),
    )


class SupportSourceOut(BaseModel):
    """Фрагмент документации поддержки, на который опирался ответ."""

    source: str = Field(..., description="Имя документа корпуса (напр. day21-docs-support-faq.md)")
    title: str = Field(..., description="Заголовок документа")
    section: str = Field("", description="Секция (заголовок раздела) фрагмента")
    chunk_id: str = Field("", description="Идентификатор чанка в индексе")
    score: float = Field(0.0, description="Балл, по которому фрагмент отобран")
    vector_score: Optional[float] = Field(
        None, description="Вклад векторной близости (день 22), если считался")
    lexical_score: Optional[float] = Field(
        None, description="Доля веса слов вопроса в тексте фрагмента, если считалась")
    rerank_score: Optional[float] = Field(
        None, description="Балл реранкера (день 23), если он считался")


class SupportToolUseOut(BaseModel):
    """Один вызов MCP-инструмента в ответе: что вызвали и чем это кончилось."""

    tool: str = Field(..., description="Имя инструмента (напр. get_ticket)")
    ok: bool = Field(True, description="Инструмент ответил без ошибки")
    duration_ms: int = Field(0, description="Сколько занял вызов, мс")
    error: str = Field("", description="Текст ошибки инструмента (пусто при успехе)")


class SupportUserOut(BaseModel):
    """Профиль клиента поддержки из MCP-инструмента ``get_user``."""

    id: str = Field(..., description="Идентификатор клиента (напр. user_003)")
    name: str = Field("", description="Имя клиента")
    email: str = Field("", description="Email клиента")
    plan: str = Field("", description="Тариф: free | pro | enterprise")
    registered_at: str = Field("", description="Дата регистрации (ISO-8601)")
    last_seen: str = Field("", description="Дата последней активности (ISO-8601)")


class SupportTicketMessageOut(BaseModel):
    """Одно сообщение тикета: кто написал, текст и время."""

    author: str = Field("", description="Автор сообщения: user | support")
    text: str = Field("", description="Текст сообщения")
    timestamp: str = Field("", description="Время сообщения (ISO-8601)")


class SupportTicketOut(BaseModel):
    """Тикет клиента целиком: тема, статус, приоритет и история сообщений."""

    id: str = Field(..., description="Идентификатор тикета (напр. ticket_007)")
    user_id: str = Field("", description="Клиент — владелец тикета")
    subject: str = Field("", description="Тема тикета")
    status: str = Field("", description="Статус: open | in_progress | resolved | closed")
    priority: str = Field("", description="Приоритет: low | normal | high | urgent")
    created_at: str = Field("", description="Дата создания (ISO-8601)")
    messages: List[SupportTicketMessageOut] = Field(
        [], description="История сообщений (последние — в конце)")


class SupportTicketSummaryOut(BaseModel):
    """Тикет в списке клиента: без истории, ``messages`` — ЧИСЛО сообщений.

    Так его отдаёт инструмент ``list_user_tickets``: селектор тикета в разделе
    показывает тему, статус и приоритет, а полная история приходит только у
    выбранного тикета (``GET /support/tickets/{id}``).
    """

    id: str = Field(..., description="Идентификатор тикета")
    subject: str = Field("", description="Тема тикета")
    status: str = Field("", description="Статус: open | in_progress | resolved | closed")
    priority: str = Field("", description="Приоритет: low | normal | high | urgent")
    created_at: str = Field("", description="Дата создания (ISO-8601)")
    messages: int = Field(0, description="Сколько сообщений в тикете")


class SupportTicketsOut(BaseModel):
    """Тикеты клиента для селектора; причина отказа приходит полем ``error``."""

    user_id: str = Field("", description="Клиент, чьи тикеты перечислены")
    count: int = Field(0, description="Сколько тикетов в ответе")
    tickets: List[SupportTicketSummaryOut] = Field([], description="Тикеты клиента")
    error: str = Field("", description="Причина отказа (пусто при успехе; напр. not found)")


class SupportUserListOut(BaseModel):
    """Каталог клиентов поддержки; ошибка подключения приходит полем ``error``."""

    count: int = Field(0, description="Сколько профилей в ответе")
    users: List[SupportUserOut] = Field([], description="Профили клиентов")
    error: str = Field("", description="Причина отказа подключения (пусто при успехе)")


class SupportAskOut(BaseModel):
    """Ответ ассистента поддержки: текст, источники и контекст клиента."""

    answer: str = Field(..., description="Ответ модели либо объяснение отказа")
    sources: List[SupportSourceOut] = Field(
        [], description="Фрагменты документации поддержки (может быть пусто)")
    user_context: Optional[SupportUserOut] = Field(
        None, description="Профиль клиента из MCP; None — профиль не запрошен или не найден")
    ticket_context: Optional[SupportTicketOut] = Field(
        None, description="Тикет из MCP; None — тикет не запрошен или не найден")
    product_context: Optional[dict] = Field(
        None, description="Раздел продукта из MCP: описание и короткий FAQ области")
    mcp_tools_used: List[SupportToolUseOut] = Field(
        [], description="Вызовы MCP-инструментов по вопросу")
    duration_ms: int = Field(0, description="Время ответа целиком, мс")
    provider: str = Field("deepseek", description="Провайдер, который отвечал")
    warnings: List[str] = Field(
        [], description="Отказы шагов: пустой индекс, недоступный MCP, ненайденный профиль")


__all__ = ["SupportAskIn", "SupportAskOut", "SupportSourceOut", "SupportTicketMessageOut",
           "SupportTicketOut", "SupportTicketsOut", "SupportTicketSummaryOut",
           "SupportToolUseOut", "SupportUserListOut", "SupportUserOut"]
