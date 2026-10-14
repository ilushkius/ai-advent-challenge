"""Роутер API: ассистент поддержки пользователей (день 33) — ``/support/*``.

Пять эндпоинтов одного раздела: вопрос с контекстом клиента (``/support/ask``),
каталог пользователей и один профиль, тикеты клиента и один тикет. Пути абсолютные
(префиксов у роутеров дня нет), служба берётся через
``dependencies.get_support_service()`` — не прямой импорт: тесты подменяют её одной
строкой в ``backend.api.main``.

Коды ответов. Вопрос: 400 — пустой вопрос или незнакомый провайдер, 502 — сбой
модели, когда ни одного блока контекста не собралось. **Панельные** списки
(``/support/users``, ``/support/tickets?user_id=``) отвечают 200 ВСЕГДА: селекторы
раздела показывают причину строкой ``error``, а не падают — недоступный MCP-сервер
поднимается лениво и его отсутствие штатно. **Одиночная** запись отвечает 404, если
записи нет (текст ``error`` от инструмента), и 502, если сервер не поднялся.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..core import dependencies
# Схемы берутся из своего модуля, а не из пакета ``..schemas``: ``schemas/__init__.py``
# стоит на пределе 400 строк, и дни 30–32 сделали так же.
from ..schemas.support import (SupportAskIn, SupportAskOut, SupportTicketOut,
                              SupportTicketsOut, SupportUserListOut, SupportUserOut)
from ..services.rag_errors import RAGUpstreamError
from ..services.support_service import SupportMCPError

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    """Доменное исключение поддержки в HTTP-ответ: 400 — запрос, 502 — сбой соединения."""
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.post(
    "/support/ask",
    response_model=SupportAskOut,
    summary="Ответ ассистента поддержки по FAQ, профилю и тикету",
    description=(
        "Собирает контекст вопроса из трёх источников: фрагменты документации "
        "поддержки (RAG-индекс корпуса: FAQ, разборы симптомов, справочник API), "
        "профиль клиента (``user_id``) и его тикет (``ticket_id``) из MCP-сервера "
        "``support_server``, а также раздел продукта, определённый по словам вопроса. "
        "Тикет знает своего владельца: если ``user_id`` не передан, профиль "
        "подтягивается из тикета. Ответ содержит источники, контекст клиента, вызовы "
        "инструментов и предупреждения отказов; недоступная модель возвращается "
        "честным текстом в поле answer. 400: пустой вопрос или незнакомый провайдер."
    ),
)
def ask_support(payload: SupportAskIn) -> SupportAskOut:
    """Ответ по вопросу клиента: текст, источники RAG и контекст из MCP."""
    service = dependencies.get_support_service()
    try:
        result = service.answer(payload.question, payload.user_id or None,
                                payload.ticket_id or None, payload.provider or None)
    except (ValueError, RAGUpstreamError) as exc:
        raise _http_error(exc) from exc
    return SupportAskOut(**result)


@router.get(
    "/support/users",
    response_model=SupportUserListOut,
    summary="Каталог пользователей поддержки (MCP)",
    description=(
        "Вызывает ``list_users`` сервера поддержки: селектор пользователей раздела "
        "наполняется из MCP, а не из константного списка идентификаторов. Всегда 200: "
        "недоступный сервер заполняет поле ``error``, а поля ``count``/``users`` "
        "остаются пустыми."
    ),
)
def list_support_users() -> SupportUserListOut:
    """Каталог пользователей по инструменту ``list_users`` (всегда 200)."""
    service = dependencies.get_support_service()
    return SupportUserListOut(**service.users())


@router.get(
    "/support/users/{user_id}",
    response_model=SupportUserOut,
    summary="Профиль клиента поддержки (MCP)",
    description=(
        "Вызывает ``get_user`` сервера поддержки. 404 — записи нет (текст причины из "
        "инструмента, ``not found``), 502 — MCP-сервер не поднялся. Одиночная запись "
        "не отвечает 200 на несуществующий профиль: ссылка на несуществующего клиента "
        "должна быть видна клиенту как ошибка."
    ),
)
def read_support_user(user_id: str) -> SupportUserOut:
    """Профиль клиента по инструменту ``get_user`` (404 — записи нет)."""
    try:
        result = dependencies.get_support_service().user(user_id)
    except SupportMCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result["user"] is None:
        raise HTTPException(status_code=404,
                            detail=result["error"] or f"Пользователь {user_id} не найден")
    return SupportUserOut(**result["user"])


@router.get(
    "/support/tickets",
    response_model=SupportTicketsOut,
    summary="Тикеты клиента поддержки (MCP)",
    description=(
        "Вызывает ``list_user_tickets`` сервера поддержки: список тикетов клиента для "
        "селектора раздела — тема, статус, приоритет и число сообщений без истории. "
        "Всегда 200: у ненайденного клиента ``count=0`` и ``error=not found``, у "
        "недоступного сервера — текст причины в ``error``."
    ),
)
def list_support_tickets(
    user_id: str = Query(..., min_length=1, max_length=64,
                         description="Идентификатор клиента (напр. user_003)"),
) -> SupportTicketsOut:
    """Тикеты клиента по инструменту ``list_user_tickets`` (всегда 200)."""
    service = dependencies.get_support_service()
    return SupportTicketsOut(**service.user_tickets(user_id))


@router.get(
    "/support/tickets/{ticket_id}",
    response_model=SupportTicketOut,
    summary="Тикет клиента целиком (MCP)",
    description=(
        "Вызывает ``get_ticket`` сервера поддержки и отдаёт тикет целиком: тему, "
        "статус, приоритет, дату и историю сообщений. 404 — тикета нет, 502 — "
        "MCP-сервер не поднялся."
    ),
)
def read_support_ticket(ticket_id: str) -> SupportTicketOut:
    """Тикет по инструменту ``get_ticket`` (404 — записи нет)."""
    try:
        result = dependencies.get_support_service().ticket(ticket_id)
    except SupportMCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result["ticket"] is None:
        raise HTTPException(status_code=404,
                            detail=result["error"] or f"Тикет {ticket_id} не найден")
    return SupportTicketOut(**result["ticket"])
