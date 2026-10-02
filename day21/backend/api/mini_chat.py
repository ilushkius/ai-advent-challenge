"""Роутер API: мини-чат дня 25 — сессии, реплики, память задачи и история.

Пять эндпоинтов: ``POST /mini-chat/sessions`` (открыть сессию), ``POST
/mini-chat/sessions/{session_id}/messages`` (реплика и ответ с источниками,
цитатами и памятью задачи), ``GET /mini-chat/sessions/{session_id}/memory``
(снимок памяти задачи), ``GET /mini-chat/sessions/{session_id}/history``
(история диалога) и ``DELETE /mini-chat/sessions/{session_id}`` (закрыть сессию
идемпотентно: реплики удаляются, память задачи остаётся).

Перевод отказов в коды ответов: ``MiniChatSessionError`` — 404 (сессии нет),
пустая реплика (``ValueError``) — 400, ``RAGRejected`` — 400/409 как в режиме
RAG, ``RAGUpstreamError`` — 502 (сбой отбора; сбой ответа модель уже перехвачен
сервисом и вернулся записью с ``mode="error"``).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core import dependencies
from ..domain import rag_filter, rag_mode
from ..schemas import (
    MiniChatAnswerOut,
    MiniChatCloseOut,
    MiniChatHistoryOut,
    MiniChatMessageIn,
    MiniChatSessionIn,
    MiniChatSessionOut,
    MiniChatTaskMemoryOut,
)
from ..services.mini_chat_service import MiniChatSessionError
from ..services.rag_errors import RAGRejected, RAGUpstreamError

router = APIRouter()

#: Коды причин, которые говорят про сам запрос, а не про состояние корпуса.
_BAD_REQUEST_REASONS = (rag_mode.REASON_RAG_BAD_STRATEGY,
                        rag_mode.REASON_RAG_EMPTY_QUERY,
                        rag_filter.REASON_RAG_BAD_MODE)


def _rejected(exc: RAGRejected) -> HTTPException:
    """Отказ отбора в HTTP: 400 — про запрос, 409 — про непроиндексированный корпус."""
    code = 400 if exc.reason_code in _BAD_REQUEST_REASONS else 409
    return HTTPException(status_code=code, detail=exc.message)


def _http_error(exc: Exception) -> HTTPException:
    """Доменное исключение мини-чата в HTTP-ответ.

    ``MiniChatSessionError`` проверяется раньше ``ValueError``: она — его наследник,
    но означает «сессии нет» (404), а не «реплика пуста» (400).
    """
    if isinstance(exc, MiniChatSessionError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RAGRejected):
        return _rejected(exc)
    if isinstance(exc, RAGUpstreamError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/mini-chat/sessions",
    response_model=MiniChatSessionOut,
    status_code=201,
    summary="Открыть сессию мини-чата",
    description=(
        "Создаёт сессию мини-чата: краткосрочная память и память задачи живут в "
        "базе агентов под служебным агентом ``mini-chat``, задача рабочей памяти "
        "связана с сессией префиксом ``mc-``, поэтому перезапуск бэкенда память "
        "не теряет."
    ),
)
def open_session(payload: MiniChatSessionIn) -> MiniChatSessionOut:
    """Сессия мини-чата: ``session_id``, связанный ``task_id`` и пользователь."""
    service = dependencies.get_mini_chat_service()
    return MiniChatSessionOut(**service.start_session(payload.user_id))


@router.post(
    "/mini-chat/sessions/{session_id}/messages",
    response_model=MiniChatAnswerOut,
    summary="Реплика пользователя и ответ мини-чата",
    description=(
        "Ищет фрагменты корпуса, собирает промпт из контекста, памяти задачи и "
        "истории диалога, отвечает моделью и обновляет память задачи. Ответ "
        "приходит с источниками, цитатами и предупреждениями: ``dont_know`` — "
        "контекст слабее порога, ``error`` — модель не ответила после всех повторов."
    ),
)
def send_message(session_id: str, payload: MiniChatMessageIn) -> MiniChatAnswerOut:
    """Ответ мини-чата с источниками, цитатами и памятью задачи."""
    service = dependencies.get_mini_chat_service()
    try:
        result = service.chat(session_id, payload.message, top_k=payload.top_k)
    except (MiniChatSessionError, ValueError, RAGRejected, RAGUpstreamError) as exc:
        raise _http_error(exc) from exc
    return MiniChatAnswerOut(**result)


@router.get(
    "/mini-chat/sessions/{session_id}/memory",
    response_model=MiniChatTaskMemoryOut,
    summary="Память задачи сессии",
    description=(
        "Четыре ключа рабочей памяти (цель, термины, ограничения, уточнения), "
        "счётчик реплик и метка последнего обновления. Обновление — полная замена: "
        "предыдущее состояние не сливается с новым."
    ),
)
def read_memory(session_id: str) -> MiniChatTaskMemoryOut:
    """Снимок памяти задачи: панель «Память задачи» мини-чата."""
    service = dependencies.get_mini_chat_service()
    try:
        result = service.get_task_memory(session_id)
    except (MiniChatSessionError, ValueError) as exc:
        raise _http_error(exc) from exc
    return MiniChatTaskMemoryOut(**result)


@router.get(
    "/mini-chat/sessions/{session_id}/history",
    response_model=MiniChatHistoryOut,
    summary="История диалога сессии",
    description=(
        "Реплики сессии в порядке добавления: роль, текст и время записи. Ответы "
        "режимов ``dont_know`` и ``error`` тоже сохраняются, чтобы ход диалога не "
        "терялся. ``limit`` оставляет последние реплики (скользящее окно дня 10)."
    ),
)
def read_history(session_id: str,
                 limit: Optional[int] = Query(
                     None, ge=1, le=500,
                     description="Сколько последних реплик вернуть"),
                 ) -> MiniChatHistoryOut:
    """История диалога сессии, при ``limit`` — только последние реплики."""
    service = dependencies.get_mini_chat_service()
    try:
        result = service.get_history(session_id, limit=limit)
    except (MiniChatSessionError, ValueError) as exc:
        raise _http_error(exc) from exc
    return MiniChatHistoryOut(**result)


@router.delete(
    "/mini-chat/sessions/{session_id}",
    response_model=MiniChatCloseOut,
    summary="Закрыть сессию мини-чата",
    description=(
        "Идемпотентно удаляет реплики сессии и возвращает их число. Четыре ключа "
        "памяти задачи остаются в рабочей памяти: удаления записей рабочей памяти "
        "в API дня 11 нет, и повторный закрытой сессии возвращает ``deleted=0``."
    ),
)
def close_session(session_id: str) -> MiniChatCloseOut:
    """Закрытие сессии: удалены реплики, память задачи сохранена."""
    service = dependencies.get_mini_chat_service()
    return MiniChatCloseOut(**service.end_session(session_id))
