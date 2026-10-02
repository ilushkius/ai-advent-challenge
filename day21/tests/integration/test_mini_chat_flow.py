"""Интеграционный тест мини-чата дня 25 (``slow``): сценарий целиком на корпусе.

Корпус собирается заново из файлов репозитория (``RAGService.prepare_corpus``), эмбеддер
подменён хеш-заглушкой, модель — заглушкой: проверяется связка «сценарий → отбор →
ответ с источниками → память задачи», а не качество настоящей модели. Для настоящих
ответов есть ``scripts/run_mini_chat_scenarios.py``.
"""
import json
from pathlib import Path

import pytest

from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.mini_chat_memory import MINI_CHAT_AGENT_ID, MINI_CHAT_MEMORY_KEYS
from backend.services.mini_chat_service import MiniChatService
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.services.rag_service import AGENT_ID, RAGService
from backend.storage.llm_usage_store import LLMUsageStore

from mini_chat_fakes import MiniChatStubClient
from rag_fakes import RagStubReranker

pytestmark = pytest.mark.slow

#: Поля источника в ответе: полный набор дня 22–24.
SOURCE_KEYS = {"source", "title", "section", "chunk_id", "score", "vector_score",
               "lexical_score", "rerank_score"}
#: Доля реплик сценария, которые обязаны прийти с источниками.
MIN_SOURCED_SHARE = 0.8
#: Сценарии прогона: тот же файл читает ``scripts/run_mini_chat_scenarios.py``.
SCENARIOS_PATH = (Path(__file__).resolve().parents[2] / "backend" / "data"
                  / "mini_chat_scenarios.json")


def _scenarios() -> list:
    """Сценарии прогона из файла данных."""
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]


def _chat_client(stub: MiniChatStubClient, session_factory) -> LLMClient:
    """Клиент мини-чата на заглушке: журнал расходов пишется во временную базу."""
    return LLMClient(agent_id=MINI_CHAT_AGENT_ID, client_factory=lambda: stub,
                     store=LLMUsageStore(session_factory=session_factory))


@pytest.fixture
def mini_chat_corpus_service(tmp_path, chunk_store, fake_embedder, session_factory):
    """Служба RAG на настоящем корпусе репозитория: фейковый эмбеддер, заглушки модели."""
    stub = MiniChatStubClient()
    service = RAGService(
        index_service=IndexService(embedder=fake_embedder, store=chunk_store,
                                   index_dir=tmp_path / "index"),
        loader=RagCorpusLoader(documents_dir=tmp_path / "rag_corpus"),
        store=chunk_store,
        llm_client=LLMClient(agent_id=AGENT_ID, client_factory=lambda: stub,
                             store=LLMUsageStore(session_factory=session_factory)),
        rerank_service=RagStubReranker(),
        sleep=lambda _seconds: None,
    )
    service.prepare_corpus()
    return service


def test_full_scenario_keeps_goal_and_sources(mini_chat_corpus_service,
                                              session_factory):
    """Первый сценарий целиком: ответы с источниками, цель не теряется, память очищается."""
    scenario = _scenarios()[0]
    messages = scenario["messages"]
    assert messages, "сценарий без сообщений не проверяет ничего"

    answer_stub = MiniChatStubClient()
    memory_stub = MiniChatStubClient()
    service = MiniChatService(
        rag_service=mini_chat_corpus_service,
        session_factory=session_factory,
        llm_client=_chat_client(answer_stub, session_factory),
        memory_client=LLMClient(agent_id=MINI_CHAT_AGENT_ID,
                                client_factory=lambda: memory_stub,
                                store=LLMUsageStore(session_factory=session_factory)),
    )
    session = service.start_session("scenario:integration")
    session_id = session["session_id"]

    records = [service.chat(session_id, message) for message in messages]

    assert all(record["answer"] for record in records)
    assert all(record["mode"] in {"rag", "dont_know"} for record in records)
    sourced = [record for record in records if record["mode"] == "rag"]
    assert len(sourced) >= MIN_SOURCED_SHARE * len(records)
    for record in sourced:
        assert record["sources"], f"режим rag без источников: {record['question']!r}"
        for source in record["sources"]:
            assert set(source) == SOURCE_KEYS
            assert source["score"] > 0
        assert record["context_tokens"] > 0

    final_memory = service.get_task_memory(session_id)
    assert final_memory["goal"], "цель сценария потеряна"
    assert isinstance(final_memory["terms"], list)
    assert isinstance(final_memory["constraints"], list)
    assert isinstance(final_memory["clarifications"], list)
    assert final_memory["message_count"] == 2 * len(messages)

    history = service.get_history(session_id)
    assert len(history["messages"]) == 2 * len(messages)

    rows = service.memory.get_working(MINI_CHAT_AGENT_ID, final_memory["task_id"])
    assert {row["key"] for row in rows} == set(MINI_CHAT_MEMORY_KEYS)

    assert service.end_session(session_id)["deleted"] == 2 * len(messages)
