"""Обёртка вызова LLM: модель по задаче, метрики кэша, журнал расходов (день 21).

Проверяется контракт обёртки: она передаёт SDK ровно те четыре параметра, которые
понимает клиент (лишний сломал бы и провайдера, и фейки тестов), выбирает модель и
предел ответа по типу задачи, забирает из ответа попадания и промахи кэша контекста
и пишет строку в журнал — а сбой журнала не ломает сам запрос.

Клиент подменяется своим: тест проверяет учёт, а не сеть. Хранилище — на временной
БД (фикстура `session_factory`).
"""
from types import SimpleNamespace

import pytest

from backend.core import config
from backend.services.llm_client import (
    LLMClient,
    extract_cache_metrics,
    get_llm_client,
)
from backend.storage.llm_usage_store import LLMUsageStore


class StubUsage:
    """Блок `usage` ответа: токены и — по желанию — поля кэша контекста."""

    def __init__(self, prompt_tokens=1000, completion_tokens=50,
                 cache_hit_tokens=None, cache_miss_tokens=None,
                 extra_only=False) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        if cache_hit_tokens is not None or cache_miss_tokens is not None:
            values = {"prompt_cache_hit_tokens": cache_hit_tokens,
                      "prompt_cache_miss_tokens": cache_miss_tokens}
            if extra_only:
                # Так поля приходят у части сборок SDK: в `model_extra`, не атрибутом.
                self.model_extra = values
            else:
                self.prompt_cache_hit_tokens = cache_hit_tokens
                self.prompt_cache_miss_tokens = cache_miss_tokens


class StubCompletions:
    """`chat.completions`: записывает вызов и отвечает заготовленным ответом."""

    def __init__(self, owner: "StubClient") -> None:
        self._owner = owner

    def create(self, model, messages, temperature=None, max_tokens=None):
        self._owner.calls.append({"model": model, "messages": messages,
                                  "temperature": temperature, "max_tokens": max_tokens})
        if self._owner.error is not None:
            raise self._owner.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Ответ"),
                                     finish_reason="stop")],
            usage=self._owner.usage,
        )


class StubClient:
    """Минимальный клиент DeepSeek: те же четыре именованных параметра, что у SDK."""

    def __init__(self, usage=None, error=None) -> None:
        self.calls: list = []
        self.usage = usage if usage is not None else StubUsage()
        self.error = error
        self.chat = SimpleNamespace(completions=StubCompletions(self))


@pytest.fixture
def store(session_factory):
    """Журнал расходов на временной БД."""
    return LLMUsageStore(session_factory=session_factory)


@pytest.fixture
def client(store):
    """Обёртка с подменённым клиентом и временным журналом."""
    stub = StubClient(usage=StubUsage(prompt_tokens=1000, completion_tokens=50,
                                      cache_hit_tokens=800, cache_miss_tokens=200))
    wrapper = LLMClient(agent_id="cost01", client_factory=lambda: stub, store=store)
    wrapper.stub = stub
    return wrapper


MESSAGES = [{"role": "user", "content": "Сколько стоит запрос?"}]


# ---------- выбор модели и предела ----------
@pytest.mark.parametrize("task_type,expected", [
    (config.LLM_TASK_CHAT, config.MODEL_CHAT),
    (config.LLM_TASK_SUMMARY, config.MODEL_CHAT),
    (config.LLM_TASK_CLASSIFY, config.MODEL_CHAT),
    (config.LLM_TASK_ORCHESTRATION, config.MODEL_REASONER),
    (config.LLM_TASK_CODE, config.MODEL_REASONER),
    ("неизвестный-тип", config.MODEL_CHAT),
    (None, config.MODEL_CHAT),
])
def test_select_model_by_task(client, task_type, expected):
    """Простые задачи идут на дешёвую модель, сложные — на основную."""
    assert client.select_model(task_type) == expected


def test_max_tokens_by_task(client):
    """Предел длины ответа задаётся типом задачи."""
    assert client.max_tokens_for(config.LLM_TASK_CHAT) == config.LLM_MAX_RESPONSE_TOKENS
    assert client.max_tokens_for(config.LLM_TASK_SUMMARY) == 512
    assert client.max_tokens_for(config.LLM_TASK_INDEXING) == \
        config.LLM_MAX_RESPONSE_TOKENS_LONG


