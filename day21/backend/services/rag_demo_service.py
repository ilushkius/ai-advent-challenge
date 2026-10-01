"""Служба демо-прогона RAG (день 24): десять вопросов одним вызовом.

Один сбойный вопрос не срывает прогон: ошибка становится строкой-предупреждением
в таблице, остальные вопросы отвечаются. Сводка считается здесь же — отчёт и
интерфейс читают одни и те же числа, а не считают их каждый по-своему.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from ..domain import rag_demo, rag_quotes
from .rag_errors import RAGError

__all__ = ["demo_row", "questions", "run_demo", "summary"]


def questions() -> list[dict]:
    """Список контрольных вопросов для API и интерфейса."""
    return [rag_demo.question_as_dict(item) for item in rag_demo.load_questions()]


def run_demo(service, questions: Optional[Iterable[Any]] = None) -> dict:
    """Прогон набора: строка на каждый вопрос плюс сводка.

    Пустой набор — пустые строки и нулевая сводка, а не исключение: интерфейс
    показывает это как «вопросов нет».
    """
    items = list(questions) if questions is not None else rag_demo.load_questions()
    rows = [demo_row(item, _answer(service, item)) for item in items]
    return {"rows": rows, "summary": summary(rows)}


def _answer(service, item) -> dict:
    """Ответ по вопросу; сбой вызова — строка-предупреждение, а не падение прогона."""
    try:
        return service.rag_query(item.question)
    except RAGError as exc:
        return _failure(item, exc)


def _failure(item, exc: Exception) -> dict:
    """Синтетическая запись упавшего вопроса: помечена ``fallback``."""
    return {
        "mode": rag_quotes.RAG_MODE_RAG,
        "question": item.question,
        "answer": "",
        "sources": [],
        "quotes": [],
        "quotes_verified": False,
        "confidence": 0.0,
        "chunks_used": 0,
        "context_tokens": 0,
        "tokens": None,
        "duration_ms": 0,
        "grounding": "",
        "fallback": True,
        "warning": str(exc),
    }


def demo_row(item, record: dict) -> dict:
    """Строка таблицы демо: режим, ответ, источники, цитаты и вердикт."""
    sources = list(record.get("sources") or [])
    return {
        "question": item.question,
        "expectation": item.expectation,
        "expected_mode": item.expected_mode,
        "mode": str(record.get("mode") or ""),
        "top_score": max(
            (float(source.get("vector_score") or 0.0) for source in sources), default=0.0
        ),
        "answer": str(record.get("answer") or ""),
        "sources": sources,
        "quotes": list(record.get("quotes") or []),
        "confidence": float(record.get("confidence") or 0.0),
        "quotes_verified": bool(record.get("quotes_verified")),
        "sources_expected": rag_demo.expected_found(sources, item),
        "verdict": rag_demo.verdict(item, record),
    }


def summary(rows: Iterable[Any]) -> dict:
    """Сводка по строкам: распределение режимов, источников, цитат и вердиктов."""
    data = list(rows or [])
    modes = [str(row.get("mode") or "") for row in data]
    matched = (rag_demo.VERDICT_OK, rag_demo.VERDICT_DONT_KNOW_OK)
    return {
        "total": len(data),
        "rag": modes.count(rag_quotes.RAG_MODE_RAG),
        "no_rag": modes.count(rag_quotes.RAG_MODE_NO_RAG),
        "dont_know": modes.count(rag_quotes.RAG_MODE_DONT_KNOW),
        "with_sources": sum(
            1 for row in data
            if row.get("mode") == rag_quotes.RAG_MODE_RAG and row.get("sources")
        ),
        "with_quotes": sum(1 for row in data if row.get("quotes")),
        "verified": sum(1 for row in data if row.get("quotes_verified")),
        "mismatches": sum(1 for row in data if row.get("verdict") not in matched),
    }
