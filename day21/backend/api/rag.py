"""Роутер API: режим RAG — поиск по корпусу, ответ с контекстом и без.

Шесть эндпоинтов: ``POST /rag/query`` (ответ по корпусу или без него — переключатель
``use_rag``), ``POST /rag/compare`` (оба ответа на один вопрос), ``POST
/rag/compare_modes`` (тот же вопрос по нескольким режимам отбора: базовый гибридный
поиск, переформулировка, реранкер, реранкер с порогом), ``GET /rag/config``
(готовность корпуса, лимиты режима и каталог режимов), ``GET /rag/demo-questions``
(контрольные вопросы демо) и ``POST /rag/demo-run`` (прогон демо с источниками,
цитатами и режимом «не знаю»). Отдельного эндпоинта поиска
нет: интерфейсу нужен ответ модели, а выдача поиска приходит в нём же полем ``sources``.

Перевод отказов в коды ответов: ``RAGRejected`` с кодом ``bad_strategy``,
``empty_query`` или ``bad_mode`` — 400 (ошибка запроса), ``index_empty`` — 409 (корпус
ещё не проиндексирован), ``RAGUpstreamError`` — 502 (вызов модели не удался после всех
повторов и откат на ответ без RAG тоже).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..domain import rag_demo, rag_filter, rag_mode
from ..schemas import (
    RagCompareIn,
    RagCompareOut,
    RagConfigOut,
    RagDemoIn,
    RagDemoOut,
    RagDemoQuestionsOut,
    RagModesIn,
    RagModesOut,
    RagQueryIn,
    RagQueryOut,
)
from ..services import rag_demo_service
from ..services.rag_errors import RAGRejected, RAGUpstreamError

router = APIRouter()

#: Коды причин, которые говорят про сам запрос, а не про состояние корпуса.
_BAD_REQUEST_REASONS = (rag_mode.REASON_RAG_BAD_STRATEGY,
                        rag_mode.REASON_RAG_EMPTY_QUERY,
                        rag_filter.REASON_RAG_BAD_MODE)


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
                                       payload.strategy,
                                       rewrite=payload.rewrite,
                                       rerank=payload.rerank,
                                       min_score=payload.min_score,
                                       top_k_candidates=payload.top_k_candidates)
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


@router.post(
    "/rag/compare_modes",
    response_model=RagModesOut,
    summary="Сравнение режимов отбора на одном вопросе",
    description=(
        "Один вопрос — до четырёх записей: базовый гибридный поиск дня 22, "
        "переформулировка запроса моделью, реранкер кросс-энкодером и реранкер с "
        "порогом отсечения. У каждой записи свои источники, баллы отбора и числа "
        "«сколько кандидатов было до фильтра / сколько осталось»: интерфейс и отчёт "
        "показывают, что именно добавляет каждая ступень."
    ),
)
def rag_compare_modes(payload: RagModesIn) -> RagModesOut:
    """Ответы по нескольким режимам отбора: одна ступень отбора на запись."""
    service = dependencies.get_rag_service()
    try:
        result = service.compare_modes(
            payload.question, top_k=payload.top_k, strategy=payload.strategy,
            min_score=payload.min_score,
            top_k_candidates=payload.top_k_candidates, modes=payload.modes)
    except RAGRejected as exc:
        raise _rejected(exc) from exc
    except RAGUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RagModesOut(**result)


@router.get(
    "/rag/demo-questions",
    response_model=RagDemoQuestionsOut,
    summary="Контрольные вопросы RAG-демо",
    description=(
        "Десять вопросов демо-сценария: у каждого ожидаемый режим и, для вопросов "
        "с ответом в корпусе, ожидаемые источники. Список читает раздел «RAG-демо» "
        "интерфейса и скрипт отчёта."
    ),
)
def rag_demo_questions() -> RagDemoQuestionsOut:
    """Контрольные вопросы демо-сценария."""
    return RagDemoQuestionsOut(questions=rag_demo_service.questions())


@router.post(
    "/rag/demo-run",
    response_model=RagDemoOut,
    summary="Прогон RAG-демо: источники, цитаты, режим «не знаю»",
    description=(
        "Прогон контрольных вопросов через режим RAG: на каждый вопрос — режим, "
        "ответ, источники, цитаты, уверенность и вердикт «совпало ли с ожиданием», "
        "плюс сводка по набору. Пустое тело — прогнать все вопросы, тело с "
        "``question`` — только один. Сбой одного вопроса становится строкой с "
        "вердиктом «ошибка модели», остальные вопросы всё равно отвечаются."
    ),
)
def rag_demo_run(payload: Optional[RagDemoIn] = None) -> RagDemoOut:
    """Прогон демо-вопросов: все или один по полю ``question``."""
    service = dependencies.get_rag_service()
    if payload is not None and payload.question:
        items = [item for item in rag_demo.load_questions()
                 if item.question == payload.question]
    else:
        items = None
    return RagDemoOut(**rag_demo_service.run_demo(service, items))