def test_max_tokens_respects_user_limit(client):
    """Пользовательский потолок сильнее: оптимизация опускает предел, но не поднимает."""
    assert client.max_tokens_for(config.LLM_TASK_CHAT, limit=256) == 256
    assert client.max_tokens_for(config.LLM_TASK_INDEXING, limit=512) == 512


# ---------- вызов ----------
def test_call_passes_exactly_four_parameters(client):
    """В SDK уходят ровно `model`, `messages`, `temperature`, `max_tokens`."""
    client.call(messages=MESSAGES, task_type=config.LLM_TASK_CHAT,
                temperature=0.3, max_tokens=2048)
    call = client.stub.calls[-1]
    assert set(call) == {"model", "messages", "temperature", "max_tokens"}
    assert call["model"] == config.MODEL_CHAT
    assert call["temperature"] == 0.3
    assert call["max_tokens"] == config.LLM_MAX_RESPONSE_TOKENS


def test_call_uses_task_model_and_limit(client):
    """Сложная задача уходит на основную модель с её пределом."""
    client.call(messages=MESSAGES, task_type=config.LLM_TASK_ORCHESTRATION)
    call = client.stub.calls[-1]
    assert call["model"] == config.MODEL_REASONER
    assert call["max_tokens"] == config.LLM_TASK_MAX_TOKENS[config.LLM_TASK_ORCHESTRATION]


def test_call_extracts_cache_metrics(client):
    """Метрики кэша берутся из ответа, и доля попаданий считается по ним."""
    result = client.call(messages=MESSAGES)
    assert result.cache_hit_tokens == 800
    assert result.cache_miss_tokens == 200
    assert result.cache_hit_percent == 80.0
    assert result.cost_estimate > 0
    assert result.to_dict()["request_type"] == config.LLM_TASK_CHAT


def test_call_records_journal_row(client, store):
    """Строка журнала содержит модель, тип задачи, токены, кэш и стоимость."""
    result = client.call(messages=MESSAGES, task_type=config.LLM_TASK_CLASSIFY)
    rows = store.recent(agent_id="cost01")
    assert len(rows) == 1
    row = rows[0]
    assert row["agent_id"] == "cost01"
    assert row["model"] == config.MODEL_CHAT
    assert row["request_type"] == config.LLM_TASK_CLASSIFY
    assert (row["prompt_tokens"], row["completion_tokens"]) == (1000, 50)
    assert (row["cache_hit_tokens"], row["cache_miss_tokens"]) == (800, 200)
    assert row["cost_estimate"] == result.cost_estimate
    assert row["timestamp"] and row["created_at"]


def test_call_can_skip_journal(client, store):
    """`record=False` не пишет строку: так можно померить стоимость без учёта."""
    client.call(messages=MESSAGES, record=False)
    assert store.recent() == []


def test_journal_failure_does_not_break_call(client, monkeypatch):
    """Сбой журнала — предупреждение в лог, а не исключение в генерации."""
    monkeypatch.setattr(store_of(client), "add",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("БД занята")))
    result = client.call(messages=MESSAGES)
    assert result.usage_row is None
    assert result.response.choices[0].message.content == "Ответ"


def store_of(client):
    """Хранилище обёртки (достаётся свойством — так тест подменяет именно его)."""
    return client.store


def test_error_from_client_is_not_swallowed(client):
    """Ошибку клиента обёртка не глотает: её обрабатывает вызывающий код."""
    client.stub.error = OSError("нет сети")
    with pytest.raises(OSError):
        client.call(messages=MESSAGES)
    assert client.store.recent() == []


# ---------- ответ с контекстом ----------
def test_generate_with_context_orders_system_then_context(client):
    """Системный промпт идёт первым: это стабильный префикс запроса (кэш контекста)."""
    result = client.generate_with_context(system="S", context="CTX", question="Q?")
    messages = client.stub.calls[-1]["messages"]
    assert messages[0] == {"role": "system", "content": "S"}
    assert messages[1]["content"].startswith("CTX")
    assert messages[1]["content"].endswith("Q?")
    assert result.response.choices[0].message.content == "Ответ"


