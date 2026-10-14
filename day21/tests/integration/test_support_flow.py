"""Интеграционный тест ассистента поддержки (день 33): весь путь целиком.

Проверяется то, что юнит-тесты подменяют: НАСТОЯЩИЙ корпус (вся таблица
``RAG_CORPUS_SOURCES``, включая документацию поддержки), настоящий индекс FAISS на
фейковом эмбеддере и НАСТОЯЩИЙ stdio-сервер ``mcp_servers/support_server/server.py``,
запущенный дочерним процессом того же интерпретатора. Модель — заглушка: тест не
ходит в сеть и не тратит токены, но путь «вопрос → поиск по документации поддержки →
вызовы get_ticket/get_user/get_product_info → контекст → ответ» исполняется целиком.

Корпус собирается во временную папку (``tmp_path``): рабочие файлы дня тест не
трогает. Каталог индекса тоже временный. База поддержки, наоборот, читается НАСТОЯЩАЯ
(``backend/data/support_db.json``) — иначе проверялся бы фейк вместо того, что видит
поддержка.

Тест медленнее юнит-тестов (поднимается процесс MCP-сервера и собирается корпус),
поэтому файл помечен ``slow``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.core import config
from backend.domain import rag_mode, support
from backend.services.chunker import chunk_document
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.rag_corpus_index import CHUNK_STRATEGIES
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.services.support_service import SupportService
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import RagStubClient

pytestmark = pytest.mark.slow

#: Тот же путь, что у панели раздела: файл сервера поддержки в пакете дня.
SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_servers" / "support_server" / "server.py"


@pytest.fixture
def service(tmp_path, chunk_store, fake_embedder, session_factory):
    """Служба на настоящем корпусе, настоящем сервере поддержки и заглушке модели.

    Корпус собирается всей таблицей источников: именно её читает день (пересборка
    ``scripts/reindex_with_support.py``), поэтому расхождение «документация
    поддержки в таблице, но не в индексе» здесь и ловится.
    """
    loader = RagCorpusLoader(documents_dir=tmp_path / "rag_corpus")
    documents = loader.ensure_documents()
    index_service = IndexService(embedder=fake_embedder, store=chunk_store,
                                 index_dir=tmp_path / "index")
    for strategy in rag_mode.RAG_STRATEGIES:
        chunks = [chunk for document in documents
                  for chunk in chunk_document(document, CHUNK_STRATEGIES[strategy])]
        index_service.index_chunks(chunks, strategy)
    stub = RagStubClient()
    client = LLMClient(agent_id=support.AGENT_ID,
                       client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    instance = SupportService(
        index_service=index_service, llm_client=client,
        mcp_target=f'"{sys.executable}" "{SERVER.resolve()}"',
        mcp_cwd=config.MCP_FLEET_CWD, sleep=lambda _seconds: None)
    try:
        yield instance
    finally:
        instance.close()


def test_ticket_question_full_cycle(service):
    """Вопрос про вход с тикетом: тикет, профиль из тикета и документация поддержки."""
    record = service.answer("Почему не работает авторизация?", ticket_id="ticket_007")

    assert record["ticket_context"]["subject"] == "Не работает авторизация"
    assert record["ticket_context"]["priority"] == "high"
    assert record["user_context"]["id"] == "user_003"
    assert record["user_context"]["plan"] == "pro"
    assert [item["tool"] for item in record["mcp_tools_used"]][0] == support.TOOL_GET_TICKET
    assert all(item["ok"] for item in record["mcp_tools_used"])
    assert record["warnings"] == []
    assert record["answer"]
    sources = {item["source"] for item in record["sources"]}
    assert sources & set(support.SUPPORT_SLUGS)          # источник — FAQ/документация поддержки
    assert all(item["chunk_id"] for item in record["sources"])
