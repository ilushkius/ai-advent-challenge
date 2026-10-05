"""Фабрика клиента LLM по провайдеру (день 26).

Одно место, где имя провайдера превращается в клиента: ``local`` — HTTP-клиент
Ollama (``local_llm_client.LocalLLMClient``), ``deepseek`` — обёртка дня 21
(``llm_client.LLMClient``), которой вызывающий код передаёт фабрику SDK-клиента.

Одноимённая функция в ``llm_client`` — НЕ эта: ``llm_client.get_llm_client()``
отдаёт синглтон-обёртку DeepSeek для ``GET /llm/usage``, а
``llm_factory.get_llm_client(provider)`` собирает клиента выбранного провайдера.
Импорт всегда по пути модуля (``from .llm_factory import get_llm_client``):
в ``services/__init__.py`` функция не реэкспортируется, чтобы два имени одного
контракта не спорили друг с другом.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ..domain import llm_provider
from .llm_client import LLMClient
from .local_llm_client import LocalLLMClient

__all__ = ["get_llm_client"]


def get_llm_client(provider: Optional[str] = None, *, agent_id: Optional[str] = None,
                   client_factory: Optional[Callable[[], Any]] = None,
                   session_factory=None,
                   timeout: Optional[float] = None
                   ) -> Any:
    """Клиент выбранного провайдера: ``None`` — ``config.LLM_PROVIDER``.

    ``client_factory``/``session_factory`` нужны только облаку: у локальной модели
    нет ни ключа, ни журнала расходов, ни сессий, поэтому их отсутствие здесь не
    ошибка. Неизвестное имя провайдера — ``ValueError`` (роутер переводит в 400).
    """
    name = llm_provider.resolve(provider)
    if name == llm_provider.PROVIDER_LOCAL:
        return LocalLLMClient(agent_id=agent_id, timeout=timeout)
    return LLMClient(agent_id=agent_id, client_factory=client_factory,
                     session_factory=session_factory)
