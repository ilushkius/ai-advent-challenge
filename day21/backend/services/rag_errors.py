"""Отказы режима RAG: коды причин и исключения службы (день 22).

Модуль-лист без зависимостей от служб: его импортируют и роутер (``backend/api/rag``),
и модули службы, поэтому цикла импорта здесь быть не может. ``RAGRejected`` несёт код
причины (``bad_strategy``, ``empty_query``, ``index_empty``) и переводится роутером в
400/409, ``RAGUpstreamError`` — в 502.
"""
from __future__ import annotations

__all__ = ["RAGError", "RAGRejected", "RAGUpstreamError"]


class RAGError(Exception):
    """Базовая ошибка режима RAG."""


class RAGRejected(RAGError):
    """Отказ режима RAG: код причины переводится роутером в HTTP-статус."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


class RAGUpstreamError(RAGError):
    """Вызов модели не удался после всех повторов (роутер отвечает 502)."""
