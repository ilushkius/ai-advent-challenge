"""Тесты эндпоинтов расходов на LLM (день 21).

Проверяется контракт `/llm`: журнал расходов с раздельными `cache_hit`/`cache_miss`,
состояние рычагов экономии (пик/непик, кэш стабильных префиксов, сжатие), прогноз
экономии, справка по моделям и правило непиковых окон. Отдельно — контракт ошибок:
400 на неизвестный период агрегации, 422 на выход `off_peak_share` за границы. Плюс
поле `llm` ответа генерации — то, ради чего день и делался: стоимость хода видна
сразу, а не только в журнале.

Клиент DeepSeek подменяется `FakeClient`: тест проверяет контракт API, а не сеть.
"""
import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.core import config
from backend.core.prompt_builder import PromptBuilder, reset_prompt_builder
from backend.domain import llm_provider, local_tuning
from backend.services import llm_factory, local_tuning_service
from backend.services.local_llm_client import LocalLLMError
from backend.storage import database
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import LocalDictStubClient
from support import FakeClient

#: Вопрос с литералом тестового корпуса: на него обязана найтись выдача.
TUNE_QUESTION = "Чему равен CHARS_PER_PAGE?"

#: Записи журнала для проверки агрегатов: две чат-строки и одна классификация.
SEED_ROWS = (
    {"model": config.MODEL_CHAT, "request_type": config.LLM_TASK_CHAT,
     "prompt_tokens": 1000, "completion_tokens": 50,
     "cache_hit_tokens": 800, "cache_miss_tokens": 200, "cost_estimate": 0.0002},
    {"model": config.MODEL_CHAT, "request_type": config.LLM_TASK_CHAT,
     "prompt_tokens": 1000, "completion_tokens": 60,
     "cache_hit_tokens": 900, "cache_miss_tokens": 100, "cost_estimate": 0.0003},
    {"model": config.MODEL_CHAT, "request_type": config.LLM_TASK_CLASSIFY,
     "prompt_tokens": 400, "completion_tokens": 20,
     "cache_hit_tokens": 0, "cache_miss_tokens": 400, "cost_estimate": 0.0001},
)


@pytest.fixture
def client(session_factory, monkeypatch):
    """TestClient на временной БД с подменённым клиентом DeepSeek и своим журналом."""
    factory = session_factory
    monkeypatch.setattr(database, "SessionLocal", factory)
    reset_prompt_builder()

    import backend.api.main as main

    manager = AgentManager(session_factory=factory)
    monkeypatch.setattr(main, "get_manager", lambda: manager)
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient(reply="Ответ"))

    store = LLMUsageStore(session_factory=factory)
    for row in SEED_ROWS:
        store.add(agent_id="agent-llm", **row)

    instance = TestClient(main.app)
    instance.store = store
    instance.manager = manager
    return instance


