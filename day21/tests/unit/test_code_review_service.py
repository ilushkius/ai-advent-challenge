"""Юнит-тесты службы AI-ревью PR (день 32): структура ревью и отказы шагов.

Проверяется ОДНО поведение — что служба отдаёт на запрос ревью: набор полей, разбор
ответа модели (баги, архитектура, рекомендации, риски по приоритетам), откуда взяты
diff и список файлов (payload или MCP), какие предупреждения появляются и что
приходит вместо ревью, когда модель недоступна. Без сети, моделей и процессов:
индекс — фейк, MCP-клиент — фейк, модель — ``RagStubClient``
(фейки — ``tests/code_review_fakes.py``). Настоящий ``git diff`` и настоящий процесс
``dev_server`` проверяет slow-интеграция (``tests/integration/test_code_review_flow.py``).

Второй тест — порядок приоритетов: ``P0`` строго выше ``P3``, свободные формы
(``"p0"``, ``"P1 (важно)"``, ``2``, ``None``) приводятся к каноническому виду.
"""
from __future__ import annotations

import pytest

from backend.domain import code_review, llm_provider, rag_mode
from backend.domain.code_review import normalize_priority, sort_risks
from backend.services.code_review_service import CodeReviewService, CodeReviewError
from backend.services.llm_client import LLMClient
from backend.storage.llm_usage_store import LLMUsageStore

from code_review_fakes import (CASES, CHANGED_FILES, PR_DIFF, REVIEW_JSON,
                               FakeIndexService, FakeMCP, FailingStdioClient,
                               make_service)
from rag_fakes import RagStubClient

#: Поля ответа ревью — контракт для роутера, комментария в PR и отчёта.
EXPECTED_KEYS = {"review_text", "bugs", "architecture_issues", "recommendations",
                 "risks", "sources", "mcp_tools_used", "changed_files", "duration_ms",
                 "provider", "warnings"}


@pytest.fixture
def review_stub() -> RagStubClient:
    """Заглушка DeepSeek: пишет сообщения вызова и отвечает ревью по контракту."""
    return RagStubClient(reply=REVIEW_JSON)


def make_client(stub: RagStubClient, session_factory) -> LLMClient:
    """Обёртка вызова модели на заглушке и временном журнале расходов."""
    return LLMClient(agent_id=code_review.AGENT_ID,
                     client_factory=lambda: stub,
                     store=LLMUsageStore(session_factory=session_factory))


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_review_pr_structure(case, session_factory):
    """Ревью PR: контракт ответа, разбор находок и отказы шагов по кейсу."""
    stub = RagStubClient(reply=REVIEW_JSON, error=case.llm_error, error_times=None)
    mcp = FakeMCP(error=case.mcp_error)
    index = FakeIndexService(error=case.index_error)
    service = make_service(client=make_client(stub, session_factory), mcp=mcp,
                           index=index)

    record = service.review_pr(case.payload, llm_provider.PROVIDER_DEEPSEEK)

    assert set(record) == EXPECTED_KEYS
    assert record["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert record["duration_ms"] >= 0
    assert [item["tool"] for item in record["mcp_tools_used"]] == list(case.expect_mcp_tools)
    assert record["changed_files"] == CHANGED_FILES
    if case.expect_parsed:
        assert [item["priority"] for item in record["risks"]] == ["P0", "P1", "P3"]
        assert record["bugs"][0]["issue"].startswith("Запрос к базе")
        assert record["bugs"][0]["file"].endswith("index_service.py")
        assert record["bugs"][0]["line"] == "152"
        assert record["architecture_issues"][0]["recommendation"]
        assert record["recommendations"]
    else:
        assert record["bugs"] == [] and record["risks"] == []
        assert record["review_text"].startswith("Ревью недоступно")
    if case.expect_warning:
        assert any(case.expect_warning in item for item in record["warnings"])
    if case.expect_sources:
        sources = {item["source"] for item in record["sources"]}
        assert sources & {"day21-docs-architecture.md", "day21-docs-usage.md"}
        assert "day21-backend-services-index_service.py" in sources
    else:
        assert record["sources"] == []
    if case.expect_mcp_tools:
        assert mcp.calls
    else:
        assert mcp.calls == []
    prompt = stub.calls[-1]["messages"][-1]["content"]
    assert code_review.CONTEXT_DIFF_HEADER in prompt
    assert code_review.CONTEXT_DOCS_HEADER in prompt
    assert "from .lifespan import lifespan" in prompt
    assert stub.calls[-1]["messages"][0]["content"] == code_review.SYSTEM_PROMPT
    assert index.calls and index.calls[0]["strategy"] == rag_mode.RAG_DEFAULT_STRATEGY


def test_code_context_falls_back_to_path_query(session_factory):
    """Добавленные строки увели выдачу от файла — второй запрос по пути его находит."""
    slug = "day21-backend-services-index_service.py"
    index = FakeIndexService(detail_misses={slug})
    stub = RagStubClient(reply=REVIEW_JSON)
    service = make_service(client=make_client(stub, session_factory),
                           mcp=FakeMCP(), index=index)

    record = service.review_pr({"diff": PR_DIFF, "changed_files": CHANGED_FILES})

    assert slug in {item["source"] for item in record["sources"]}
    assert not any("нет фрагментов файла" in item for item in record["warnings"])
    queries = [call["query"] for call in index.calls]
    assert "day21/backend/services/index_service.py" in queries


def test_review_without_diff_and_broken_mcp_is_error(monkeypatch):
    """Ни diff-а, ни файлов, а MCP не поднялся: ревью невозможно — ``CodeReviewError``."""
    monkeypatch.setattr("backend.services.code_review_service.MCPClient",
                        FailingStdioClient)
    service = CodeReviewService(sleep=lambda _seconds: None)
    try:
        with pytest.raises(CodeReviewError):
            service.review_pr({"base": "day30", "head": "day31"})
    finally:
        service.close()


def test_review_without_diff_and_refs_is_rejected():
    """Ни diff-а, ни ref-ов: анализировать нечего — ``ValueError`` для роутера (400)."""
    service = make_service(client=object())
    with pytest.raises(ValueError):
        service.review_pr({"provider": llm_provider.PROVIDER_DEEPSEEK})


@pytest.mark.parametrize("raw,expected", [
    ("p0", "P0"),
    ("P1 (важно)", "P1"),
    (2, "P2"),
    ("0", "P0"),
    ("важно", "P3"),
    ("", "P3"),
    (None, "P3"),
])
def test_priority_order(raw, expected):
    """Приоритет приводится к P0–P3, а риски сортируются от P0 к P3 без потерь."""
    assert normalize_priority(raw) == expected
    ordered = sort_risks([{"priority": item} for item in ("P3", "P0", "P2", "P1", "P3")])
    assert [item["priority"] for item in ordered] == ["P0", "P1", "P2", "P3", "P3"]
