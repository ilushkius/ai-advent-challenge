"""Тесты службы мини-чата дня 25: источники, память задачи и история диалога.

Сеть не задействована: отбор подменён готовыми ступенями, клиент DeepSeek — заглушкой,
память и журнал расходов пишутся во временную базу (``session_factory``).
"""
import json

import pytest

from backend.agents.memory import MemoryManager
from backend.core import config
from backend.domain import rag_quotes
from backend.services.llm_client import LLMClient
from backend.services.mini_chat_memory import MINI_CHAT_AGENT_ID, MINI_CHAT_MEMORY_KEYS
from backend.services.mini_chat_service import (MiniChatService, MiniChatSessionError,
                                               get_mini_chat_service,
                                               make_mini_chat_client)
from backend.services.rag_service import get_rag_service
from backend.storage.database import AgentRecord, SessionLocal

from fixtures_mini_chat import build_service
from mini_chat_fakes import BrokenPayloadClient
from rag_fakes import GROUNDED_REPLY

#: Поля источника в ответе: те же, что у режима RAG (второй формы не заводим).
SOURCE_KEYS = ("source", "section", "chunk_id", "score")

QUESTION = "Чему равен CHARS_PER_PAGE?"
OTHER_QUESTION = "Какая стратегия чанков используется?"


def test_chat_returns_answer_with_sources(mini_chat_service, mini_chat_stub):
    """Ответ по корпусу: режим ``rag``, цитаты подтверждены, источник описан баллами."""
    session = mini_chat_service.start_session("alice")
    record = mini_chat_service.chat(session["session_id"], QUESTION)

    assert record["mode"] == "rag"
    assert record["answer"] == GROUNDED_REPLY
    assert record["fallback"] is False
    assert record["warning"] == ""
    assert record["question"] == QUESTION
    assert record["session_id"] == session["session_id"]
    assert record["task_id"] == "mc-" + session["session_id"]
    assert record["chunks_used"] == 1
    assert record["context_tokens"] > 0
    assert record["tokens"]["prompt_tokens"] == 100
    assert record["duration_ms"] >= 0

    assert len(record["sources"]) == 1
    source = record["sources"][0]
    assert {key: source[key] for key in SOURCE_KEYS} == {
        "source": "rules.md", "section": "Подсчёт", "chunk_id": "c1", "score": 0.91}
    assert record["quotes"] and record["quotes_verified"] is True
    assert record["confidence"] == rag_quotes.CONFIDENCE_HIGH

    # Отбор вызван ровно один раз и без реранкера: мини-чат берёт фрагменты как есть.
    retrieval = mini_chat_service.rag_service.retrieval
    assert [call["question"] for call in retrieval.calls] == [QUESTION]
    assert retrieval.calls[0]["rerank"] is False
    assert mini_chat_stub.answer_calls(), "ответ собирается моделью, а не заглушкой отбора"


def test_task_memory_updated_after_message(mini_chat_service, mini_chat_stub):
    """Память задачи обновлена после реплики: четыре ключа из JSON извлекателя."""
    session = mini_chat_service.start_session("alice")
    record = mini_chat_service.chat(session["session_id"], QUESTION)
    memory = mini_chat_service.get_task_memory(session["session_id"])

    assert memory["goal"] == "Настроить RAG-поиск по документации FastAPI"
    assert memory["terms"] == ["CHARS_PER_PAGE"]
    assert memory["constraints"] == ["не менять основной app.py"]
    assert memory["clarifications"] == ["нужны источники в каждом ответе"]
    assert memory["updated"] is True
    assert memory["updated_at"]
    assert memory["message_count"] == 2
    assert memory["task_id"] == session["task_id"]
    assert record["memory_updated"] is True
    assert record["memory_warning"] == ""
    assert record["task_memory"]["goal"] == memory["goal"]
    assert mini_chat_stub.memory_calls(), "извлекатель памяти вызван на диалоге"
    prompt = mini_chat_stub.memory_calls()[0]["messages"][-1]["content"]
    assert QUESTION in prompt and GROUNDED_REPLY in prompt


