"""Записи ответа режима RAG: фрагмент-источник и отчёт о ступенях отбора (день 23).

Служба отдаёт наружу словари, а не объекты отбора: схемы API, скрипт отчёта и
интерфейс читают одни и те же поля. Переводом ``RAGStages`` и хита индекса в эти
словари занимается этот модуль — иначе служба росла бы за предел строк, а форма
ответа расползлась бы по вызовам.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..domain import rag_filter
from .rag_retrieval import RAGStages

__all__ = ["selection", "source"]


def source(hit: Dict[str, Any]) -> dict:
    """Ссылка на использованный фрагмент: баллы отбора, без текста чанка.

    ``score`` — балл, по которому фрагмент отобран и отсортирован: балл реранкера,
    если он считался, иначе гибридный балл дня 22.
    """
    rerank_score = hit.get("rerank_score")
    return {
        "source": str(hit.get("source") or ""),
        "title": str(hit.get("title") or ""),
        "section": str(hit.get("section") or ""),
        "chunk_id": str(hit.get("chunk_id") or ""),
        "score": round(float(rerank_score if rerank_score is not None
                             else hit.get("score") or 0.0), 4),
        "vector_score": round(float(hit.get("vector_score") or 0.0), 4),
        "lexical_score": round(float(hit.get("lexical_score") or 0.0), 4),
        "rerank_score": (None if rerank_score is None
                         else round(float(rerank_score), 4)),
    }


def selection(stages: Optional[RAGStages]) -> dict:
    """Отчёт о ступенях отбора: в режиме без RAG все поля — значения по умолчанию."""
    if stages is None:
        return {"query_used": "", "rewritten": False, "reranked": False,
                "candidates": 0, "kept": 0, "min_score": None,
                "top_k_candidates": 0, "rewrite_warning": "",
                "rerank_warning": "", "filter_warning": ""}
    empty = bool(stages.min_score is not None and stages.candidates
                 and not stages.hits)
    return {
        "query_used": stages.query,
        "rewritten": bool(stages.query != stages.question),
        "reranked": stages.reranked,
        "candidates": len(stages.candidates),
        "kept": len(stages.hits),
        "min_score": stages.min_score,
        "top_k_candidates": stages.candidate_limit,
        "rewrite_warning": stages.rewrite_warning,
        "rerank_warning": stages.rerank_warning,
        "filter_warning": (rag_filter.filtered_empty_warning(stages.min_score)
                           if empty else ""),
    }
