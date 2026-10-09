"""Провайдер ответа LLM (день 26): облако DeepSeek или локальная модель Ollama.

Здесь только имена провайдеров и их подписи: ни HTTP, ни базы, ни выбора клиента —
клиент собирает ``services/llm_factory``, а значение по умолчанию берётся из
``config.LLM_PROVIDER`` в МОМЕНТ ВЫЗОВА, а не на импорте: тест и перезапущенный
бэкенд после правки ``.env`` видят актуальное значение.
"""
from __future__ import annotations

from typing import Optional

from ..core import config

#: Имена провайдеров: они уходят в поле ``provider`` запросов и ответов API.
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_LOCAL = "local"
#: Удалённая локальная модель (день 30): тот же Ollama, но развёрнутый в Google
#: Colab и опубликованный через Cloudflare Tunnel. Сервис OpenAI-совместимый,
#: поэтому клиент свой (``remote_llm_client``), а не ``local_llm_client`` с
#: ``/api/chat``.
PROVIDER_REMOTE = "remote"
PROVIDERS = (PROVIDER_DEEPSEEK, PROVIDER_LOCAL, PROVIDER_REMOTE)

#: Подписи для интерфейса: их отдаёт ``GET /llm/provider``, чтобы UI не дублировал
#: список провайдеров своими литералами.
PROVIDER_LABELS = {
    PROVIDER_DEEPSEEK: "🌐 DeepSeek (облако)",
    PROVIDER_LOCAL: "🖥 Local LLM (Ollama)",
    PROVIDER_REMOTE: "🛰 Удалённая LLM (Colab)",
}

#: Кого предлагает переключатель интерфейса (боковая панель песочницы и мини-чата):
#: удалённая модель дня 30 в него не входит — у неё свой раздел со своим адресом
#: туннеля, который живёт часы. Список задан данными, а не в разметке: два радио
#: (``sidebar``, ``mini_chat/panels``) читают его отсюда.
PICKER_PROVIDERS = (PROVIDER_DEEPSEEK, PROVIDER_LOCAL)

__all__ = ["PICKER_PROVIDERS", "PROVIDER_DEEPSEEK", "PROVIDER_LABELS",
           "PROVIDER_LOCAL", "PROVIDER_REMOTE", "PROVIDERS", "label",
           "normalize_provider", "resolve"]


def normalize_provider(raw: Optional[str] = None) -> str:
    """Имя провайдера из строки конфига: пробелы и регистр не значат ничего.

    Пустое значение — обычный чат облаком (``deepseek``): так отсутствие строки в
    ``.env`` не меняет поведение дня 21.
    """
    name = str(raw or "").strip().lower()
    return name or PROVIDER_DEEPSEEK


def resolve(provider: Optional[str] = None) -> str:
    """Провайдер запроса: явный аргумент → ``config.LLM_PROVIDER`` → ``deepseek``.

    Пустой явный аргумент считается отсутствующим (в теле запроса это «поле не
    задано»). Незнакомое имя — ``ValueError``: роутер переводит его в 400, а
    молчаливая подмена показала бы в ответе не того провайдера, который отвечал.
    """
    raw = provider if str(provider or "").strip() else config.LLM_PROVIDER
    name = normalize_provider(raw)
    if name not in PROVIDERS:
        raise ValueError(f"Неизвестный провайдер LLM: {name!r}. Доступны: "
                         f"{', '.join(PROVIDERS)}")
    return name


def label(name: str) -> str:
    """Подпись провайдера для интерфейса; незнакомое имя возвращается как есть."""
    return PROVIDER_LABELS.get(str(name or ""), str(name or ""))