def test_history_saved_for_session(mini_chat_service, mini_chat_stub):
    """История диалога: реплики пользователя и ответы модели в порядке добавления."""
    session = mini_chat_service.start_session("alice")
    session_id = session["session_id"]
    mini_chat_service.chat(session_id, QUESTION)
    mini_chat_service.chat(session_id, OTHER_QUESTION)

    history = mini_chat_service.get_history(session_id)
    assert history["session_id"] == session_id
    assert history["task_id"] == session["task_id"]
    messages = history["messages"]
    assert [message["role"] for message in messages] == \
        ["user", "assistant", "user", "assistant"]
    assert [message["content"] for message in messages] == \
        [QUESTION, GROUNDED_REPLY, OTHER_QUESTION, GROUNDED_REPLY]
    assert all(message["created_at"] for message in messages)

    last_two = mini_chat_service.get_history(session_id, limit=2)["messages"]
    assert [message["content"] for message in last_two] == [OTHER_QUESTION, GROUNDED_REPLY]


def test_prompt_context_carries_rag_memory_and_dialog(mini_chat_service, mini_chat_stub):
    """Промпт ответа: RAG-блок, память задачи с напоминанием о цели, история диалога."""
    session = mini_chat_service.start_session("alice")
    session_id = session["session_id"]
    mini_chat_service.chat(session_id, QUESTION)
    mini_chat_service.chat(session_id, OTHER_QUESTION)

    context = mini_chat_stub.answer_calls()[-1]["messages"][1]["content"]
    assert "## Контекст из корпуса RAG" in context
    assert "## Память задачи" in context
    assert "Цель: Настроить RAG-поиск по документации FastAPI" in context
    assert "Текущая цель диалога: Настроить RAG-поиск по документации FastAPI" in context
    assert "## История диалога" in context
    assert f"Пользователь: {QUESTION}" in context
    assert context.rstrip().endswith(OTHER_QUESTION), "вопрос идёт последним"
    assert context.index("## Память задачи") < context.index("## История диалога")


def test_dont_know_when_context_is_weak(mini_chat_weak_service, mini_chat_stub):
    """Слабая выдача: режим «не знаю», модель ответа не вызывается вовсе."""
    session = mini_chat_weak_service.start_session("alice")
    record = mini_chat_weak_service.chat(session["session_id"], QUESTION)

    assert record["mode"] == "dont_know"
    assert record["answer"] == rag_quotes.DONT_KNOW_ANSWER
    assert record["sources"] == []
    assert record["quotes"] == []
    assert record["warning"]
    assert record["chunks_used"] == 0
    assert mini_chat_stub.answer_calls() == []
    assert mini_chat_stub.memory_calls(), "память задачи обновляется даже в режиме «не знаю»"


def test_error_mode_when_model_fails(mini_chat_broken_service):
    """Повторный сбой модели: режим ``error``, но реплика и ответ остаются в истории."""
    session = mini_chat_broken_service.start_session("alice")
    session_id = session["session_id"]
    record = mini_chat_broken_service.chat(session_id, QUESTION)

    assert record["mode"] == "error"
    assert record["answer"].startswith("Не удалось получить ответ")
    assert record["fallback"] is True
    assert record["sources"] == []
    assert record["chunks_used"] == 0
    assert record["memory_updated"] is False
    assert record["memory_warning"]
    assert len(mini_chat_broken_service.get_history(session_id)["messages"]) == 2


def test_memory_keeps_previous_state_when_extraction_fails(session_factory):
    """Модель ответила не JSON: память не обновлена, предыдущее состояние сохранено."""
    client = BrokenPayloadClient()
    service = build_service(client, session_factory)
    session = service.start_session("alice")
    session_id = session["session_id"]

    record = service.chat(session_id, QUESTION)
    assert record["mode"] == "rag"
    assert record["memory_updated"] is False
    assert record["memory_warning"]

    memory = service.get_task_memory(session_id)
    assert memory["updated"] is False
    assert memory["updated_at"] is None
    assert memory["goal"] == ""
    assert memory["terms"] == [] and memory["constraints"] == []
    assert memory["clarifications"] == []


