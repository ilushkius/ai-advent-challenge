"""Фабрика клиента LLM по провайдеру (день 26).

Одно место, где имя провайдера превращается в клиента: ``local`` — HTTP-клиент
Ollama (``local_llm_client.LocalLLMClient``), ``remote`` — OpenAI-совместимый клиент
удалённой модели дня 30 (``remote_llm_client.RemoteLLMClient``), ``deepseek`` —
обёртка дня 21 (``llm_client.LLMClient``), которой вызывающий код передаёт фабрику
SDK-клиента.

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
from ..domain.local_tuning import TuningProfile
from .llm_client import LLMClient
from .local_llm_client import LocalLLMClient
from .remote_llm_client import RemoteLLMClient, RemoteSettings

__all__ = ["get_llm_client"]


def get_llm_client(provider: Optional[str] = None, *, agent_id: Optional[str] = None,
                   client_factory: Optional[Callable[[], Any]] = None,
                   session_factory=None,
                   timeout: Optional[float] = None,
                   profile: Optional[TuningProfile] = None,
                   remote_settings: Optional[RemoteSettings] = None
                   ) -> Any:
    """Клиент выбранного провайдера: ``None`` — ``config.LLM_PROVIDER``.

    ``client_factory``/``session_factory`` нужны только облаку: у локальной модели
    нет ни ключа, ни журнала расходов, ни сессий, поэтому их отсутствие здесь не
    ошибка. Неизвестное имя провайдера — ``ValueError`` (роутер переводит в 400).

    ``profile`` (день 29) задаёт модель и окно контекста (``num_ctx``) локального
    клиента: профиль настройки — единственное место, где эти два параметра связаны,
    иначе смена профиля на лету перезагружала бы веса Ollama. ``None`` — поведение
    дня 26 (модель конфига, окно по умолчанию).

    ``remote_settings`` (день 30) — настройки удалённой модели (адрес туннеля,
    модель, ключ, частота, окно контекста); ``None`` — значения ``day21/.env``.
    Профиль дня 29 сюда не применяется: он описывает кванты и окно локальной
    Ollama, а у удалённого клиента свои ручки.
    """
    name = llm_provider.resolve(provider)
    if name == llm_provider.PROVIDER_REMOTE:
        return RemoteLLMClient(settings=remote_settings, timeout=timeout,
                               agent_id=agent_id)
    if name == llm_provider.PROVIDER_LOCAL:
        return LocalLLMClient(agent_id=agent_id, timeout=timeout,
                              model=(profile.model if profile else None),
                              num_ctx=(profile.num_ctx if profile else None))
    return LLMClient(agent_id=agent_id, client_factory=client_factory,
                     session_factory=session_factory)
