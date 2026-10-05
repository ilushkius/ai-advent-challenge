"""Локальная LLM через Ollama (день 26): HTTP-клиент, совместимый по вызову с LLMClient.

Второй провайдер рядом с DeepSeek: тот же вызов ``generate_with_context``, что у
``LLMClient``, но ответ приходит СЛОВАРЁМ, а не ``LLMCallResult`` — у локальной
модели нет ни журнала расходов, ни кэша контекста, ни цены за токены. Терпимость к
словарю даёт общий помощник ``rag_llm`` (``response_text``/``usage_dict``), поэтому
RAG и мини-чат не знают, кто именно отвечал.

Запрос идёт в ``POST {base_url}/api/chat``, а не в ``/api/generate``: системный
промпт — отдельное сообщение, а не склейка с вопросом в один текст. ``stream=false``
— ответ ждём целиком, а ``duration_ms`` измеряется вокруг всего HTTP-запроса,
включая загрузку весов модели в память (первый запрос после простоя).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional, Sequence

import requests

from shared.logging_utils import get_logger

from ..core import config
from ..domain import llm_provider

logger = get_logger(__name__)

__all__ = ["LocalLLMClient", "LocalLLMError"]

#: Сколько символов тела ответа с ошибкой попадает в текст исключения.
ERROR_BODY_LIMIT = 200


class LocalLLMError(RuntimeError):
    """Ollama недоступен или ответил ошибкой: роутеры переводят её в 502."""


class LocalLLMClient:
    """Клиент Ollama: вызовы как у ``LLMClient``, ответ — словарь для rag_llm.

    ``post`` — точка подмены HTTP в тестах: вызывается ровно как ``requests.post``
    (``url`` позиционно, ``json=`` и ``timeout=`` по имени), поэтому офлайн-тест
    сети не открывает. ``agent_id`` принимается и игнорируется: журнала расходов у
    локальной модели нет, но сигнатура вызова остаётся общей с облачным клиентом.
    """

    def __init__(self, *, model: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: Optional[float] = None, agent_id: Optional[str] = None,
                 post: Optional[Callable[..., Any]] = None) -> None:
        self.model = str(model or config.LOCAL_LLM_MODEL)
        self.base_url = str(base_url or config.LOCAL_LLM_URL).rstrip("/")
        self.timeout = float(config.LOCAL_LLM_TIMEOUT if timeout is None else timeout)
        self.agent_id = agent_id
        self._post = post or requests.post

    # ---------- вызовы ----------
    def chat(self, messages: Sequence[dict], *, max_tokens: Optional[int] = None,
             temperature: Optional[float] = None) -> dict:
        """Ответ на список сообщений: ``/api/chat``, поток выключен."""
        payload = {
            "model": self.model,
            "messages": [{str(key): message[key] for key in ("role", "content")}
                         for message in messages],
            "stream": False,
            "options": {
                "temperature": (config.DEFAULT_TEMPERATURE if temperature is None
                                else float(temperature)),
                "num_predict": self._limit(None, max_tokens),
            },
        }
        url = f"{self.base_url}/api/chat"
        started = time.perf_counter()
        data = self._request(url, payload)
        duration_ms = int((time.perf_counter() - started) * 1000)
        answer = str((data.get("message") or {}).get("content") or "").strip()
        if not answer:
            raise LocalLLMError(f"Ollama вернул пустой ответ ({url})")
        return self._result(data, answer, duration_ms)

    def generate(self, prompt: str, max_tokens: Optional[int] = None) -> dict:
        """Один пользовательский промпт: тот же ``chat`` без системного сообщения."""
        return self.chat([{"role": "user", "content": str(prompt or "")}],
                         max_tokens=max_tokens)

    def generate_with_context(self, *, system: str, context: str, question: str,
                              task_type: Optional[str] = None,
                              max_tokens: Optional[int] = None,
                              temperature: Optional[float] = None,
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
                         temperature=temperature)

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

    def _result(self, data: dict, answer: str, duration_ms: int) -> dict:
        """Ответ словарём: те же поля, что читают ``usage_dict`` и записи RAG."""
        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion = int(data.get("eval_count") or 0)
        model = str(data.get("model") or self.model)
        return {
            "provider": llm_provider.PROVIDER_LOCAL,
            "model": model,
            "answer": answer,
            "duration_ms": duration_ms,
            "tokens": {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion,
                # Кэша контекста и тарифа у локальной модели нет: весь ввод — промах,
                # стоимость нулевая (железо своё), но форма ответа та же, что в облаке.
                "cache_hit_tokens": 0,
                "cache_miss_tokens": prompt_tokens,
                "cache_hit_percent": 0.0,
                "cost_estimate": 0.0,
            },
        }

    def _request(self, url: str, payload: dict) -> dict:
        """HTTP-запрос к Ollama: любой сбой — ``LocalLLMError`` с понятным текстом."""
        try:
            response = self._post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LocalLLMError(
                f"Ollama недоступен по адресу {self.base_url} "
                f"({exc.__class__.__name__}: {exc}). Запустите `ollama serve` или "
                f"проверьте LOCAL_LLM_URL"
            ) from exc
        if response.status_code != 200:
            raise LocalLLMError(f"Ollama ответил HTTP {response.status_code}: "
                                f"{str(response.text)[:ERROR_BODY_LIMIT]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LocalLLMError(f"Ollama вернул не JSON ({url}): {exc}") from exc
        if not isinstance(data, dict):
            raise LocalLLMError(f"Ollama вернул не объект JSON ({url})")
        if data.get("error"):
            raise LocalLLMError(f"Ollama сообщил об ошибке: {data['error']}")
        return data
