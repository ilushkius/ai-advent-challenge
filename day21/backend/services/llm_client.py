"""Единственная точка вызова DeepSeek: модель по задаче, метрики кэша, журнал (день 21).

Зачем обёртка вокруг ``client.chat.completions.create``: у каждого запроса есть три
вещи, которые нельзя забыть, и одна, которую нельзя дублировать:

* **выбор модели по типу задачи** (``select_model``): простая задача (классификация,
  ключевые слова, короткая сводка) не должна тратить основную модель;
* **предел длины ответа** (``max_tokens_for``): длинный ответ — самая дорогая часть
  запроса, и предел задаётся типом задачи, а не «сколько влезет»;
* **метрики кэша контекста**: DeepSeek возвращает ``prompt_cache_hit_tokens`` и
  ``prompt_cache_miss_tokens``; попадание в кэш дешевле обычного ввода, поэтому эти
  числа — деньги, и они обязаны попасть в журнал, а не только в лог;
* **журнал расходов** (``llm_usage``) — ОДНО место записи: если каждый вызов сайт
  писал бы сам, строки разошлись бы по формату и потеряли часть полей.

Клиентский объект берётся из фабрики (``client_factory``). В приложении это
``Agent._make_client``, поэтому подмена клиента в тестах
(``monkeypatch.setattr(agent, "_make_client", ...)``) по-прежнему видна и здесь:
обёртка не создаёт клиента сама.

Сбой записи в журнал НЕ ломает запрос: расходы — учёт, а не функциональность,
поэтому ошибка журнала пишется предупреждением в лог и возвращается ``None``.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Sequence

from shared.logging_utils import get_logger

from ..core import config
from ..domain.llm_cost import estimate_cost
from ..storage.llm_usage_store import LLMUsageStore

logger = get_logger(__name__)

__all__ = ["LLMCallResult", "LLMClient", "extract_cache_metrics", "get_llm_client"]


class LLMCallResult:
    """Ответ модели вместе с тем, что о нём нужно знать журналу и агенту.

    ``response`` остаётся исходным объектом SDK: агент читает из него ``choices``,
    ``finish_reason`` и ``usage``, и подменять их своей копией значило бы менять
    поведение вызывающего кода ради удобства учёта.
    """

    def __init__(self, *, response: Any, model: str, task_type: str,
                 max_tokens: int, prompt_tokens: int, completion_tokens: int,
                 cache_hit_tokens: int, cache_miss_tokens: int,
                 cost_estimate: float, usage_row: Optional[dict] = None) -> None:
        self.response = response
        self.model = model
        self.task_type = task_type
        self.max_tokens = max_tokens
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cache_hit_tokens = cache_hit_tokens
        self.cache_miss_tokens = cache_miss_tokens
        self.cost_estimate = cost_estimate
        self.usage_row = usage_row

    @property
    def cache_hit_percent(self) -> float:
        """Доля ввода, попавшая в кэш контекста (0.0 — данных о кэше не было)."""
        total = self.cache_hit_tokens + self.cache_miss_tokens
        return round(self.cache_hit_tokens / total * 100, 1) if total else 0.0

    def to_dict(self) -> dict:
        """Отчёт о вызове для лога, ответа API и отчёта об оптимизации."""
        return {
            "model": self.model,
            "request_type": self.task_type,
            "max_tokens": self.max_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "cache_hit_percent": self.cache_hit_percent,
            "cost_estimate": self.cost_estimate,
        }


def _usage_field(usage: Any, name: str) -> Optional[int]:
    """Поле ``usage`` по имени: атрибут, ``model_extra`` или ключ словаря.

    Три формы нужны потому, что DeepSeek отдаёт поля кэша не во всех версиях SDK
    одинаково: старые сборки кладут их в ``model_extra``, новые — атрибутами, а
    фейки тестов — обычными атрибутами объекта. Отсутствие поля — ``None``, и это
    не ошибка: у запроса без кэша его просто нет.
    """
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(name)
    else:
        value = getattr(usage, name, None)
        if value is None:
            extra = getattr(usage, "model_extra", None) or {}
            value = extra.get(name) if isinstance(extra, dict) else None
    return int(value) if value is not None else None


def extract_cache_metrics(usage: Any) -> tuple[int, int]:
    """Пара ``(попадания, промахи)`` кэша контекста из блока ``usage``.

    Если провайдер (или фейк тестов) полей кэша не отдал, весь ввод считается
    промахом: так «доля попаданий» не становится завышенной из-за отсутствия
    данных, а стоимость считается по полной цене ввода.
    """
    prompt = int(_usage_field(usage, "prompt_tokens") or 0)
    hit = _usage_field(usage, "prompt_cache_hit_tokens")
    miss = _usage_field(usage, "prompt_cache_miss_tokens")
    if hit is None and miss is None:
        return 0, prompt
    hit = max(0, hit or 0)
    if miss is None:
        miss = max(0, prompt - hit)
    return hit, max(0, miss)


class LLMClient:
    """Обёртка вызова DeepSeek: модель, предел ответа, метрики кэша, журнал."""

    def __init__(self, *, agent_id: Optional[str] = None,
                 client_factory: Optional[Callable[[], Any]] = None,
                 store: Optional[LLMUsageStore] = None,
                 session_factory=None,
                 default_model: Optional[str] = None,
                 default_temperature: Optional[float] = None) -> None:
        self.agent_id = agent_id
        self._client_factory = client_factory
        self._store = store
        self._session_factory = session_factory
        self._client = None
        self.default_model = default_model
        self.default_temperature = default_temperature

    # ---------- зависимости ----------
    @property
    def store(self) -> LLMUsageStore:
        """Хранилище журнала: переданное или на фабрике сессий вызывающего кода."""
        if self._store is None:
            self._store = LLMUsageStore(session_factory=self._session_factory)
        return self._store

    def client(self) -> Any:
        """Клиент DeepSeek: создаётся лениво один раз на обёртку."""
        if self._client is None:
            if self._client_factory is None:
                raise RuntimeError(
                    "LLMClient без client_factory: передайте фабрику клиента "
                    "(в приложении это Agent._make_client)"
                )
            self._client = self._client_factory()
        return self._client

    # ---------- выбор модели и предела ----------
    def select_model(self, task_type: Optional[str] = None) -> str:
        """Модель под тип задачи: простые — дешёвая, сложные — основная.

        Таблица «тип → модель» лежит в ``config.LLM_TASK_MODELS`` (данные, а не
        код). Неизвестный тип считается обычным чатом: он не должен ронять запрос.
        """
        key = str(task_type or self.default_model_task())
        return config.LLM_TASK_MODELS.get(key, config.LLM_TASK_MODELS[config.LLM_TASK_DEFAULT])

    def default_model_task(self) -> str:
        """Тип задачи по умолчанию (для вызовов без явного типа)."""
        return config.LLM_TASK_CHAT

    def max_tokens_for(self, task_type: Optional[str] = None,
                       limit: Optional[int] = None) -> int:
        """Предел длины ответа по типу задачи, не выше пользовательского лимита.

        ``limit`` — потолок от вызывающего кода (у агента это ``max_tokens`` из его
        конфигурации): оптимизация опускает предел, но не поднимает его выше того,
        что выбрал пользователь.
        """
        key = str(task_type or self.default_model_task())
        cap = config.LLM_TASK_MAX_TOKENS.get(key, config.LLM_MAX_RESPONSE_TOKENS)
        if limit:
            cap = min(int(cap), int(limit))
        return max(1, int(cap))

    # ---------- вызов ----------
    def call(self, *, messages: Sequence[dict],
             task_type: Optional[str] = None,
             model: Optional[str] = None,
             max_tokens: Optional[int] = None,
             temperature: Optional[float] = None,
             agent_id: Optional[str] = None,
             record: bool = True) -> LLMCallResult:
        """Вызывает модель и (по умолчанию) пишет строку в журнал расходов.

        Ключевые слова вызова ровно те, что понимает SDK и фейки тестов
        (``model``, ``messages``, ``temperature``, ``max_tokens``): лишние
        параметры сломали бы подменённый клиент, а провайдеру для кэша контекста
        ничего дополнительно передавать не нужно — кэш работает по префиксу запроса.
        """
        kind = str(task_type or self.default_model_task())
        chosen = model or self.select_model(kind)
        cap = self.max_tokens_for(kind, limit=max_tokens)
        temperature_value = (self.default_temperature if temperature is None
                             else temperature)
        started = datetime.now(timezone.utc)
        response = self.client().chat.completions.create(
            model=chosen, messages=list(messages),
            temperature=temperature_value, max_tokens=cap,
        )
        usage = getattr(response, "usage", None)
        prompt_tokens = int(_usage_field(usage, "prompt_tokens") or 0)
        completion_tokens = int(_usage_field(usage, "completion_tokens") or 0)
        hit, miss = extract_cache_metrics(usage)
        cost = estimate_cost(model=chosen, prompt_tokens=prompt_tokens,
                             completion_tokens=completion_tokens,
                             cache_hit_tokens=hit)
        row = None
        if record:
            row = self.record_usage(
                model=chosen, task_type=kind, prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens, cache_hit_tokens=hit,
                cache_miss_tokens=miss, cost_estimate=cost,
                agent_id=agent_id, timestamp=started,
            )
        logger.info(
            "LLM %s: модель %s, ввод %d (кэш %d/%d, %.1f%%), вывод %d, предел %d, ~$%.6f",
            kind, chosen, prompt_tokens, hit, miss,
            round(hit / (hit + miss) * 100, 1) if (hit + miss) else 0.0,
            completion_tokens, cap, cost,
        )
        return LLMCallResult(response=response, model=chosen, task_type=kind,
                             max_tokens=cap, prompt_tokens=prompt_tokens,
                             completion_tokens=completion_tokens,
                             cache_hit_tokens=hit, cache_miss_tokens=miss,
                             cost_estimate=cost, usage_row=row)

    # ---------- журнал ----------
    def record_usage(self, *, model: str, task_type: str, prompt_tokens: int = 0,
                     completion_tokens: int = 0, cache_hit_tokens: int = 0,
                     cache_miss_tokens: int = 0, cost_estimate: float = 0.0,
                     agent_id: Optional[str] = None,
                     timestamp: Optional[datetime] = None) -> Optional[dict]:
        """Пишет строку журнала; сбой журнала не роняет запрос (``None``)."""
        try:
            return self.store.add(
                model=model, request_type=task_type, prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_hit_tokens=cache_hit_tokens, cache_miss_tokens=cache_miss_tokens,
                cost_estimate=cost_estimate,
                agent_id=agent_id if agent_id is not None else self.agent_id,
                timestamp=timestamp,
            )
        except Exception as exc:  # noqa: BLE001 — учёт не должен ломать генерацию
            logger.warning("Журнал расходов LLM не записан: %s", exc)
            return None

    # ---------- чтение ----------
    def get_usage_stats(self, agent_id: Optional[str] = None,
                        period: Optional[str] = None) -> dict:
        """Агрегированная статистика расходов: токены, кэш, стоимость, модели.

        Форма — ровно то, что отдают ``LLMUsageStore.stats`` и ``recent``: вкладка
        «Расходы» и отчёт об оптимизации читают одни и те же числа, поэтому
        статистика не пересчитывается на их стороне.
        """
        target = agent_id if agent_id is not None else self.agent_id
        return self.store.stats(agent_id=target, period=period)

    def usage(self, agent_id: Optional[str] = None, period: Optional[str] = None,
              limit: Optional[int] = None) -> dict:
        """Статистика плюс последние запросы — ответ ``GET /llm/usage``."""
        target = agent_id if agent_id is not None else self.agent_id
        stats = self.store.stats(agent_id=target, period=period)
        recent = self.store.recent(agent_id=target, limit=limit)
        return {"stats": stats, "requests": recent, "count": len(recent)}


#: Клиент процесса: один на процесс, чтобы журнал и выбор модели не разъезжались.
_singleton: Optional[LLMClient] = None
_singleton_lock = threading.Lock()


def get_llm_client() -> LLMClient:
    """Обёртка вызова LLM процесса (без фабрики клиента — её задаёт вызывающий).

    Точка подмены для тестов: ``monkeypatch.setattr(main, "get_llm_client", ...)``.
    Агент по умолчанию берёт обёртку процесса, но со СВОЕЙ фабрикой клиента, поэтому
    подмена ``Agent._make_client`` в тестах продолжает работать.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = LLMClient()
    return _singleton
