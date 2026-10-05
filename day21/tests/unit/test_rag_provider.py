"""Тесты пути провайдера через службы RAG и мини-чата (день 26).

Проверяется то, ради чего переключатель и сделан: при ``provider="local"`` служба
берёт клиента у фабрики провайдера (HTTP к Ollama), а не свою подменённую обёртку
DeepSeek, и кладёт имя провайдера в запись ответа. Незнакомое имя — отказ до поиска
и до вызова модели: молчаливая подмена показала бы в отчёте не того провайдера.
"""
import pytest

from backend.core import config
from backend.domain import llm_provider
from backend.services import llm_factory

from rag_fakes import GROUNDED_REPLY, LocalDictStubClient

QUESTION = "Чему равен CHARS_PER_PAGE?"


@pytest.fixture
def local_client(monkeypatch):
    """Фабрика провайдера подменена локальным клиентом-словарём: сети нет."""
    client = LocalDictStubClient()
    monkeypatch.setattr(llm_factory, "get_llm_client",
                        lambda *args, **kwargs: client)
    return client


# ---------- RAG по корпусу ----------
def test_rag_query_with_local_provider_uses_factory(rag_service, local_client):
    """Провайдер local: клиент берётся у фабрики, ответ-словарь читается как обычно."""
    record = rag_service.rag_query(QUESTION, provider="local")

    assert record["provider"] == "local"
    assert record["mode"] == "rag"
    assert record["answer"] == GROUNDED_REPLY.strip()
    assert record["tokens"]["completion_tokens"] == 0
    assert record["tokens"]["cost_estimate"] == 0.0
    assert local_client.calls and local_client.calls[0]["task_type"] == \
        config.LLM_TASK_CHAT
    assert local_client.calls[0]["context"], "контекст корпуса ушёл в локальный клиент"


def test_rag_query_without_provider_keeps_injected_client(rag_service, rag_stub,
                                                          monkeypatch):
    """Провайдер не назван: работает переданная службе заглушка облачного клиента.

    Значение по умолчанию задаётся явно: у чужого ``.env`` оно может быть ``local``,
    и тогда тест проверял бы не то.
    """
    monkeypatch.setattr(config, "LLM_PROVIDER", llm_provider.PROVIDER_DEEPSEEK)

    record = rag_service.rag_query(QUESTION)

    assert record["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert rag_stub.calls, "облачный клиент службы обойдён"


def test_rag_query_rejects_unknown_provider_before_model(rag_service):
    """Незнакомый провайдер — отказ до поиска, а не режим «не знаю»."""
    with pytest.raises(ValueError) as exc:
        rag_service.rag_query(QUESTION, provider="nope")

    assert "nope" in str(exc.value)


# ---------- мини-чат ----------
def test_mini_chat_uses_local_provider_for_answer_and_memory(mini_chat_service,
                                                             local_client):
    """Провайдер local: и ответ, и извлечение памяти идут через фабрику провайдера."""
    session = mini_chat_service.start_session("bob")

    record = mini_chat_service.chat(session["session_id"], QUESTION, provider="local")

    assert record["provider"] == "local"
    assert record["mode"] == "rag"
    assert record["answer"] == GROUNDED_REPLY.strip()
    assert record["tokens"]["completion_tokens"] == 0
    # Память извлекается тем же клиентом (ответ без JSON — обновления нет), а в
    # предупреждении стоит предел ожидания локальной модели, а не облачные 5 секунд.
    assert record["memory_updated"] is False
    assert str(int(config.LOCAL_LLM_TIMEOUT)) in record["memory_warning"]
    assert len(local_client.calls) >= 2


def test_mini_chat_rejects_unknown_provider(mini_chat_service):
    """Незнакомый провайдер мини-чата — ошибка значения: роутер переводит её в 400."""
    session = mini_chat_service.start_session("carol")

    with pytest.raises(ValueError) as exc:
        mini_chat_service.chat(session["session_id"], QUESTION, provider="nope")

    assert "nope" in str(exc.value)
