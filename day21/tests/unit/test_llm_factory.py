"""Тесты фабрики провайдера и домена имён (день 26).

Проверяется ровно стык двух миров: имя провайдера из конфига или аргумента
превращается в клиента — ``LocalLLMClient`` (HTTP к Ollama) или ``LLMClient``
(обёртка DeepSeek). Сеть не нужна: локальный клиент создаётся без запросов, а
облачный — на фабрике-заглушке вместо SDK.
"""
import pytest

from backend.core import config
from backend.domain import llm_provider, local_tuning
from backend.services.llm_client import LLMClient
from backend.services.llm_factory import get_llm_client
from backend.services.local_llm_client import LocalLLMClient


def test_resolve_without_argument_uses_config(monkeypatch):
    """Аргумента нет — берётся провайдер процесса (значение из .env)."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "local")

    assert llm_provider.resolve(None) == "local"
    assert llm_provider.resolve("") == "local"


def test_resolve_normalizes_case_and_spaces():
    """Регистр и пробелы не значат ничего: «LOCAL » — то же, что «local»."""
    assert llm_provider.resolve("LOCAL ") == "local"
    assert llm_provider.normalize_provider("  DeepSeek  ") == "deepseek"


def test_resolve_rejects_unknown_name():
    """Незнакомое имя — ошибка: подменять провайдера молча нельзя."""
    with pytest.raises(ValueError) as exc:
        llm_provider.resolve("nope")

    assert "nope" in str(exc.value) and "local" in str(exc.value)


def test_label_falls_back_to_raw_name():
    """Подпись есть у известных провайдеров; незнакомое имя показывается как есть."""
    assert llm_provider.label("local") == llm_provider.PROVIDER_LABELS["local"]
    assert llm_provider.label("прочее") == "прочее"


def test_local_provider_returns_ollama_client():
    """Провайдер local: клиент Ollama с моделью и адресом из конфига, без сети."""
    client = get_llm_client("local", agent_id="test-agent")

    assert isinstance(client, LocalLLMClient)
    assert client.model == config.LOCAL_LLM_MODEL
    assert client.base_url == config.LOCAL_LLM_URL
    assert client.timeout == config.LOCAL_LLM_TIMEOUT


def test_local_provider_accepts_timeout_override():
    """Предел ожидания переопределяется вызовом: мини-чат даёт память свой."""
    client = get_llm_client("local", timeout=7.5)

    assert client.timeout == 7.5


def test_profile_sets_model_and_context_window():
    """Профиль дня 29 задаёт модель и окно контекста локального клиента."""
    profile = local_tuning.create("tuned", model="qwen2.5-coder:14b-instruct-q3_K_M")

    client = get_llm_client("local", profile=profile)

    assert client.model == "qwen2.5-coder:14b-instruct-q3_K_M"
    assert client.num_ctx == profile.num_ctx


def test_without_profile_ollama_defaults_apply():
    """Без профиля — поведение дня 26: модель конфига и окно по умолчанию Ollama."""
    client = get_llm_client("local")

    assert client.model == config.LOCAL_LLM_MODEL
    assert client.num_ctx is None


def test_deepseek_provider_returns_wrapper_on_factory():
    """Провайдер deepseek: обёртка дня 21, клиент SDK берётся из фабрики."""
    client = get_llm_client("deepseek", agent_id="test-agent",
                            client_factory=lambda: object())

    assert isinstance(client, LLMClient)
    assert client.agent_id == "test-agent"
    assert client.client() is not None


def test_deepseek_provider_requires_factory_only_at_call():
    """Обёртка без фабрики создаётся: ошибка возникает при первом обращении к SDK."""
    client = get_llm_client("deepseek")

    assert isinstance(client, LLMClient)
    with pytest.raises(RuntimeError):
        client.client()
