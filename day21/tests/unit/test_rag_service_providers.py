"""Тесты парного прогона провайдеров (день 28).

``tests/unit/test_rag_provider.py`` (день 26) проверяет, что провайдер запроса уходит в
фабрику и попадает в запись ответа. Здесь проверяется то, чего нет ни там, ни в тестах
дня 22: какой конкретный клиент собирается на каждый провайдер, как проходит парный
прогон одного вопроса двумя провайдерами и по какому правилу считается вердикт строки.

Прогон офлайн: фабрика провайдеров подменена словарём клиентов (локальный —
``LocalDictStubClient``, облачный — заглушка ``RagStubClient``), модели не грузятся.
"""
import pytest

from backend.core import config
from backend.domain import local_tuning, rag_compare, rag_mode
from backend.services import llm_factory, rag_compare_service
from backend.services.llm_client import LLMClient
from backend.services.local_llm_client import LocalLLMClient
from backend.services.rag_service import AGENT_ID

from rag_fakes import LocalDictStubClient, RagStubClient

#: Литерал есть в тестовом корпусе: на него обязан найтись фрагмент.
QUESTION = "Чему равен CHARS_PER_PAGE?"


@pytest.fixture
def provider_factory(monkeypatch, rag_client):
    """Фабрика провайдеров подменена словарём клиентов: сети нет.

    Своя подмена на каждый провайдер (а не один клиент, как в ``test_rag_provider``):
    парный прогон обязан увидеть РАЗНЫХ клиентов, иначе проверка выродится. Вызовы
    фабрики записываются в ``calls``: по ним видно, какой профиль настройки дня 29
    получил клиент (модель и ``num_ctx``).
    """
    local, cloud = LocalDictStubClient(), rag_client
    calls: list = []

    def factory(name, **kwargs):
        calls.append({"provider": name, **kwargs})
        return {"local": local, "deepseek": cloud}[name]

    monkeypatch.setattr(llm_factory, "get_llm_client", factory)
    return {"local": local, "deepseek": cloud, "calls": calls}


# ---------- сборка клиента по провайдеру ----------
def test_local_provider_builds_local_llm_client(rag_service):
    """Провайдер local: собирается клиент Ollama с моделью из конфига дня."""
    client = rag_service.llm_client_for("local")

    assert isinstance(client, LocalLLMClient)
    assert client.model == config.LOCAL_LLM_MODEL


def test_deepseek_provider_builds_deepseek_client(rag_service):
    """Провайдер deepseek: собирается облачная обёртка и живёт в службе по имени."""
    client = rag_service.llm_client_for("deepseek")

    assert isinstance(client, LLMClient)
    assert not isinstance(client, LocalLLMClient)
    assert rag_service.llm_client_for("deepseek") is client


# ---------- парный прогон ----------
def test_compare_providers_runs_both_clients(rag_service, provider_factory):
    """Один вопрос — две строки ответа: provider, режим, источники и сводка."""
    result = rag_compare_service.run(rag_service, [QUESTION])

    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["local"]["provider"] == rag_compare_service.LOCAL_PROVIDER
    assert row["cloud"]["provider"] == rag_compare_service.CLOUD_PROVIDER
    assert row["local"]["mode"] == rag_compare.MODE_ANSWERED
    assert row["cloud"]["mode"] == rag_compare.MODE_ANSWERED
    assert row["local"]["sources"] and row["cloud"]["sources"]
    assert row["verdict"] in rag_compare.VERDICT_LABELS
    assert provider_factory["local"].calls, "локальный клиент не вызывался"
    assert provider_factory["deepseek"].stub.calls, "облачный клиент не вызывался"
    assert result["summary"]["total"] == 1
    assert result["summary"]["local_avg_ms"] > 0


def test_compare_providers_defaults_to_demo_questions(rag_service, provider_factory):
    """Пустой список вопросов — десять контрольных вопросов демо."""
    result = rag_compare_service.run(rag_service)

    assert len(result["rows"]) == 10
    summary = result["summary"]
    assert summary["local_rag"] + summary["local_dont_know"] == 10
    assert summary["cloud_rag"] + summary["cloud_dont_know"] == 10


def test_compare_providers_failure_is_a_row(rag_service, rag_usage_store, monkeypatch):
    """Сбой облачного вызова — строка ``error``, а не отказ всего прогона.

    Заглушка падает на каждом вызове (``error_times=None``), поэтому не удаётся и
    откат на ответ без RAG: служба обязана поймать ``RAGUpstreamError`` и отдать
    строку, а локальная сторона при этом остаётся полноценным ответом.
    """
    broken = RagStubClient(error=RuntimeError("boom"), error_times=None)
    stubs = {"local": LocalDictStubClient(),
             "deepseek": LLMClient(agent_id=AGENT_ID, client_factory=lambda: broken,
                                   store=rag_usage_store)}
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda name, **kw: stubs[name])

    result = rag_compare_service.run(rag_service, [QUESTION])

    row = result["rows"][0]
    assert row["cloud"]["mode"] == "error"
    assert row["cloud"]["fallback"] is True
    assert "boom" in row["cloud"]["warning"]
    assert row["local"]["mode"] == rag_compare.MODE_ANSWERED
    assert row["verdict"] == rag_compare.VERDICT_LOCAL_BETTER
    assert result["summary"]["better_local"] == 1