def _agent_id(client, name="Агент расходов") -> str:
    """Создаёт агента через API и возвращает его идентификатор."""
    response = client.post("/agents", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["agent_id"]


# ---------- журнал ----------
def test_usage_returns_stats(client):
    """GET /llm/usage отдаёт агрегаты периода и свежие запросы."""
    body = client.get("/llm/usage", params={"period": "all"}).json()
    assert body["count"] == 3
    stats = body["stats"]
    assert stats["requests"] == 3
    assert stats["prompt_tokens"] == 2400
    assert stats["completion_tokens"] == 130
    assert stats["total_tokens"] == 2530
    assert stats["cache_hit_tokens"] == 1700
    assert stats["cache_miss_tokens"] == 700
    assert stats["cache_hit_percent"] == pytest.approx(70.8, abs=0.1)
    assert stats["cost_estimate"] == pytest.approx(0.0006, abs=1e-9)
    assert set(stats["by_type"]) == {config.LLM_TASK_CHAT, config.LLM_TASK_CLASSIFY}
    assert stats["daily"] and stats["daily"][0]["requests"] == 3


def test_usage_request_rows_expose_cache_fields(client):
    """Строка журнала несёт cache_hit и cache_miss раздельно (ради этого день и делался)."""
    body = client.get("/llm/usage", params={"period": "all", "limit": 2}).json()
    assert len(body["requests"]) == 2
    row = body["requests"][0]
    assert row["model"] == config.MODEL_CHAT
    assert row["agent_id"] == "agent-llm"
    assert row["cache_hit_tokens"] + row["cache_miss_tokens"] == row["prompt_tokens"]
    assert row["cost_estimate"] > 0
    assert row["timestamp"] and row["created_at"]


def test_usage_filters_by_agent(client):
    """Фильтр по агенту сужает выборку."""
    assert client.get("/llm/usage",
                      params={"agent_id": "agent-llm", "period": "all"}).json()["count"] == 3
    assert client.get("/llm/usage",
                      params={"agent_id": "чужой", "period": "all"}).json()["count"] == 0


def test_usage_rejects_unknown_period(client):
    """Неизвестный период агрегации — 400 с перечнем допустимых."""
    response = client.get("/llm/usage", params={"period": "вечность"})
    assert response.status_code == 400
    assert "week" in response.json()["detail"]


def test_usage_validates_limit(client):
    """Неположительный limit — 422 (проверка параметра, а не молчаливый зажим)."""
    assert client.get("/llm/usage", params={"limit": 0}).status_code == 422


# ---------- состояние и прогноз ----------
def test_status_reports_peak_and_cache(client):
    """GET /llm/status: окно часов, скидка, кэш префиксов, сжатие и таблицы задач."""
    body = client.get("/llm/status").json()
    assert body["peak"] != body["off_peak"]
    assert body["discount_percent"] == config.OFF_PEAK_DISCOUNT_PERCENT
    assert body["next_off_peak"]
    assert set(body["prompt"]) >= {"cache_hits", "cache_misses", "cache_hit_percent"}
    assert set(body["compressor"]) >= {"calls", "saved_tokens", "saved_percent"}
    assert body["task_models"] == config.LLM_TASK_MODELS
    assert body["task_max_tokens"] == config.LLM_TASK_MAX_TOKENS


def test_status_counts_prompt_cache_hits(client):
    """Повторная сборка промпта видна в статусе как попадание в кэш префикса."""
    builder = PromptBuilder()
    builder.build(system="Ты — ассистент.", dynamic=["память"])
    builder.build(system="Ты — ассистент.", dynamic=["другая память"])
    import backend.core.prompt_builder as module

    module._BUILDER = builder  # подменяем службу процесса на свою (изоляция теста)
    try:
        body = client.get("/llm/status").json()
    finally:
        module._BUILDER = None
    assert body["prompt"]["cache_hits"] == 1
    assert body["prompt"]["requests"] == 2


def test_estimate_counts_levers(client):
    """POST /llm/estimate показывает вклад каждого рычага по отдельности."""
    body = client.post("/llm/estimate", json={
        "model": config.MODEL_CHAT, "task_type": config.LLM_TASK_CHAT,
        "prompt_tokens": 100_000, "completion_tokens": 400,
        "cache_hit_tokens": 60_000, "compressed_tokens": 10_000,
        "max_response_tokens": 1_000, "off_peak_share": 1.0,
    }).json()
    assert body["cache"]["saving"] > 0
    assert body["compression"]["saving"] > 0
    assert body["off_peak"]["saving"] > 0
    assert body["response_limit"]["tokens"] == config.DEFAULT_MAX_TOKENS - 1_000
    assert body["core_saving"] == pytest.approx(
        body["cache"]["saving"] + body["compression"]["saving"] + body["off_peak"]["saving"],
        abs=1e-6)
    assert body["core_saving"] < body["total_saving"] < body["baseline_cost"]
    assert 0 < body["saving_percent"] < 100


def test_estimate_validates_share(client):
    """Доля непика вне 0…1 — 422."""
    response = client.post("/llm/estimate", json={"off_peak_share": 5.0})
    assert response.status_code == 422


def test_models_endpoint_lists_routing(client):
    """GET /llm/models отдаёт маршрутизацию моделей и тарифы."""
    body = client.get("/llm/models").json()
    assert body["task_models"] == config.LLM_TASK_MODELS
    assert body["default_model"] == config.MODEL_CHAT
    assert body["cache_input_ratio"] == config.LLM_CACHE_INPUT_RATIO
    assert set(body["prices"]) == set(config.MODEL_PRICES)


def test_peak_endpoint_describes_windows(client):
    """GET /llm/peak отдаёт правило окон, скидку и текущий статус."""
    body = client.get("/llm/peak").json()
    assert body["off_peak_weekday_hours_utc"] == [
        [start, end] for start, end in config.OFF_PEAK_WEEKDAY_HOURS_UTC]
    assert body["peak_weekday_hours_utc"] == [
        [start, end] for start, end in config.PEAK_WEEKDAY_HOURS_UTC]
    assert body["weekends_off_peak"] is True
    assert body["discount_percent"] == config.OFF_PEAK_DISCOUNT_PERCENT
    assert body["status"]["peak"] != body["status"]["off_peak"]


# ---------- ход агента ----------
def test_generate_reports_llm_costs_and_logs(client):
    """Ответ генерации несёт поле `llm`, а ход появляется в журнале расходов."""
    agent_id = _agent_id(client)
    body = client.post(f"/agents/{agent_id}/generate",
                      json={"prompt": "Сколько стоит запрос?"}).json()
    assert body["status"] == "ok"
    llm = body["llm"]
    assert llm["model"] == config.MODEL_CHAT
    assert llm["request_type"] == config.LLM_TASK_CHAT
    assert llm["max_tokens"] == config.LLM_MAX_RESPONSE_TOKENS
    assert llm["prompt_tokens"] > 0 and llm["cost_estimate"] > 0
    rows = client.store.recent(agent_id=agent_id)
    assert rows, "ход агента обязан попасть в журнал расходов"
    assert {row["request_type"] for row in rows} >= {config.LLM_TASK_CHAT}


def test_generate_logs_invariant_check_separately(client):
    """Проверка инвариантов — отдельный тип задачи: её видно в журнале отдельно."""
    # Без активных правил контролёр не зовёт модель вовсе, поэтому правило нужно.
    created = client.post("/invariants", json={
        "name": "Вежливый тон", "description": "Отвечай вежливо",
        "category": "architecture", "severity": "soft",
    })
    assert created.status_code == 201, created.text
    agent_id = _agent_id(client, "Агент инвариантов")
    client.post(f"/agents/{agent_id}/generate", json={"prompt": "Привет"})
    kinds = {row["request_type"] for row in client.store.recent(agent_id=agent_id)}
    assert config.LLM_TASK_CLASSIFY in kinds
    assert config.LLM_TASK_CHAT in kinds


def test_root_lists_llm_group(client):
    """Корневая точка перечисляет группу расходов и её эндпоинты."""
    body = client.get("/").json()
    assert "/llm/usage" in body["llm"]
    assert "GET /llm/status" in body["endpoints"]
    assert body["endpoints"].count("POST /llm/estimate") == 1


class LocalDemoClient:
    """Клиент локального демо: ответ подбирается по промпту (Париж / 9 / код).

    Форма ответа — как у ``LocalLLMClient``: демо читает ``answer``, ``duration_ms``,
    ``model`` и ``tokens``, поэтому заглушка обязана отдать именно эти поля.
    """

    def __init__(self) -> None:
        self.prompts: list = []

    def generate(self, prompt, max_tokens=None) -> dict:
        """Словарь ответа локальной модели; промпт и предел сохраняются для проверки."""
        self.prompts.append({"prompt": prompt, "max_tokens": max_tokens})
        text = str(prompt).lower()
        if "столица" in text:
            answer = "Париж."
        elif "яблок" in text:
            answer = "Всего 9 яблок."
        else:
            answer = ("def bubble(items):\n    for item in items:\n        pass\n"
                      "    return items")
        return {"provider": "local", "model": "stub-local:1b", "answer": answer,
                "duration_ms": 5,
                "tokens": {"model": "stub-local:1b", "prompt_tokens": 10,
                           "completion_tokens": 3, "cache_hit_tokens": 0,
                           "cache_miss_tokens": 10, "cache_hit_percent": 0.0,
                           "cost_estimate": 0.0}}


def test_local_demo_runs_three_requests(client, monkeypatch):
    """POST /llm/local-demo: три запроса, ответы, токены и эвристика качества."""
    stub = LocalDemoClient()
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda *args, **kwargs: stub)

    response = client.post("/llm/local-demo")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "local"
    assert body["model"] == config.LOCAL_LLM_MODEL
    assert [row["key"] for row in body["rows"]] == ["fact", "logic", "code"]
    assert [row["quality"] for row in body["rows"]] == [5, 5, 5]
    assert body["rows"][0]["answer"] == "Париж."
    assert body["rows"][0]["tokens"]["prompt_tokens"] == 10
    assert body["total_ms"] == 15
    # Каждому вопросу — свой предел ответа: тип задачи берётся из набора демо.
    assert [call["max_tokens"] for call in stub.prompts] == [
        config.LOCAL_LLM_DEMO_MAX_TOKENS["fact"],
        config.LOCAL_LLM_DEMO_MAX_TOKENS["logic"],
        config.LOCAL_LLM_DEMO_MAX_TOKENS["code"],
    ]


