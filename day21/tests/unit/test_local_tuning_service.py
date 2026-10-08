"""Тесты прогона профилей (день 29): варианты, параметры вызова, ресурсы и отказы.

Прогон офлайн: фабрика клиентов подменена ``LocalDictStubClient``, а метрики Ollama —
функциями-заглушками (``local_tuning_service.snapshot``/``version``). Проверяется то,
чего не видно в тестах домена: что профиль доходит до вызова модели (системный промпт,
температура, предел ответа), что строк на каждый вопрос столько же, сколько вопросов,
что сбой вызова становится строкой ``error``, а полный отказ превращается в
``LocalLLMError`` — роутер переводит его в 502.
"""
import pytest

from backend.core import config
from backend.domain import local_tuning, local_tuning_eval, rag_mode
from backend.services import llm_factory, local_tuning_service
from backend.services.local_llm_client import LocalLLMError

from rag_fakes import LocalDictStubClient

#: Литерал есть в тестовом корпусе: на него обязан найтись фрагмент.
QUESTION = "Чему равен CHARS_PER_PAGE?"

#: Снимок ``GET /api/ps`` без запущенной модели: служба обязана его пережить.
PS = {"models": [], "vram_mb": 0, "total_mb": 0, "error": ""}


@pytest.fixture
def ollama(monkeypatch):
    """Точки подмены окружения Ollama: снимок ресурсов, версия и клиент модели."""
    stub = LocalDictStubClient()
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda *args, **kwargs: stub)
    monkeypatch.setattr(local_tuning_service, "snapshot", lambda: dict(PS))
    monkeypatch.setattr(local_tuning_service, "version", lambda: "0.12.0")
    return stub


def test_run_covers_profiles_and_reports_params(rag_service, ollama):
    """Вариант на каждый профиль: параметры, строки, ресурсы, сводка и пары."""
    result = local_tuning_service.run(rag_service, questions=[QUESTION],
                                      models=["stub-local:1b"])

    assert result["ollama_version"] == "0.12.0"
    assert result["url"] == config.LOCAL_LLM_URL
    assert result["top_k"] == rag_mode.RAG_DEFAULT_TOP_K
    assert result["strategy"] == rag_mode.RAG_DEFAULT_STRATEGY
    assert result["ps_before"] == PS
    assert [item["profile"] for item in result["profiles"]] == list(local_tuning.PROFILES)
    assert [variant["params"]["profile"] for variant in result["variants"]] == \
        list(local_tuning.PROFILES)
    assert [variant["params"]["model"] for variant in result["variants"]] == \
        ["stub-local:1b", "stub-local:1b"]
    assert all(len(variant["rows"]) == 1 for variant in result["variants"])
    assert all(variant["summary"]["questions"] == 1 for variant in result["variants"])
    assert [pair["model"] for pair in result["pairs"]] == ["stub-local:1b"]
    assert result["pairs"][0]["verdict"] in (
        local_tuning_eval.VERDICT_TUNED_BETTER,
        local_tuning_eval.VERDICT_BASELINE_BETTER, local_tuning_eval.VERDICT_SAME)
    assert result["variants"][0]["resources"]["error"] == ""
    assert result["variants"][0]["resources"]["tokens_per_second"] == 0.0


def test_run_passes_profile_settings_into_call(rag_service, ollama):
    """Профиль доходит до вызова: промпт, температура и предел ответа различаются.

    Это то, ради чего профиль живёт в домене: без него ``.env`` задал бы половину
    настроек, а вторая осталась бы зашитой в службе.
    """
    local_tuning_service.run(rag_service, questions=[QUESTION],
                             profiles=["baseline", "tuned"], models=["stub-local:1b"])

    baseline, tuned = ollama.calls
    assert baseline["system"] == rag_mode.RAG_SYSTEM_PROMPT
    assert baseline["temperature"] == config.DEFAULT_TEMPERATURE
    assert baseline["max_tokens"] is None
    assert tuned["system"] == local_tuning.LOCAL_TUNED_RAG_PROMPT
    assert tuned["temperature"] == local_tuning.LOCAL_LLM_TEMPERATURE
    assert tuned["max_tokens"] == local_tuning.LOCAL_LLM_CHAT_MAX_TOKENS


#: Второй вопрос: слова есть в тестовом корпусе, поэтому первый вызов проходит.
QUESTION_TWO = "Сколько символов на одну страницу корпуса?"


class FlakyClient(LocalDictStubClient):
    """Заглушка, падающая со второго вопроса: строка ``error`` рядом с успешной строкой."""

    def generate_with_context(self, **kwargs) -> dict:
        """После первого вызова модель «ломается» — так проверяется строка-ошибка."""
        if self.calls:
            self.error = RuntimeError("boom")
        return super().generate_with_context(**kwargs)


def test_run_reports_model_failure_as_row(rag_service, monkeypatch):
    """Сбой вызова — строка ``error`` с предупреждением, а не срыв всего прогона."""
    flaky = FlakyClient()
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda *args, **kwargs: flaky)
    monkeypatch.setattr(local_tuning_service, "snapshot", lambda: dict(PS))
    monkeypatch.setattr(local_tuning_service, "version", lambda: "")

    result = local_tuning_service.run(rag_service, questions=[QUESTION, QUESTION_TWO],
                                      profiles=["tuned"], models=["stub-local:1b"])

    rows = result["variants"][0]["rows"]
    assert [row["mode"] for row in rows] == ["rag", "error"]
    assert rows[1]["verdict"] == "ошибка модели, ответ без корпуса"
    assert "boom" in rows[1]["warning"]
    assert result["variants"][0]["summary"]["errors"] == 1


def test_run_of_dead_ollama_is_an_error(rag_service, monkeypatch):
    """Все строки с ошибкой — недоступная Ollama: ``LocalLLMError`` (роутер отдаст 502)."""
    broken = LocalDictStubClient(error=RuntimeError("connection refused"))
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda *args, **kwargs: broken)
    monkeypatch.setattr(local_tuning_service, "snapshot", lambda: dict(PS))
    monkeypatch.setattr(local_tuning_service, "version", lambda: "")

    with pytest.raises(LocalLLMError) as exc:
        local_tuning_service.run(rag_service, questions=[QUESTION])

    assert "connection refused" in str(exc.value)


def test_run_rejects_unknown_profile(rag_service, ollama):
    """Незнакомый профиль — ``ValueError`` до единого вызова модели (роутер: 400)."""
    with pytest.raises(ValueError) as exc:
        local_tuning_service.run(rag_service, questions=[QUESTION], profiles=["быстрый"])

    assert "быстрый" in str(exc.value)
    assert ollama.calls == []


def test_run_without_questions_uses_demo_set(rag_service, ollama):
    """Пустой список вопросов — десять контрольных вопросов демо."""
    result = local_tuning_service.run(rag_service, profiles=["tuned"],
                                      models=["stub-local:1b"])

    assert len(result["variants"][0]["rows"]) == 10
    assert result["variants"][0]["summary"]["questions"] == 10