# ---------- правило вердикта ----------
def _record(mode: str = rag_compare.MODE_ANSWERED, *, verified: bool = False,
            confidence: float = 0.3, sources: int = 1, fallback: bool = False,
            duration_ms: int = 100) -> dict:
    """Запись стороны для проверки правила: те же поля, что читает вердикт."""
    return {"mode": mode, "fallback": fallback, "quotes_verified": verified,
            "confidence": confidence, "sources": [{"source": f"s{index}"}
                                                 for index in range(sources)],
            "duration_ms": duration_ms}


@pytest.mark.parametrize("local, cloud, expected", [
    (_record(verified=True), _record("dont_know"), rag_compare.VERDICT_LOCAL_BETTER),
    (_record("dont_know"), _record(verified=True), rag_compare.VERDICT_CLOUD_BETTER),
    (_record(fallback=True), _record(), rag_compare.VERDICT_CLOUD_BETTER),
    (_record("dont_know"), _record("dont_know"), rag_compare.VERDICT_EQUAL),
    (_record(), _record(), rag_compare.VERDICT_EQUAL),
    (_record(verified=False, confidence=0.3), _record(verified=True),
     rag_compare.VERDICT_CLOUD_BETTER),
    (_record(sources=3), _record(sources=1), rag_compare.VERDICT_LOCAL_BETTER),
])
def test_verdict_pairs(local, cloud, expected):
    """Правило вердикта: сначала «ответил ли», затем цитаты, уверенность, источники."""
    assert rag_compare.verdict(local, cloud) == expected


def test_verdict_ignores_duration():
    """Время на вердикт не влияет: строка решает, кто ответил лучше по корпусу."""
    assert rag_compare.verdict(_record(duration_ms=100_000),
                               _record(duration_ms=1)) == rag_compare.VERDICT_EQUAL


# ---------- сводка ----------
def test_summary_counts_and_overall_verdict():
    """Сводка: средние времена, источники, «не знаю» и распределение вердиктов."""
    rows = [
        rag_compare.row("один", _record(verified=True, confidence=0.4, sources=2,
                                        duration_ms=1000),
                        _record("dont_know", sources=0, duration_ms=3000)),
        rag_compare.row("два", _record("dont_know", sources=0, duration_ms=1000),
                        _record(verified=True, duration_ms=500)),
        rag_compare.row("три", _record(duration_ms=500), _record(duration_ms=500)),
    ]
    summary = rag_compare.summary(rows)

    assert (summary["better_local"], summary["better_cloud"], summary["equal"]) == (1, 1, 1)
    assert summary["verdict"] == rag_compare.VERDICT_EQUAL
    assert summary["total"] == 3
    assert summary["local_avg_ms"] == 833
    assert summary["cloud_avg_ms"] == 1333
    assert summary["local_with_sources"] == 2
    assert summary["cloud_with_sources"] == 2
    assert summary["local_dont_know"] == 1
    assert summary["cloud_dont_know"] == 1
    assert summary["local_verified"] == 1
    assert summary["cloud_verified"] == 1


def test_summary_of_empty_run():
    """Пустой прогон: нули по всем счётчикам и вердикт «равно»."""
    summary = rag_compare.summary([])

    assert summary["total"] == 0
    assert summary["local_avg_ms"] == 0 and summary["cloud_avg_ms"] == 0
    assert summary["verdict"] == rag_compare.VERDICT_EQUAL
    assert all(value == 0 for key, value in summary.items()
               if key not in ("verdict",))


# ---------- профиль настройки локальной модели (день 29) ----------
def test_tuned_profile_reaches_local_call(rag_service, provider_factory, monkeypatch):
    """Профиль по умолчанию (tuned): свой промпт, температура и предел ответа."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_TUNED)

    record = rag_service.rag_query(QUESTION, provider="local")

    assert record["mode"] == rag_compare.MODE_ANSWERED
    call = provider_factory["local"].calls[0]
    assert call["system"] == local_tuning.LOCAL_TUNED_RAG_PROMPT
    assert call["temperature"] == local_tuning.LOCAL_LLM_TEMPERATURE
    assert call["max_tokens"] == local_tuning.LOCAL_LLM_CHAT_MAX_TOKENS
    assert provider_factory["calls"][0]["provider"] == "local"
    assert provider_factory["calls"][0]["profile"].name == local_tuning.PROFILE_TUNED


def test_baseline_profile_keeps_day26_call(rag_service, provider_factory, monkeypatch):
    """baseline — ровно поведение дня 26: промпт режима и значения по умолчанию."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_BASELINE)

    rag_service.rag_query(QUESTION, provider="local")

    call = provider_factory["local"].calls[0]
    assert call["system"] == rag_mode.RAG_SYSTEM_PROMPT
    assert call["temperature"] is None and call["max_tokens"] is None
    assert provider_factory["calls"][0]["profile"] is None


def test_explicit_profile_overrides_environment(rag_service, provider_factory,
                                                monkeypatch):
    """Явный профиль важнее окружения: так прогон дня 29 гоняет оба варианта."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_TUNED)

    rag_service.rag_query(QUESTION, provider="local",
                          profile=local_tuning.baseline_profile())

    call = provider_factory["local"].calls[0]
    assert call["system"] == rag_mode.RAG_SYSTEM_PROMPT
    assert call["temperature"] == config.DEFAULT_TEMPERATURE
    assert call["max_tokens"] is None, "предел ответа baseline — как у типа задачи"