def test_generate_with_context_without_context_sends_question_only(client):
    """Пустой контекст — режим без RAG: в сообщении пользователя ровно вопрос."""
    client.generate_with_context(system="S", context="", question="Q?")
    assert client.stub.calls[-1]["messages"][1] == {"role": "user", "content": "Q?"}


def test_generate_with_context_falls_back_to_task_tokens(client):
    """Без явного лимита предел ответа берётся из таблицы типа задачи."""
    client.generate_with_context(system="S", context="", question="Q?",
                                 task_type=config.LLM_TASK_CHAT)
    assert client.stub.calls[-1]["max_tokens"] == config.LLM_MAX_RESPONSE_TOKENS


# ---------- метрики без данных о кэше ----------
def test_extract_cache_metrics_without_fields():
    """Провайдер не отдал полей кэша — весь ввод считается промахом."""
    assert extract_cache_metrics(StubUsage(prompt_tokens=700)) == (0, 700)


def test_extract_cache_metrics_from_model_extra():
    """Поля кэша приходят и в `model_extra` (зависит от сборки SDK)."""
    usage = StubUsage(prompt_tokens=900, cache_hit_tokens=600, cache_miss_tokens=300,
                      extra_only=True)
    assert extract_cache_metrics(usage) == (600, 300)


def test_extract_cache_metrics_fills_missing_miss():
    """Если есть только хиты, промахи считаются как остаток ввода."""
    usage = StubUsage(prompt_tokens=900, cache_hit_tokens=600)
    assert extract_cache_metrics(usage) == (600, 300)


def test_extract_cache_metrics_from_dict():
    """Словарь `usage` (некоторые тесты и обёртки) тоже понимается."""
    assert extract_cache_metrics({"prompt_tokens": 500,
                                  "prompt_cache_hit_tokens": 400,
                                  "prompt_cache_miss_tokens": 100}) == (400, 100)


def test_extract_cache_metrics_ignores_none_usage():
    """Отсутствующий `usage` — нули, а не исключение."""
    assert extract_cache_metrics(None) == (0, 0)


# ---------- чтение статистики ----------
def test_usage_returns_stats_and_requests(client, store):
    """`usage` отдаёт агрегаты периода и свежие запросы."""
    client.call(messages=MESSAGES, task_type=config.LLM_TASK_CHAT)
    client.call(messages=MESSAGES, task_type=config.LLM_TASK_SUMMARY)
    payload = client.usage(period="all")
    assert payload["count"] == 2
    assert payload["stats"]["requests"] == 2
    assert payload["stats"]["cache_hit_tokens"] == 1600
    assert payload["stats"]["cache_hit_percent"] == 80.0
    assert config.LLM_TASK_SUMMARY in payload["stats"]["by_type"]


def test_get_usage_stats_uses_agent_from_wrapper(client):
    """Статистика по умолчанию считается по агенту обёртки."""
    client.call(messages=MESSAGES)
    assert client.get_usage_stats(period="all")["requests"] == 1
    assert client.get_usage_stats(agent_id="другой", period="all")["requests"] == 0


def test_client_without_factory_explains_itself(store):
    """Обёртка без фабрики клиента не молчит: понятная ошибка вместо AttributeError."""
    wrapper = LLMClient(store=store)
    with pytest.raises(RuntimeError, match="client_factory"):
        wrapper.call(messages=MESSAGES)


def test_client_is_created_once(store):
    """Клиент создаётся лениво и один раз на обёртку."""
    created: list = []

    class Counting(StubClient):
        def __init__(self):
            super().__init__()
            created.append(1)

    wrapper = LLMClient(client_factory=Counting, store=store)
    wrapper.call(messages=MESSAGES)
    wrapper.call(messages=MESSAGES)
    assert len(created) == 1


def test_singleton_is_process_wide(monkeypatch):
    """Служба процесса — один объект (иначе журнал и выбор модели разъезжались бы)."""
    import backend.services.llm_client as module

    monkeypatch.setattr(module, "_singleton", None)
    try:
        assert get_llm_client() is get_llm_client()
    finally:
        monkeypatch.setattr(module, "_singleton", None)
