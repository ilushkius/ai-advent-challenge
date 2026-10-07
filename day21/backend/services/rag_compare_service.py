"""Прогон сравнения провайдеров (день 28): один вопрос — два ответа.

Локальная модель отвечает первой, облако — второй: интерфейс и отчёт читают одну и
ту же запись строки, а поиск по корпусу в обоих случаях делает один и тот же
локальный retrieval (``RAGService.rag_query`` без провайдера поиска).

Сбой одного вызова не срывает прогон из десяти вопросов: строка приходит с режимом
``error`` и предупреждением. Ловится только ``RAGUpstreamError`` — отказы запроса
(``RAGRejected``: пустой вопрос, незнакомая стратегия, пустой индекс) должны дойти до
роутера и стать 400/409, а не молча превратиться в строку таблицы.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from ..domain import llm_provider, rag_compare, rag_demo
from .rag_errors import RAGUpstreamError

__all__ = ["CLOUD_PROVIDER", "LOCAL_PROVIDER", "run"]

#: Порядок ответов в строке: сначала локальный, потом облачный.
LOCAL_PROVIDER = llm_provider.PROVIDER_LOCAL
CLOUD_PROVIDER = llm_provider.PROVIDER_DEEPSEEK


def run(service: Any, questions: Optional[Iterable[str]] = None, *,
        top_k: Optional[int] = None, strategy: Optional[str] = None) -> dict:
    """Прогон набора: строка на каждый вопрос плюс сводка по строкам."""
    rows = [rag_compare.row(text,
                            _answer(service, text, LOCAL_PROVIDER, top_k, strategy),
                            _answer(service, text, CLOUD_PROVIDER, top_k, strategy))
            for text in _questions(questions)]
    return {"rows": rows, "summary": rag_compare.summary(rows)}


def _questions(questions: Optional[Iterable[str]]) -> List[str]:
    """Вопросы прогона: заданные списком или десять контрольных вопросов демо.

    Пустое поле запроса (``None``) и пустой список значат одно: прогонять нечего, и
    берётся набор демо — как у ``POST /rag/demo-run`` без тела.
    """
    if not questions:
        return [item.question for item in rag_demo.load_questions()]
    return [str(item).strip() for item in questions if str(item or "").strip()]


def _answer(service: Any, question: str, provider: str,
            top_k: Optional[int], strategy: Optional[str]) -> dict:
    """Ответ одного провайдера; сбой вызова — строка ``error``, а не падение прогона."""
    try:
        return service.rag_query(question, top_k, strategy, provider=provider)
    except RAGUpstreamError as exc:
        return _failure(question, provider, exc)


def _failure(question: str, provider: str, exc: Exception) -> dict:
    """Синтетическая запись упавшего вызова: те же поля, что у ответа ``RagQueryOut``."""
    return {"mode": "error", "question": question, "answer": "", "provider": provider,
            "fallback": True, "warning": str(exc), "grounding": "", "sources": [],
            "quotes": [], "quotes_verified": False, "confidence": 0.0,
            "chunks_used": 0, "context_tokens": 0, "tokens": None, "duration_ms": 0,
            "query_used": "", "rewritten": False, "reranked": False, "candidates": 0,
            "kept": 0, "min_score": None, "top_k_candidates": 0,
            "rewrite_warning": "", "rerank_warning": "", "filter_warning": ""}