def test_local_demo_reports_unavailable_ollama(client, monkeypatch):
    """Ollama недоступна: 502 с текстом причины, а не пустая таблица ответов."""
    def broken(*args, **kwargs):
        raise LocalLLMError(f"Ollama недоступен по адресу {config.LOCAL_LLM_URL}")

    monkeypatch.setattr(llm_factory, "get_llm_client", broken)

    response = client.post("/llm/local-demo")

    assert response.status_code == 502, response.text
    assert "Ollama недоступен" in response.json()["detail"]


def test_provider_endpoint_reports_current_config(client, monkeypatch):
    """GET /llm/provider: провайдер процесса читается на момент запроса, не на импорте."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "local")

    body = client.get("/llm/provider").json()

    assert body["provider"] == "local"
    assert body["providers"] == list(llm_provider.PROVIDERS)
    assert set(body["labels"]) == set(body["providers"])
    assert body["local_model"] == config.LOCAL_LLM_MODEL
    assert body["local_url"] == config.LOCAL_LLM_URL
    assert body["local_timeout"] == config.LOCAL_LLM_TIMEOUT
    # Профиль дня 29: подписи и значения действующего профиля — те же, что в домене.
    active = (local_tuning.active(llm_provider.PROVIDER_LOCAL)
              or local_tuning.baseline_profile())
    assert body["profiles"] == list(local_tuning.PROFILES)
    assert body["profile_labels"] == local_tuning.PROFILE_LABELS
    assert body["local_profile"] == active.name
    assert body["local_num_ctx"] == active.num_ctx
    assert body["local_temperature"] == active.temperature
    assert body["local_chat_max_tokens"] == active.max_tokens


def test_provider_endpoint_reports_baseline_values(client, monkeypatch):
    """При `LOCAL_LLM_PROFILE=baseline` значения описывают день 26, а не константы tuned."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_BASELINE)

    body = client.get("/llm/provider").json()

    assert body["local_profile"] == local_tuning.PROFILE_BASELINE
    assert body["local_temperature"] == config.DEFAULT_TEMPERATURE
    assert body["local_num_ctx"] == local_tuning.BASELINE_NUM_CTX
    assert body["local_chat_max_tokens"] is None


