"""Интеграционный тест AI-ревью PR (день 32): весь путь целиком, но без сети.

Проверяется то, что юниты проверить не могут: настоящий ``git diff`` двух ref-ов
приходит через настоящий процесс ``mcp_servers/dev_server`` (то есть список файлов и
diff берутся из репозитория, а не из payload), diff обрезается до предела и об этом
появляется предупреждение, а RAG-контекст собирается по настоящему корпусу дня 22 —
поэтому источники включают и документацию проекта. Модель — заглушка
(``RagStubClient``), сети нет.

Тест медленный: поднимается процесс MCP-сервера и собирается корпус из 41 источника,
поэтому файл помечен ``slow``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.core import config
from backend.domain import code_review, dev_assistant, llm_provider, rag_mode
from backend.services.chunker import chunk_document
from backend.services.code_review_service import CodeReviewError, CodeReviewService
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.rag_corpus_index import CHUNK_STRATEGIES
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.storage.llm_usage_store import LLMUsageStore

from code_review_fakes import REVIEW_JSON
from rag_fakes import RagStubClient

pytestmark = pytest.mark.slow

#: Тот же путь, что у панели раздела: файл сервера разработки в пакете дня.
SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_servers" / "dev_server" / "server.py"


@pytest.fixture
def service(tmp_path, chunk_store, fake_embedder, session_factory):
    """Служба на настоящем корпусе, настоящем dev-сервере и заглушке модели."""
    loader = RagCorpusLoader(documents_dir=tmp_path / "rag_corpus")
    documents = loader.ensure_documents()
    index_service = IndexService(embedder=fake_embedder, store=chunk_store,
                                 index_dir=tmp_path / "index")
    for strategy in rag_mode.RAG_STRATEGIES:
        chunks = [chunk for document in documents
                  for chunk in chunk_document(document, CHUNK_STRATEGIES[strategy])]
        index_service.index_chunks(chunks, strategy)
    stub = RagStubClient(reply=REVIEW_JSON)
    client = LLMClient(agent_id=code_review.AGENT_ID,
                       client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    instance = CodeReviewService(
        index_service=index_service, llm_client=client,
        mcp_target=f'"{sys.executable}" "{SERVER.resolve()}"',
        mcp_cwd=config.MCP_FLEET_CWD, sleep=lambda _seconds: None)
    try:
        yield instance
    finally:
        instance.close()


def test_real_diff_comes_through_mcp(service):
    """Diff дня 30..31: инструменты реальные, diff обрезан, ревью разобрано."""
    record = service.review_pr({"base": "day30", "head": "day31",
                               "pr_label": "diff day30..day31"},
                               llm_provider.PROVIDER_DEEPSEEK)

    tools = [item["tool"] for item in record["mcp_tools_used"]]
    assert tools == [code_review.TOOL_PR_DIFF, code_review.TOOL_CHANGED_FILES]
    assert all(item["ok"] for item in record["mcp_tools_used"])
    assert "day21/backend/services/dev_assistant_service.py" in record["changed_files"]
    assert any("обрезан" in item for item in record["warnings"])
    assert record["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert record["review_text"] == REVIEW_JSON
    assert record["bugs"] and record["risks"]
    assert [item["priority"] for item in record["risks"]] == ["P0", "P1", "P3"]
    sources = {item["source"] for item in record["sources"]}
    assert sources & set(dev_assistant.DOCUMENTATION_SLUGS)
    assert record["duration_ms"] >= 0


def test_review_without_diff_and_broken_mcp_is_error():
    """Diff-а нет, а MCP не поднимается: ревью невозможно — ``CodeReviewError`` (502)."""
    service = CodeReviewService(
        mcp_target=f'"{sys.executable}" "-c" "import sys; sys.exit(1)"',
        mcp_cwd=config.MCP_FLEET_CWD, sleep=lambda _seconds: None)
    try:
        with pytest.raises(CodeReviewError):
            service.review_pr({"base": "day30", "head": "day31",
                               "provider": llm_provider.PROVIDER_DEEPSEEK})
    finally:
        service.close()
