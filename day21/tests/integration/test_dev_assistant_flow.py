"""Интеграционный тест ассистента разработчика (день 31): весь путь целиком.

Проверяется то, что юнит-тесты подменяют: НАСТОЯЩИЙ корпус (все 41 источник таблицы
``RAG_CORPUS_SOURCES``, включая документацию проекта), настоящий индекс FAISS на
фейковом эмбеддере и НАСТОЯЩИЙ stdio-сервер ``mcp_servers/dev_server/server.py``,
запущенный дочерним процессом того же интерпретатора. Модель — заглушка: тест не
ходит в сеть и не тратит токены, но путь «вопрос → поиск по документации → вызовы
инструментов → контекст → ответ» исполняется целиком.

Корпус собирается во временную папку (``tmp_path``): рабочие файлы дня тест не
трогает. Каталог индекса тоже временный. Git-инструменты читают НАСТОЯЩИЙ
репозиторий — иначе они и не инструменты: проверяются только устойчивые к содержимому
факты (непустая ветка, корень репозитория, четыре инструмента в каталоге).

Тест медленнее юнит-тестов (поднимается процесс MCP-сервера и собирается корпус),
поэтому файл помечен ``slow``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.core import config
from backend.domain import dev_assistant, llm_provider, rag_mode
from backend.services.chunker import chunk_document
from backend.services.dev_assistant_service import DevAssistantService
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.rag_corpus_index import CHUNK_STRATEGIES
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import RagStubClient

pytestmark = pytest.mark.slow

#: Тот же путь, что у панели раздела: файл сервера разработки в пакете дня.
SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_servers" / "dev_server" / "server.py"


@pytest.fixture
def service(tmp_path, chunk_store, fake_embedder, session_factory):
    """Служба на настоящем корпусе, настоящем сервере и заглушке модели.

    Корпус собирается всей таблицей источников: именно её читает день (пересборка
    ``scripts/reindex_with_docs.py``), поэтому расхождение «документация в таблице,
    но не в индексе» здесь и ловится.
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
    client = LLMClient(agent_id=dev_assistant.AGENT_ID,
                       client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    instance = DevAssistantService(
        index_service=index_service, llm_client=client,
        mcp_target=f'"{sys.executable}" "{SERVER.resolve()}"',
        mcp_cwd=config.MCP_FLEET_CWD, sleep=lambda _seconds: None)
    try:
        yield instance
    finally:
        instance.close()


def test_documentation_question_answers_with_doc_sources(service):
    """Вопрос про тесты: ответ модели, источники из документации и ни одного инструмента."""
    record = service.handle_help("/help как запустить тесты?")

    assert record["question_type"] == dev_assistant.KIND_DOCS
    assert record["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert record["answer"]
    assert record["mcp_tools_used"] == []
    sources = {item["source"] for item in record["sources"]}
    assert sources & set(dev_assistant.DOCUMENTATION_SLUGS)
    assert all(item["chunk_id"] for item in record["sources"])


def test_git_question_calls_real_dev_server(service):
    """Вопрос про ветку: настоящий инструмент сервера и состояние репозитория."""
    record = service.handle_help("/help что в текущей git-ветке?")

    assert [item["tool"] for item in record["mcp_tools_used"]] == [
        dev_assistant.TOOL_GIT_BRANCH]
    assert record["mcp_tools_used"][0]["ok"] is True
    assert record["sources"] == []
    assert record["warnings"] == []

    git = service.git_context()
    assert git["error"] == ""
    assert git["branch"]
    assert git["repo_root"].replace("\\", "/").endswith("ai-challenge")


def test_tools_catalog_lists_four_tools(service):
    """Каталог сервера: четыре инструмента со схемами аргументов и результата.

    ``get_project_structure`` возвращает ``dict``, поэтому SDK не публикует для него
    ``outputSchema`` — форма дерева описана докстрингом инструмента. Это контракт
    каталога, а не поломка: у трёх остальных инструментов схема результата есть.
    """
    catalog = service.tools()

    assert catalog["server"] == "dev_server"
    assert catalog["connected"] is True
    assert catalog["error"] == ""
    assert catalog["count"] == len(dev_assistant.TOOLS)
    tools = {tool["name"]: tool for tool in catalog["tools"]}
    assert set(tools) == set(dev_assistant.TOOLS)
    for tool in tools.values():
        assert tool["description"]
        assert tool["input_schema"].get("type") == "object"
    assert tools[dev_assistant.TOOL_LIST_FILES]["input_schema"]["properties"]["directory"]
    for name in (dev_assistant.TOOL_GIT_BRANCH, dev_assistant.TOOL_LIST_FILES,
                 dev_assistant.TOOL_GIT_DIFF):
        assert tools[name]["output_schema"].get("properties")


def test_structure_question_returns_tree(service):
    """Вопрос про структуру: инструмент дерева вызван и вернул данные без ошибки."""
    record = service.handle_help("/help покажи структуру проекта")

    calls = [item["tool"] for item in record["mcp_tools_used"]]
    assert calls[0] == dev_assistant.TOOL_GIT_BRANCH
    assert dev_assistant.TOOL_PROJECT_STRUCTURE in calls
    assert all(item["ok"] for item in record["mcp_tools_used"])
    assert record["answer"]
