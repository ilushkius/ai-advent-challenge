"""Pydantic-схемы API мини-чата (день 25).

Схемы повторяют форму словарей ``services/mini_chat_service.py``: сессия
(``MiniChatSessionOut``), ответ с источниками и памятью задачи
(``MiniChatAnswerOut``), снимок памяти задачи (``MiniChatTaskMemoryOut``) и
история диалога (``MiniChatHistoryOut``). Источники, цитаты и расходы описаны
схемами дня 22 (``RagSourceOut``/``RagQuoteOut``/``RagTokensOut``) — второй формы
тех же данных не заводим, мини-чат берёт фрагменты у того же отбора.

``mode`` в ответе — ``rag`` (контекст корпуса), ``dont_know`` (контекст слабее
порога) либо ``error`` (повторный сбой модели); последний режим есть только у
мини-чата, поэтому строка объявлена свободной, без ``Enum``. Пустое ``message``
отсекается здесь (``min_length=1``) — «Введите текст сообщения» это ошибка
валидации, а не ответ API.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..domain import rag_mode
from .rag import RagQuoteOut, RagSourceOut, RagTokensOut


class MiniChatSessionIn(BaseModel):
    """POST /mini-chat/sessions — открыть сессию мини-чата."""

    user_id: Optional[str] = Field(
        None, max_length=config.USER_ID_MAX,
        description="Пользователь сессии (по умолчанию default)",
    )


class MiniChatSessionOut(BaseModel):
    """Сессия мини-чата: ``task_id`` связан с ``session_id`` префиксом ``mc-``."""

    session_id: str = Field(..., description="Идентификатор сессии мини-чата")
    task_id: str = Field(..., description="Задача рабочей памяти: mc-<session_id>")
    user_id: str = Field(..., description="Пользователь сессии")
    created_at: str = Field(..., description="Время открытия сессии (ISO 8601)")


class MiniChatMessageIn(BaseModel):
    """POST /mini-chat/sessions/{session_id}/messages — реплика пользователя."""

    message: str = Field(
        ..., min_length=1, max_length=config.INDEX_QUERY_MAX,
        description="Реплика пользователя (пустая — ошибка валидации)",
    )
    top_k: int = Field(
        rag_mode.RAG_DEFAULT_TOP_K, ge=1, le=rag_mode.RAG_MAX_TOP_K,
        description="Сколько фрагментов корпуса брать в контекст",
    )
    provider: Optional[str] = Field(
        None, max_length=16,
        description=(
            "Провайдер ответа и извлечения памяти: deepseek | local; по умолчанию — "
            "LLM_PROVIDER из конфига. Незнакомое имя — 400"
        ),
    )


class MiniChatTaskMemoryOut(BaseModel):
    """Снимок памяти задачи: четыре ключа рабочей памяти плюс счётчик реплик."""

    session_id: str = Field(..., description="Идентификатор сессии мини-чата")
    task_id: str = Field(..., description="Задача рабочей памяти: mc-<session_id>")
    goal: str = Field("", description="Цель диалога")
    terms: List[str] = Field([], description="Зафиксированные термины")
    constraints: List[str] = Field([], description="Ограничения")
    clarifications: List[str] = Field([], description="Уточнения пользователя")
    message_count: int = Field(0, description="Сколько реплик сохранено в сессии")
    updated: bool = Field(False, description="Извлекалась ли память хотя бы раз")
    updated_at: Optional[str] = Field(
        None, description="Время последнего обновления памяти (ISO 8601)")


class MiniChatAnswerOut(BaseModel):
    """Ответ мини-чата: режим, источники, цитаты, память задачи и расходы."""

    session_id: str = Field(..., description="Идентификатор сессии мини-чата")
    task_id: str = Field(..., description="Задача рабочей памяти: mc-<session_id>")
    question: str = Field(..., description="Реплика пользователя, на которую отвечали")
    mode: str = Field(
        ..., description="rag — ответ по корпусу, dont_know — контекст слабее порога, "
                         "error — повторный сбой модели")
    answer: str = Field(..., description="Текст ответа ассистента")
    provider: str = Field(
        "", description="Кто ответил: deepseek (облако) или local (Ollama по HTTP)"
    )
    sources: List[RagSourceOut] = Field(
        [], description="Фрагменты корпуса, попавшие в контекст")
    quotes: List[RagQuoteOut] = Field(
        [], description="Прямые цитаты из контекста, проверенные на опору")
    quotes_verified: bool = Field(
        False, description="Подтверждены ли цитаты в тексте ответа")
    confidence: float = Field(0.0, description="Уверенность цитирования [0, 1]")
    grounding: str = Field("", description="Вердикт оценки опоры ответа на контекст")
    warning: str = Field("", description="Предупреждение режима ответа")
    memory_warning: str = Field(
        "", description="Предупреждение о необновлённой памяти задачи")
    fallback: bool = Field(False, description="Ответ получен без модели (откат)")
    chunks_used: int = Field(0, description="Сколько фрагментов ушло в контекст")
    context_tokens: int = Field(0, description="Токенов в контексте запроса")
    duration_ms: int = Field(0, description="Время ответа, миллисекунды")
    tokens: Optional[RagTokensOut] = Field(
        None, description="Расходы модели на ответ (нет в режимах без модели)")
    task_memory: MiniChatTaskMemoryOut = Field(
        ..., description="Память задачи после этой реплики")
    memory_updated: bool = Field(
        False, description="Обновилась ли память задачи на этой реплике")


class MiniChatHistoryMessageOut(BaseModel):
    """Реплика истории диалога: роль, текст и время записи."""

    role: str = Field(..., description="user | assistant")
    content: str = Field(..., description="Текст реплики")
    created_at: Optional[str] = Field(
        None, description="Время записи реплики (ISO 8601)")


class MiniChatHistoryOut(BaseModel):
    """История диалога сессии в порядке добавления."""

    session_id: str = Field(..., description="Идентификатор сессии мини-чата")
    task_id: str = Field(..., description="Задача рабочей памяти: mc-<session_id>")
    messages: List[MiniChatHistoryMessageOut] = Field(
        [], description="Реплики сессии по порядку (user, assistant, …)")


class MiniChatCloseOut(BaseModel):
    """Результат закрытия сессии: удалены только реплики, память задачи остаётся."""

    session_id: str = Field(..., description="Идентификатор сессии мини-чата")
    task_id: str = Field(..., description="Задача рабочей памяти: mc-<session_id>")
    deleted: int = Field(0, description="Сколько реплик удалено")


__all__ = ["MiniChatAnswerOut", "MiniChatCloseOut", "MiniChatHistoryMessageOut",
           "MiniChatHistoryOut", "MiniChatMessageIn", "MiniChatSessionIn",
           "MiniChatSessionOut", "MiniChatTaskMemoryOut"]
