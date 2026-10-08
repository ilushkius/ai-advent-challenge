"""Обвязка вызова модели в режиме RAG: клиент, повторы, текст ответа и расход.

Вынесено из ``rag_service`` (день 23), чтобы служба не росла за предел строк: здесь
технические подробности клиента, а не правила отбора фрагментов. Повторы живут тут
же, чтобы переформулировка запроса (день 23) шла через ту же политику, что и ответ.
Фабрика клиента DeepSeek (``make_rag_client``) переехала сюда по той же причине
(день 26): ключ и адрес провайдера — деталь клиента, а не режима RAG.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain import llm_provider, rag_mode
from ..domain.local_tuning import TuningProfile
from . import llm_factory
from .llm_client import LLMCallResult
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["answer", "call_with_retry", "client_for", "completion_tokens",
           "make_rag_client", "response_text", "usage_dict"]


def client_for(cache: dict, provider: Optional[str], profile: Optional[TuningProfile],
               *, stub: Any = None, **kwargs: Any) -> Any:
    """Клиент пары «провайдер + профиль» (день 29): подменённый или из кэша службы.

    Профиль входит в ключ кэша: он несёт модель и ``num_ctx``, и клиент другой
    модели, взятый из кэша, заставил бы Ollama перезагружать веса на каждом шаге.
    ``stub`` — клиент из конструктора службы: при ``provider=None`` он важнее кэша
    (так тесты и скрипты подставляют заглушку).
    """
    if provider is None and stub is not None:
        return stub
    name = llm_provider.resolve(provider)
    key = f"{name}|{profile.key}" if profile is not None else name
    if key not in cache:
        cache[key] = llm_factory.get_llm_client(name, profile=profile, **kwargs)
    return cache[key]


def answer(sleep: Callable[[float], None], client: Any, *, system: str, context: str,
           question: str, agent_id: str,
           profile: Optional[TuningProfile] = None) -> Any:
    """Вызов модели по контексту: параметры профиля дня 29 или значения дня 26.

    Одна точка для RAG и мини-чата: профиль меняет системный промпт, температуру и
    предел ответа одинаково в обоих местах, а тип задачи остаётся ``chat``.
    """
    return call_with_retry(
        sleep, client.generate_with_context, system=system, context=context,
        question=question, task_type=config.LLM_TASK_CHAT, agent_id=agent_id,
        temperature=(profile.temperature if profile is not None else None),
        max_tokens=(profile.max_tokens if profile is not None else None))


def make_rag_client() -> Any:
    """Клиент DeepSeek для режима RAG: ключ резолвится в момент вызова.

    Как у проверки инвариантов: служба собирается на старте приложения, а ключ к
    моменту первого обращения к модели может быть ещё не задан.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


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


def response_text(result) -> str:
    """Текст ответа модели: пустой ответ — пустая строка, а не ошибка.

    Локальный провайдер отвечает словарём (``LocalLLMClient``), облачный —
    ``LLMCallResult``; различие форм живёт только здесь, поэтому RAG и мини-чат
    о провайдере не знают.
    """
    if isinstance(result, dict):
        return str(result.get("answer") or "").strip()
    choices = getattr(result.response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    return str(getattr(message, "content", "") or "").strip()


def usage_dict(result) -> Optional[dict]:
    """Расход вызова: те же поля, что у ``LLMCallResult.to_dict``, без типа задачи."""
    if result is None:
        return None
    if isinstance(result, dict):
        return dict(result.get("tokens") or {}) or None
    return {
        "model": result.model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cache_hit_tokens": result.cache_hit_tokens,
        "cache_miss_tokens": result.cache_miss_tokens,
        "cache_hit_percent": result.cache_hit_percent,
        "cost_estimate": result.cost_estimate,
    }


def completion_tokens(result) -> int:
    """Токенов в ответе: у ``LLMCallResult`` — атрибут, у локального словаря — из tokens."""
    if isinstance(result, dict):
        return int((result.get("tokens") or {}).get("completion_tokens") or 0)
    return int(getattr(result, "completion_tokens", 0) or 0)
