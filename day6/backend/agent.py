"""Класс Agent дня 6 — инкапсулированный вызов DeepSeek и история запросов.

Агент — самодостаточная сущность: хранит свою конфигурацию (модель,
температура, системный промпт, лимит токенов) и собственную историю попыток.
Клиент DeepSeek создаётся фабрикой `_make_client()` — её можно подменить на
фейк в офлайн-проверках (в проекте нет автотестов, проверки — `python -c`).
"""
import time
from datetime import datetime, timezone
from typing import List

from . import config
from .models import AgentConfig


class AgentError(Exception):
    """Понятная ошибка уровня агента (нет ключа, сбой API и т.п.)."""


class Agent:
    """Один LLM-агент: конфигурация + вызов DeepSeek + история попыток."""

    def __init__(self, cfg: AgentConfig, agent_id: str) -> None:
        self.agent_id = agent_id
        self.config = cfg
        self.created_at = datetime.now(timezone.utc)
        # История попыток: новые записи в начале списка (insert(0, ...)).
        self.history: List[dict] = []

    # --- публичные поля (короткие доступы к конфигурации) ---
    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    # --- вызов DeepSeek ---
    def _make_client(self):
        """Создаёт OpenAI-совместимый клиент DeepSeek.

        Ключ резолвится в момент вызова (не при создании агента), поэтому смена
        .env/переменной окружения видна без рестарта бэкенда. Без ключа кидаем
        AgentError ДО сетевого вызова — поведение проверяемо офлайн.
        """
        api_key = config.resolve_api_key()
        if not api_key:
            raise AgentError(
                "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day6/.env "
                "или в переменной окружения и перезапустите запрос."
            )
        import openai  # локальный импорт: модуль нужен только при реальном вызове
        return openai.OpenAI(
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=api_key,
            timeout=config.REQUEST_TIMEOUT,
        )

    def generate(self, prompt: str) -> dict:
        """Отправляет запрос в DeepSeek и возвращает запись-результат.

        Запись имеет форму HistoryEntry/GenerateResponse (см. models.py):
        status "ok" (заполнен response, метрики) или "error" (заполнен error —
        понятное сообщение, без traceback). Каждая попытка — успех или ошибка —
        сохраняется в self.history (новые сверху) и возвращается вызывающему.
        """
        timestamp = datetime.now(timezone.utc)
        record: dict = {
            "agent_id": self.agent_id,
            "status": "error",
            "prompt": prompt,
            "response": None,
            "error": None,
            "model": self.config.model,
            "finish_reason": None,
            "usage": None,
            "duration_sec": None,
            "timestamp": timestamp,
        }

        messages: List[dict] = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        try:
            client = self._make_client()
            response = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        except AgentError as exc:
            record["error"] = str(exc)
        except Exception as exc:  # сеть/API DeepSeek/неожиданное: не валим сервер
            record["error"] = f"Сбой запроса к DeepSeek: {exc}"
        else:
            choice = response.choices[0] if response.choices else None
            record["status"] = "ok"
            if choice is not None:
                record["response"] = (choice.message.content or "") if choice.message else ""
                record["finish_reason"] = choice.finish_reason
            usage = getattr(response, "usage", None)
            if usage is not None:
                record["usage"] = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
        finally:
            record["duration_sec"] = round(time.perf_counter() - started, 3)

        self.history.insert(0, record)
        return record