def test_unknown_session_raises(mini_chat_service):
    """Неизвестная сессия — доменная ошибка (роутер переводит в 404), пустая реплика — 400."""
    with pytest.raises(MiniChatSessionError):
        mini_chat_service.get_task_memory("нет-такой")
    with pytest.raises(MiniChatSessionError):
        mini_chat_service.get_history("нет-такой")
    with pytest.raises(MiniChatSessionError):
        mini_chat_service.chat("нет-такой", QUESTION)
    with pytest.raises(MiniChatSessionError):
        mini_chat_service.chat("", QUESTION)

    session = mini_chat_service.start_session("alice")
    with pytest.raises(ValueError):
        mini_chat_service.chat(session["session_id"], "   ")


def test_end_session_clears_short_term_memory(mini_chat_service, monkeypatch):
    """Закрытие сессии: реплики удалены, повтор идемпотентен, память задачи остаётся."""
    session = mini_chat_service.start_session("alice")
    session_id = session["session_id"]
    mini_chat_service.chat(session_id, QUESTION)

    closed = mini_chat_service.end_session(session_id)
    assert closed == {"session_id": session_id, "task_id": session["task_id"],
                      "deleted": 2}
    assert mini_chat_service.end_session(session_id)["deleted"] == 0
    with pytest.raises(MiniChatSessionError):
        mini_chat_service.get_history(session_id)

    monkeypatch.setattr(config, "resolve_api_key", lambda: "")
    with pytest.raises(RuntimeError):
        make_mini_chat_client()


def test_make_mini_chat_client_builds_client(monkeypatch):
    """С заданным ключом фабрика отдаёт клиент DeepSeek, а не падает."""
    monkeypatch.setattr(config, "resolve_api_key", lambda: "test-key")
    client = make_mini_chat_client(timeout=1.0)
    assert hasattr(client, "chat")


def test_session_survives_service_restart(mini_chat_service, mini_chat_stub,
                                          session_factory):
    """Новый экземпляр службы видит сессию по репликам в базе (перезапуск бэкенда)."""
    session = mini_chat_service.start_session("alice")
    session_id = session["session_id"]
    mini_chat_service.chat(session_id, QUESTION)

    restarted = build_service(mini_chat_stub, session_factory)
    history = restarted.get_history(session_id)
    assert len(history["messages"]) == 2
    assert history["task_id"] == session["task_id"]
    assert restarted.get_task_memory(session_id)["goal"]


def test_update_task_memory_stores_json_rows(mini_chat_service):
    """Память задачи лежит в рабочей памяти четырьмя ключами с JSON-значениями."""
    session = mini_chat_service.start_session("alice")
    session_id = session["session_id"]
    mini_chat_service.chat(session_id, QUESTION)

    assert mini_chat_service.update_task_memory(session_id) is True
    rows = mini_chat_service.memory.get_working(MINI_CHAT_AGENT_ID, session["task_id"])
    assert {row["key"] for row in rows} == set(MINI_CHAT_MEMORY_KEYS)
    parsed = {row["key"]: json.loads(row["value"]) for row in rows}
    assert parsed["goal"] == "Настроить RAG-поиск по документации FastAPI"
    assert parsed["terms"] == ["CHARS_PER_PAGE"]
    assert json.loads(next(row["value"] for row in rows
                           if row["key"] == "clarifications")) == \
        ["нужны источники в каждом ответе"]


def test_second_session_reuses_agent_row(mini_chat_service):
    """Служебная строка агента одна: вторая сессия переиспользует якорь внешних ключей."""
    first = mini_chat_service.start_session("alice")
    second = mini_chat_service.start_session("bob")
    assert second["session_id"] != first["session_id"]
    assert second["task_id"] == "mc-" + second["session_id"]
    with mini_chat_service.session_factory() as session:
        assert session.get(AgentRecord, MINI_CHAT_AGENT_ID) is not None


def test_default_dependencies_are_resolved_lazily():
    """Без переданных зависимостей служба берёт базовую и службу RAG дня 22–24."""
    service = MiniChatService()
    assert service.session_factory is SessionLocal
    assert isinstance(service.memory, MemoryManager)
    assert service.rag_service is get_rag_service()
    assert isinstance(service.llm_client, LLMClient)
    assert isinstance(service.memory_client, LLMClient)
    assert service.memory_client is not service.llm_client


def test_get_mini_chat_service_is_singleton():
    """Служба процесса одна: точка подмены для тестов возвращает тот же объект."""
    first = get_mini_chat_service()
    assert isinstance(first, MiniChatService)
    assert get_mini_chat_service() is first
