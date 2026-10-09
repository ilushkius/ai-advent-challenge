"""Удалённая локальная LLM (день 30): Ollama в Google Colab через Cloudflare Tunnel.

Тот же второй провайдер, что в дне 26, но развёрнут не на своей машине, а в
Colab (бесплатный GPU T4) и опубликован туннелем Cloudflare. Сервис
OpenAI-совместимый, поэтому запрос идёт в ``POST {base_url}/chat/completions``, а
проверка связи — в ``GET {base_url}/models``.

Чем клиент отличается от ``LocalLLMClient`` дня 26:

* формат OpenAI (``choices[0].message.content``, ``usage.prompt_tokens``) вместо
  ``/api/chat`` с ``prompt_eval_count``/``eval_count``;
* окно контекста уходит в ``options.num_ctx`` (расширение Ollama), а предел длины
  ответа — в стандартный ``max_tokens``;
* клиентский счётчик частоты: ``rate_limit`` запросов в минуту, на следующем —
  ``RateLimitExceeded`` (в API это 429). Ограничение стоит на стороне КЛИЕНТА, а не
  Ollama: это прямо сказано и в интерфейсе, и в отчёте, иначе цифра читалась бы как
  защита сервера.

Интерфейс вызовов общий с ``LocalLLMClient`` и ``LLMClient`` (``chat``,
``generate``, ``generate_with_context``), а ответ — словарь, который читают
помощники ``rag_llm``; поэтому третьим провайдером можно отвечать и в режиме RAG.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional, Sequence

import requests

from shared.logging_utils import get_logger

from ..core import config
from ..domain import llm_provider

logger = get_logger(__name__)

__all__ = ["RateLimitExceeded", "RemoteLLMClient", "RemoteLLMError", "RemoteSettings"]

#: Сколько символов тела ответа с ошибкой попадает в текст исключения.
ERROR_BODY_LIMIT = 200
#: Нуклеарная выборка по умолчанию: значение Ollama, а не «как получится».
DEFAULT_TOP_P = 0.9


class RemoteLLMError(RuntimeError):
    """Удалённый сервис недоступен или ответил ошибкой: роутеры переводят её в 502.

    ``status_code`` заполнен, когда ошибку вернул сервер: по нему роутер отличает
    отказ частоты (429) от прочих сбоев.
    """

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitExceeded(RemoteLLMError):
    """Предел частоты исчерпан: клиентский счётчик либо 429 от сервера."""

    def __init__(self, message: str, *, limit: int = 0,
                 window_seconds: float = 0.0) -> None:
        super().__init__(message, status_code=429)
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)


@dataclass(frozen=True)
class RemoteSettings:
    """Настройки удалённого клиента: адрес туннеля, модель, ключ, ручки интерфейса.

    Значения из UI приходят через ``from_values``: пустая строка и ноль означают
    «оставить как в конфиге», поэтому незаполненное поле не превращает адрес в
    пустую строку и не даёт нулевой предел частоты.
    """

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    rate_limit: int = 0
    max_context: int = 0
    timeout: float = config.REMOTE_LLM_TIMEOUT

    @classmethod
    def from_config(cls) -> "RemoteSettings":
        """Настройки из ``day21/.env`` (значения дня 30 в ``llm_settings``)."""
        return cls(base_url=config.REMOTE_LLM_URL, model=config.REMOTE_LLM_MODEL,
                   api_key=config.REMOTE_LLM_API_KEY,
                   rate_limit=config.REMOTE_LLM_RATE_LIMIT,
                   max_context=config.REMOTE_LLM_MAX_CONTEXT,
                   timeout=config.REMOTE_LLM_TIMEOUT)

    @classmethod
    def from_values(cls, *, url: Optional[str] = None, model: Optional[str] = None,
                    api_key: Optional[str] = None, rate_limit: Optional[int] = None,
                    max_context: Optional[int] = None,
                    timeout: Optional[float] = None) -> "RemoteSettings":
        """Настройки из запроса интерфейса поверх конфига.

        Пределы зажимаются в границы слайдеров дня 30 (``REMOTE_LLM_RATE_LIMIT_MIN``
        … 30 и 1024…8192): Pydantic-схема их уже проверила, а здесь стоит вторая
        линия — на случай вызова службы из скрипта без схемы.
        """
        base = cls.from_config()
        return cls(
            base_url=str(url or base.base_url).strip().rstrip("/"),
            model=str(model or base.model).strip(),
            api_key=str(api_key or base.api_key).strip(),
            rate_limit=_clamp(rate_limit, config.REMOTE_LLM_RATE_LIMIT_MIN,
                              config.REMOTE_LLM_RATE_LIMIT_MAX, base.rate_limit),
            max_context=_clamp(max_context, config.REMOTE_LLM_MAX_CONTEXT_MIN,
                               config.REMOTE_LLM_MAX_CONTEXT_MAX, base.max_context),
            timeout=float(base.timeout if timeout is None else timeout),
        )


def _clamp(value: Optional[int], low: int, high: int, fallback: int) -> int:
    """Значение из запроса в границах; пусто (``None``/0) — значение конфига."""
    if not value:
        return max(low, min(high, int(fallback) or low))
    return max(low, min(high, int(value)))


class RemoteLLMClient:
    """OpenAI-совместимый клиент удалённой Ollama: вызовы как у ``LocalLLMClient``.

    ``post``/``get`` — точки подмены HTTP в тестах: вызываются ровно как
    ``requests.post``/``requests.get`` (``url`` позиционно, ``json=``/``headers=``/
    ``timeout=`` по имени), поэтому офлайн-тест сети не открывает. ``agent_id``
    принимается и игнорируется: журнала расходов у удалённой модели нет, но
    сигнатура вызова остаётся общей с облачным клиентом.
    """

    def __init__(self, *, settings: Optional[RemoteSettings] = None,
                 timeout: Optional[float] = None, agent_id: Optional[str] = None,
                 post: Optional[Callable[..., Any]] = None,
                 get: Optional[Callable[..., Any]] = None) -> None:
        self.settings = settings or RemoteSettings.from_config()
        self.model = self.settings.model
        self.base_url = str(self.settings.base_url or "").rstrip("/")
        self.api_key = self.settings.api_key
        self.rate_limit = max(1, int(self.settings.rate_limit))
        self.max_context = max(1, int(self.settings.max_context))
        self.timeout = float(self.settings.timeout if timeout is None else timeout)
        self.agent_id = agent_id
        self._post = post or requests.post
        self._get = get or requests.get
        # Часы — атрибут, а не прямой `time.monotonic()`: тест подменяет их и
        # проверяет окно частоты без ожидания реальной минуты.
        self._now = time.monotonic
        self._calls: Deque[float] = deque()

    # ---------- частота запросов (клиентский счётчик) ----------
    def rate_limit_state(self) -> dict:
        """Сколько запросов в окне уже сделано: видно в интерфейсе и в отчёте."""
        self._prune()
        return {"limit": self.rate_limit, "used": len(self._calls),
                "window_seconds": config.REMOTE_LLM_RATE_WINDOW_SECONDS}

    def reset_rate_limit(self) -> None:
        """Обнулить счётчик: шаг про 429 начинается с чистой минуты."""
        self._calls.clear()

    def _prune(self) -> None:
        """Выбросить из окна запросы старше ``REMOTE_LLM_RATE_WINDOW_SECONDS``."""
        now = self._now()
        while self._calls and now - self._calls[0] >= config.REMOTE_LLM_RATE_WINDOW_SECONDS:
            self._calls.popleft()

    def _check_rate_limit(self) -> None:
        """Пропустить запрос или отказать: считаются только вызовы модели."""
        self._prune()
        if len(self._calls) >= self.rate_limit:
            raise RateLimitExceeded(
                f"Rate limit exceeded: {self.rate_limit} запросов в минуту "
                f"(клиентский счётчик RemoteLLMClient)", limit=self.rate_limit,
                window_seconds=config.REMOTE_LLM_RATE_WINDOW_SECONDS)
        self._calls.append(self._now())

    # ---------- вызовы ----------
    def chat(self, messages: Sequence[dict], *, max_tokens: Optional[int] = None,
             temperature: Optional[float] = None,
             top_p: Optional[float] = None) -> dict:
        """Ответ на список сообщений: ``/chat/completions``, поток выключен."""
        self._check_rate_limit()
        payload: dict = {
            "model": self.model,
            "messages": [{str(key): message[key] for key in ("role", "content")}
                         for message in messages],
            "stream": False,
            "temperature": float(config.DEFAULT_TEMPERATURE if temperature is None
                                 else temperature),
            "top_p": float(DEFAULT_TOP_P if top_p is None else top_p),
            "max_tokens": self._limit(None, max_tokens),
        }
        # Окно контекста — расширение Ollama: в OpenAI-формате его места нет, а
        # для длинных RAG-контекстов оно решает. Предел ответа выше отвечает за
        # длину генерации, это поле — за то, сколько влезет во вход.
        payload["options"] = {"num_ctx": int(self.max_context)}
        url = self._endpoint("/chat/completions")
        started = time.perf_counter()
        data = self._request("POST", url, payload)
        duration_ms = int((time.perf_counter() - started) * 1000)
        answer = self._answer(data)
        if not answer:
            raise RemoteLLMError(f"Удалённая модель вернула пустой ответ ({url})")
        return self._result(data, answer, duration_ms)

    def generate(self, prompt: str, max_tokens: Optional[int] = None) -> dict:
        """Один пользовательский промпт: тот же ``chat`` без системного сообщения."""
        return self.chat([{"role": "user", "content": str(prompt or "")}],
                         max_tokens=max_tokens)

    def generate_with_context(self, *, system: str, context: str, question: str,
                              task_type: Optional[str] = None,
                              max_tokens: Optional[int] = None,
                              temperature: Optional[float] = None,
                              top_p: Optional[float] = None,
                              agent_id: Optional[str] = None) -> dict:
        """Вызов режима RAG: системный промпт отдельно, контекст вместе с вопросом.

        Предел ответа выбирается как в облаке: явный аргумент → предел типа задачи
        (``LLM_TASK_MAX_TOKENS``) → общий предел дня 21.
        """
        messages = []
        if str(system or "").strip():
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user",
                         "content": self._question_text(context, question)})
        return self.chat(messages,
                         max_tokens=self._limit(task_type, max_tokens),
                         temperature=temperature, top_p=top_p)

    def list_models(self) -> dict:
        """``GET /models``: проверка связи и имена моделей.

        Счётчик частоты не трогается: проверка связи — не вызов генерации, и
        тратить на неё бюджет минуты нельзя (иначе кнопка «Проверить соединение»
        молча съедала бы один из N запросов демо).
        """
        url = self._endpoint("/models")
        data = self._request("GET", url)
        items = data.get("data") or []
        models = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
        models = [name for name in models if name]
        return {"models": models, "count": len(models), "url": url,
                "base_url": self.base_url}

    # ---------- детали ----------
    @staticmethod
    def _question_text(context: str, question: str) -> str:
        """Текст пользовательского сообщения: блок контекста, затем вопрос."""
        parts = [str(context or "").strip(), str(question or "").strip()]
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _limit(task_type: Optional[str], max_tokens: Optional[int]) -> int:
        """Предел длины ответа: явный → по типу задачи → общий предел дня 21."""
        if max_tokens:
            return max(1, int(max_tokens))
        cap = config.LLM_TASK_MAX_TOKENS.get(str(task_type or ""),
                                            config.LLM_MAX_RESPONSE_TOKENS)
        return max(1, int(cap))

    @staticmethod
    def _answer(data: dict) -> str:
        """Текст ответа из OpenAI-формы: ``choices[0].message.content``."""
        choices = data.get("choices") or []
        first = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = first.get("message") or {}
        return str(message.get("content") or "").strip()

    def _endpoint(self, path: str) -> str:
        """Полный адрес эндпоинта: база уже включает ``/v1``."""
        return f"{self.base_url}{path}"

    def _result(self, data: dict, answer: str, duration_ms: int) -> dict:
        """Ответ словарём: те же поля, что читают ``usage_dict`` и записи RAG.

        Кэша контекста и тарифа у своей модели нет: весь ввод — промах, стоимость
        нулевая, но форма ответа та же, что у облачного клиента и у Ollama дня 26.
        """
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        model = str(data.get("model") or self.model)
        return {
            "provider": llm_provider.PROVIDER_REMOTE,
            "model": model,
            "answer": answer,
            "duration_ms": duration_ms,
            "tokens": {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion,
                "total_tokens": int(usage.get("total_tokens")
                                    or (prompt_tokens + completion)),
                "cache_hit_tokens": 0,
                "cache_miss_tokens": prompt_tokens,
                "cache_hit_percent": 0.0,
                "cost_estimate": 0.0,
            },
            "rate_limit": self.rate_limit_state(),
        }

    def _request(self, method: str, url: str, payload: Optional[dict] = None) -> dict:
        """HTTP-запрос к удалённому сервису: любой сбой — ``RemoteLLMError``."""
        if not self.base_url:
            raise RemoteLLMError(
                "Не задан адрес удалённой модели: впишите Base URL туннеля "
                "(REMOTE_LLM_URL в day21/.env или поле в разделе «🛰 Удалённая LLM»)")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            if method == "GET":
                response = self._get(url, headers=headers, timeout=self.timeout)
            else:
                response = self._post(url, json=payload, headers=headers,
                                      timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Удалённая модель недоступна: %s", exc)
            raise RemoteLLMError(
                f"Удалённая модель недоступна ({self.base_url}): "
                f"{exc.__class__.__name__}. Проверьте, что ячейка в Colab работает, "
                f"а туннель Cloudflare не закрылся") from exc
        if response.status_code == 429:
            raise RateLimitExceeded(
                f"Сервер удалённой модели ответил 429 (частоту ограничил он, а не "
                f"клиент): {_body(response)}", limit=self.rate_limit,
                window_seconds=config.REMOTE_LLM_RATE_WINDOW_SECONDS)
        if response.status_code >= 400:
            raise RemoteLLMError(
                f"Удалённая модель вернула HTTP {response.status_code}: {_body(response)}",
                status_code=response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise RemoteLLMError(f"Ответ удалённой модели не JSON ({url})") from exc


def _body(response: Any) -> str:
    """Тело ответа с ошибкой текстом: длинное обрезается."""
    try:
        text = str(response.text or "")
    except Exception:  # pragma: no cover - защита от чужого объекта response
        return ""
    return " ".join(text.split())[:ERROR_BODY_LIMIT] or "(пустое тело)"
