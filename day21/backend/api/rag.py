"""Роутер API дня 22: режим RAG — поиск по корпусу, ответ с контекстом и без.

Три эндпоинта: ``POST /rag/query`` (ответ по корпусу или без него — переключатель
``use_rag``), ``POST /rag/compare`` (оба ответа на один вопрос) и ``GET /rag/config``
(готовность корпуса и лимиты режима). Отдельного эндпоинта поиска нет: интерфейсу
нужен ответ модели, а выдача поиска приходит в нём же полем ``sources``.

Перевод отказов в коды ответов: ``RAGRejected`` с кодом ``bad_strategy`` или
``empty_query`` — 400 (ошибка запроса), ``index_empty`` — 409 (корпус ещё не
проиндексирован), ``RAGUpstreamError`` — 502 (вызов модели не удался после всех
повторов и откат на ответ без RAG тоже).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..domain import rag_mode
from ..schemas import (
    RagCompareIn,
    RagCompareOut,
    RagConfigOut,
    RagQueryIn,
    RagQueryOut,
)
from ..services.rag_service import RAGRejected, RAGUpstreamError

router = APIRouter()

#: Коды причин, которые говорят про сам запрос, а не про состояние корпуса.
_BAD_REQUEST_REASONS = (rag_mode.REASON_RAG_BAD_STRATEGY,
                        rag_mode.REASON_RAG_EMPTY_QUERY)


def _rejected(exc: RAGRejected) -> HTTPException:
    """Отказ режима RAG в HTTP: 400 — про запрос, 409 — про непроиндексированный корпус."""
    code = 400 if exc.reason_code in _BAD_REQUEST_REASONS else 409
    return HTTPException(status_code=code, detail=exc.message)


@router.post(
    "/rag/query",
    response_model=RagQueryOut,
    summary="Ответ по корпусу RAG или без него",
    description=(
        "С включённым RAG вопрос ищется в корпусе документов, найденные фрагменты "
        "подмешиваются в промпт, ответ приходит вместе с использованными "
        "источниками и оценкой опоры на контекст. Выключенный RAG задаёт тот же "
        "вопрос модели без контекста — это база сравнения для интерфейса и отчёта. "
        "Если вызов с контекстом не удался после всех повторов, возвращается ответ "
        "без RAG с признаком ``fallback`` и предупреждением."
    ),
)
def rag_query(payload: RagQueryIn) -> RagQueryOut:
    """Ответ модели: с найденным контекстом корпуса или без него."""
    service = dependencies.get_rag_service()
    try:
        if payload.use_rag:
            result = service.rag_query(payload.question, payload.top_k,
                                       payload.strategy)
        else:
            result = service.no_rag_query(payload.question)
    except RAGRejected as exc:
        raise _rejected(exc) from exc
    except RAGUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RagQueryOut(**result)


@router.get(
    "/rag/config",
    response_model=RagConfigOut,
    summary="Состояние корпуса RAG и лимиты режима",
    description=(
        "Готовность режима: сколько документов и страниц в корпусе, сколько чанков "
        "лежит в обеих стратегиях, есть ли индексы. Интерфейс показывает эти числа "
        "над полем вопроса, чтобы отказ 409 не был неожиданным."
    ),
)
def rag_config() -> RagConfigOut:
    """Готовность корпуса, чанки обеих стратегий и лимиты контекста."""
    return RagConfigOut(**dependencies.get_rag_service().config())


@router.post(
    "/rag/compare",
    response_model=RagCompareOut,
    summary="Сравнение ответов с RAG и без него",
    description=(
        "Один вопрос — два ответа: без контекста корпуса и с ним, вместе с "
        "источниками, расходом и оценкой опоры. Сначала считается ответ без RAG: "
        "сбой режима с контекстом не должен отнимать базу сравнения."
    ),
)
def rag_compare(payload: RagCompareIn) -> RagCompareOut:
    """Оба ответа на один вопрос: база без контекста и ответ по корпусу."""
    service = dependencies.get_rag_service()
    try:
        result = service.compare(payload.question, payload.top_k, payload.strategy)
    except RAGRejected as exc:
        raise _rejected(exc) from exc
    except RAGUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RagCompareOut(**result)