# ---------- оптимизация локальной модели (день 29) ----------
PS = {"models": [], "vram_mb": 0, "total_mb": 0, "error": ""}


@pytest.fixture
def tune_client(client, rag_service, monkeypatch):
    """TestClient с подменённой службой RAG: ``/llm/tune`` ходит в неё, а не в корпус дня."""
    import backend.api.main as main

    monkeypatch.setattr(main, "get_rag_service", lambda: rag_service)
    monkeypatch.setattr(local_tuning_service, "snapshot", lambda: dict(PS))
    monkeypatch.setattr(local_tuning_service, "version", lambda: "0.12.0")
    monkeypatch.setattr(llm_factory, "get_llm_client",
                        lambda *args, **kwargs: LocalDictStubClient())
    return client


def test_tune_runs_profiles_with_metrics(tune_client):
    """POST /llm/tune: вариант на профиль, строка на вопрос, ресурсы и сводка."""
    response = tune_client.post("/llm/tune", json={"questions": [TUNE_QUESTION],
                                                   "models": ["stub-local:1b"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ollama_version"] == "0.12.0" and body["ps_before"] == PS
    assert body["active_profile"] == local_tuning.LOCAL_LLM_PROFILE
    assert [profile["profile"] for profile in body["profiles"]] == list(local_tuning.PROFILES)
    assert [variant["params"]["profile"] for variant in body["variants"]] == \
        list(local_tuning.PROFILES)
    assert [variant["params"]["num_ctx"] for variant in body["variants"]] == \
        [local_tuning.BASELINE_NUM_CTX, local_tuning.LOCAL_LLM_NUM_CTX]
    assert all(len(variant["rows"]) == 1 for variant in body["variants"])
    row = body["variants"][1]["rows"][0]
    assert row["mode"] == "rag" and row["verdict"] and row["answer"]
    assert row["sources"] and row["quotes_verified"] is True
    assert row["completion_tokens"] == 0 and row["tokens_per_second"] == 0.0
    summary = body["variants"][1]["summary"]
    assert summary["questions"] == 1 and summary["verdict_ok"] == 0
    assert body["pairs"][0]["model"] == "stub-local:1b" and body["best"]


def test_tune_rejects_unknown_profile(tune_client):
    """Незнакомый профиль — 400 с перечнем доступных, а не молчаливая подмена."""
    response = tune_client.post("/llm/tune", json={"profiles": ["быстрый"]})

    assert response.status_code == 400, response.text
    assert "быстрый" in response.json()["detail"]


def test_tune_reports_dead_ollama(tune_client, monkeypatch):
    """Все строки с ошибкой — 502 с текстом причины (модель недоступна)."""
    dead = LocalDictStubClient(error=RuntimeError("connection refused"))
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda *a, **k: dead)

    response = tune_client.post("/llm/tune", json={"questions": [TUNE_QUESTION],
                                                   "profiles": ["tuned"]})

    assert response.status_code == 502, response.text
    assert "connection refused" in response.json()["detail"]
