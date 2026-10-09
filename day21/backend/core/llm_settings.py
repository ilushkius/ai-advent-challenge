"""Настройки провайдеров ответа LLM (дни 26 и 30): локальная Ollama и удалённая модель.

Вынесено из ``config`` (день 30), когда конфигурация упёрлась в предел 400 строк:
у этих констант своя тема — адрес, модель, таймаут и границы запросов двух
провайдеров, ни на что другое дня они не влияют. ``config`` реэкспортирует имена,
поэтому код и тесты продолжают читать их как ``config.LOCAL_LLM_URL`` /
``config.REMOTE_LLM_URL``.

Значения читаются на импорте модуля: окружение процесса → ``day21/.env`` → значение
по умолчанию. Для удалённой модели (день 30) адрес по умолчанию пуст намеренно:
это туннель Cloudflare к Ollama в Google Colab, он живёт часы, поэтому его
подставляют в UI или в ``.env``, а не в код.
"""
from __future__ import annotations

import os

from .env_file import read_env_value

__all__ = [
    "LLM_PROVIDER", "LLM_PROVIDER_DEFAULT",
    "LOCAL_LLM_DEMO_MAX_TOKENS", "LOCAL_LLM_MODEL", "LOCAL_LLM_MODEL_DEFAULT",
    "LOCAL_LLM_TIMEOUT", "LOCAL_LLM_URL", "LOCAL_LLM_URL_DEFAULT",
    "REMOTE_LLM_API_KEY", "REMOTE_LLM_API_KEY_DEFAULT", "REMOTE_LLM_API_KEY_MAX",
    "REMOTE_LLM_CONNECT_MAX_TOKENS", "REMOTE_LLM_DEMO_MAX_TOKENS",
    "REMOTE_LLM_MAX_CONTEXT", "REMOTE_LLM_MAX_CONTEXT_DEFAULT",
    "REMOTE_LLM_MAX_CONTEXT_MAX", "REMOTE_LLM_MAX_CONTEXT_MIN",
    "REMOTE_LLM_MODEL", "REMOTE_LLM_MODEL_DEFAULT", "REMOTE_LLM_MODEL_MAX",
    "REMOTE_LLM_RATE_LIMIT", "REMOTE_LLM_RATE_LIMIT_DEFAULT",
    "REMOTE_LLM_RATE_LIMIT_MAX", "REMOTE_LLM_RATE_LIMIT_MIN",
    "REMOTE_LLM_RATE_WINDOW_SECONDS", "REMOTE_LLM_TIMEOUT",
    "REMOTE_LLM_URL", "REMOTE_LLM_URL_DEFAULT", "REMOTE_LLM_URL_MAX",
]


def _env(name: str) -> str:
    """Значение настройки: окружение процесса важнее ``day21/.env``."""
    raw = os.environ.get(name)
    return str(raw if raw is not None else read_env_value(name) or "").strip()


def _int_env(name: str, default: int) -> int:
    """Целое из окружения; пустое или нечисловое значение — значение по умолчанию."""
    try:
        return int(_env(name))
    except ValueError:
        return default


# --- Локальная LLM (день 26) ---------------------------------------------------
# Второй провайдер ответа — Ollama по HTTP; `provider` в запросе перекрывает дефолт.
LLM_PROVIDER_DEFAULT = "deepseek"
LOCAL_LLM_MODEL_DEFAULT = "qwen2.5-coder:14b"
LOCAL_LLM_URL_DEFAULT = "http://localhost:11434"
LLM_PROVIDER = (_env("LLM_PROVIDER") or LLM_PROVIDER_DEFAULT).lower()
LOCAL_LLM_MODEL = _env("LOCAL_LLM_MODEL") or LOCAL_LLM_MODEL_DEFAULT
LOCAL_LLM_URL = (_env("LOCAL_LLM_URL") or LOCAL_LLM_URL_DEFAULT).rstrip("/")
# Таймаут: локальная модель отвечает десятками секунд, включая прогрев весов.
LOCAL_LLM_TIMEOUT = 120.0
# Пределы ответа демо-запросов локальной модели по типу задачи (fact/logic/code).
LOCAL_LLM_DEMO_MAX_TOKENS = {"fact": 128, "logic": 256, "code": 800}

# --- Удалённая локальная LLM (день 30) -----------------------------------------
# Тот же Ollama, но развёрнутый в Google Colab (бесплатный GPU T4) и опубликованный
# через Cloudflare Tunnel: сервис OpenAI-совместимый, поэтому клиент ходит в
# ``{base_url}/chat/completions`` и ``{base_url}/models``. Ключ не проверяется
# (Ollama без авторизации), но его место в шапке запроса оставлено: без строки
# некоторые OpenAI-совместимые шлюзы отвечают 401.
REMOTE_LLM_URL_DEFAULT = ""
REMOTE_LLM_MODEL_DEFAULT = "qwen2.5-coder:7b"
REMOTE_LLM_API_KEY_DEFAULT = "ollama"
REMOTE_LLM_RATE_LIMIT_DEFAULT = 10
REMOTE_LLM_MAX_CONTEXT_DEFAULT = 4096
#: Границы ручек интерфейса: их же проверяют Pydantic-схемы запросов дня 30.
REMOTE_LLM_RATE_LIMIT_MIN = 1
REMOTE_LLM_RATE_LIMIT_MAX = 30
REMOTE_LLM_MAX_CONTEXT_MIN = 1024
REMOTE_LLM_MAX_CONTEXT_MAX = 8192
#: Окно клиентского счётчика частоты: «N запросов в минуту».
REMOTE_LLM_RATE_WINDOW_SECONDS = 60.0
#: Таймаут: удалённая модель отвечает через туннель десятками секунд.
REMOTE_LLM_TIMEOUT = 120.0
#: Пределы ответа демо-запросов удалённой модели (как у локальной, день 26).
REMOTE_LLM_DEMO_MAX_TOKENS = {"fact": 128, "logic": 256, "code": 800}
#: Ответ-«пинг» шага про частоту: он нужен как факт вызова, а не как текст.
REMOTE_LLM_CONNECT_MAX_TOKENS = 8
#: Длины полей запроса (Pydantic-схемы; адрес туннеля длиннее локального).
REMOTE_LLM_URL_MAX = 500
REMOTE_LLM_MODEL_MAX = 64
REMOTE_LLM_API_KEY_MAX = 128

REMOTE_LLM_URL = (_env("REMOTE_LLM_URL") or REMOTE_LLM_URL_DEFAULT).rstrip("/")
REMOTE_LLM_MODEL = _env("REMOTE_LLM_MODEL") or REMOTE_LLM_MODEL_DEFAULT
REMOTE_LLM_API_KEY = _env("REMOTE_LLM_API_KEY") or REMOTE_LLM_API_KEY_DEFAULT
REMOTE_LLM_RATE_LIMIT = _int_env("REMOTE_LLM_RATE_LIMIT", REMOTE_LLM_RATE_LIMIT_DEFAULT)
REMOTE_LLM_MAX_CONTEXT = _int_env("REMOTE_LLM_MAX_CONTEXT", REMOTE_LLM_MAX_CONTEXT_DEFAULT)
