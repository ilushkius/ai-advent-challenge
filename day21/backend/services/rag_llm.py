"""Обвязка вызова модели в режиме RAG: повторы, текст ответа и расход (день 22).

Вынесено из ``rag_service`` (день 23), чтобы служба не росла за предел строк: здесь
технические подробности клиента, а не правила отбора фрагментов. Повторы живут тут
же, чтобы переформулировка запроса (день 23) шла через ту же политику, что и ответ.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from shared.logging_utils import get_logger

from ..domain import rag_mode
from .llm_client import LLMCallResult
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["call_with_retry", "response_text", "usage_dict"]


def call_with_retry(sleep: Callable[[float], None],
                    func: Callable[..., LLMCallResult],
                    **kwargs: Any) -> LLMCallResult:
    """Вызов модели с повторами: последний провал — ``RAGUpstreamError``.

    Пауза между попытками растёт по ``RAG_RETRY_BACKOFF``: сбой сети не говорит
    о вопросе ничего, и первый же таймаут не должен выбрасывать строку отчёта.
    """
    last: Optional[Exception] = None
    for attempt in range(rag_mode.RAG_LLM_ATTEMPTS):
        if attempt:
            sleep(rag_mode.RAG_RETRY_SECONDS
                  * (rag_mode.RAG_RETRY_BACKOFF ** (attempt - 1)))
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001 — повторяем любой сбой вызова
            last = exc
            logger.warning("RAG: попытка %d из %d не удалась: %s",
                           attempt + 1, rag_mode.RAG_LLM_ATTEMPTS, exc)
    raise RAGUpstreamError(f"RAG-запрос не выполнен: {last}") from last


def response_text(result: LLMCallResult) -> str:
    """Текст ответа модели: пустой ответ — пустая строка, а не ошибка."""
    choices = getattr(result.response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    return str(getattr(message, "content", "") or "").strip()


def usage_dict(result: LLMCallResult) -> Optional[dict]:
    """Расход вызова: те же поля, что у ``LLMCallResult.to_dict``, без типа задачи."""
    if result is None:
        return None
    return {
        "model": result.model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cache_hit_tokens": result.cache_hit_tokens,
        "cache_miss_tokens": result.cache_miss_tokens,
        "cache_hit_percent": result.cache_hit_percent,
        "cost_estimate": result.cost_estimate,
    }
