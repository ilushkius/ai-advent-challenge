"""Юнит-тесты службы ассистента разработчика (день 31): ответы и отказы ``/help``.

Проверяется ОДНО поведение — как служба собирает контекст и что отдаёт в ответе:
тип вопроса, фрагменты документации, вызовы инструментов, предупреждения и текст отказа.
Панели раздела (каталог инструментов, git-контекст, соединение со stdio-сервером) —
в ``tests/unit/test_dev_assistant_panels.py``, фейки — в ``tests/dev_assistant_fakes.py``.
Без сети, моделей и процессов: индекс — фейк, MCP-клиент — фейк, модель — ``RagStubClient``.
Настоящий корпус и настоящий процесс ``dev_server`` проверяет slow-интеграция
(``tests/integration/test_dev_assistant_flow.py``).

Обязательные сценарии задания — классификация «git против документации»
(``test_classify_question_kind``) и ответ по документации с источниками
(``test_handle_help_answers_from_documentation``).
"""
from __future__ import annotations

import pytest

from backend.domain import dev_assistant, llm_provider, rag_corpus_spec
from backend.services.index_service import IndexNotBuiltError
from backend.services.llm_client import LLMClient
from backend.services.mcp_errors import MCPCallError
from backend.storage.llm_usage_store import LLMUsageStore

from dev_assistant_fakes import HITS, FakeIndexService, FakeMCP, make_service
from rag_fakes import GROUNDED_REPLY, RagStubClient


@pytest.fixture
def dev_stub() -> RagStubClient:
    """Заглушка DeepSeek: пишет сообщения вызова и отвечает текстом про корпус."""
    return RagStubClient()


@pytest.fixture
def dev_client(session_factory, dev_stub) -> LLMClient:
    """Обёртка вызова модели на заглушке и временном журнале расходов."""
    return LLMClient(agent_id=dev_assistant.AGENT_ID,
                     client_factory=lambda: dev_stub,
                     store=LLMUsageStore(session_factory=session_factory))


@pytest.mark.parametrize("question,expected", [
    ("/help как устроена память агента?", dev_assistant.KIND_DOCS),
    ("/help что в текущей git-ветке?", dev_assistant.KIND_GIT),
    ("/help покажи структуру проекта", dev_assistant.KIND_GIT),
    ("/help какие файлы изменены?", dev_assistant.KIND_GIT),
    ("/help как запустить тесты?", dev_assistant.KIND_DOCS),
    ("какие файлы изменены и как устроен RAG?", dev_assistant.KIND_MIXED),
])
def test_classify_question_kind(question, expected):
    """Тип вопроса по маркерам: git против документации и смешанный случай."""
    text = dev_assistant.normalize_question(question)
    assert dev_assistant.classify_question(text) == expected


def test_handle_help_answers_from_documentation(dev_client, dev_stub):
    """Вопрос по документации: ответ модели, источники RAG и ни одного вызова MCP."""
    mcp = FakeMCP()
    service = make_service(client=dev_client, mcp=mcp)

    record = service.handle_help("/help как устроена память агента?",
                                 llm_provider.PROVIDER_DEEPSEEK)

    assert record["question"] == "как устроена память агента?"
    assert record["question_type"] == dev_assistant.KIND_DOCS
    assert record["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert record["answer"] == GROUNDED_REPLY
    assert record["duration_ms"] >= 0
    assert record["warnings"] == []
    assert mcp.calls == []
    assert record["mcp_tools_used"] == []
    assert [(item["source"], item["section"], item["chunk_id"], item["score"])
            for item in record["sources"]] == [
        ("day21-docs-architecture.md", "Три слоя памяти", "c-1", 0.83),
        ("day21-docs-usage.md", "Тесты", "c-2", 0.61),
    ]
    prompt = dev_stub.calls[-1]["messages"][-1]["content"]
    assert HITS[0]["content"] in prompt and HITS[1]["content"] in prompt
    assert dev_assistant.CONTEXT_DOCS_HEADER in prompt


def test_handle_help_uses_mcp_for_git_question(dev_client, dev_stub):
    """Вопрос про ветку: один вызов ``get_git_branch``, документация не ищется."""
    index = FakeIndexService()
    mcp = FakeMCP()
    service = make_service(index=index, mcp=mcp, client=dev_client)

    record = service.handle_help("/help что в текущей git-ветке?")

    assert record["question_type"] == dev_assistant.KIND_GIT
    assert mcp.calls == [(dev_assistant.TOOL_GIT_BRANCH, {})]
    assert index.calls == []
    assert record["sources"] == []
    assert record["mcp_tools_used"][0]["tool"] == dev_assistant.TOOL_GIT_BRANCH
    assert record["mcp_tools_used"][0]["ok"] is True
    prompt = dev_stub.calls[-1]["messages"][-1]["content"]
    assert dev_assistant.CONTEXT_GIT_HEADER in prompt
    assert "main" in prompt and dev_assistant.CONTEXT_DOCS_HEADER not in prompt


def test_mixed_question_uses_docs_and_tools(dev_client):
    """Смешанный вопрос: документация плюс оба git-инструмента плана."""
    mcp = FakeMCP()
    service = make_service(mcp=mcp, client=dev_client)

    record = service.handle_help("какие файлы изменены и как устроен RAG?")

    assert record["question_type"] == dev_assistant.KIND_MIXED
    assert [name for name, _ in mcp.calls] == [dev_assistant.TOOL_GIT_BRANCH,
                                               dev_assistant.TOOL_GIT_DIFF]
    assert record["sources"]
    assert [item["tool"] for item in record["mcp_tools_used"]] == [
        dev_assistant.TOOL_GIT_BRANCH, dev_assistant.TOOL_GIT_DIFF]


def test_failed_tool_is_recorded_and_docs_still_answer(dev_client):
    """Ошибка инструмента — предупреждение и запись ``ok=False``, ответ всё равно есть.

    Вопрос смешанный: документация даёт контекст, поэтому отказ инструмента виден
    как предупреждение поверх ответа, а не превращает ответ в «нет данных».
    """
    mcp = FakeMCP(tool_error="git не сработал: нет в PATH")
    service = make_service(mcp=mcp, client=dev_client)

    record = service.handle_help("какие файлы изменены и как устроен RAG?")

    assert all(item["ok"] is False for item in record["mcp_tools_used"])
    assert "нет в PATH" in record["mcp_tools_used"][0]["error"]
    assert any("get_git_branch" in warning for warning in record["warnings"])
    assert record["sources"]
    assert record["answer"] == GROUNDED_REPLY


def test_unavailable_mcp_is_recorded(dev_client):
    """Обрыв связи MCP: все плановые инструменты в записях с ошибкой, ответ по RAG."""
    mcp = FakeMCP(error=MCPCallError("сервер не отвечает"))
    service = make_service(mcp=mcp, client=dev_client)

    record = service.handle_help("какие файлы изменены и как устроен RAG?")

    assert [item["tool"] for item in record["mcp_tools_used"]] == [
        dev_assistant.TOOL_GIT_BRANCH, dev_assistant.TOOL_GIT_DIFF]
    assert all(item["ok"] is False for item in record["mcp_tools_used"])
    assert any("недоступен" in warning for warning in record["warnings"])
    assert record["sources"]
    assert record["answer"] == GROUNDED_REPLY


def test_missing_index_is_a_warning(dev_client):
    """Пустой индекс документации: предупреждение, а git-ответ всё равно приходит."""
    index = FakeIndexService(error=IndexNotBuiltError("Индекс стратегии пуст"))
    mcp = FakeMCP()
    service = make_service(index=index, mcp=mcp, client=dev_client)

    record = service.handle_help("какие файлы изменены и как устроен RAG?")

    assert any("Индекс документации пуст" in warning for warning in record["warnings"])
    assert record["sources"] == []
    assert mcp.calls == [(dev_assistant.TOOL_GIT_BRANCH, {}),
                         (dev_assistant.TOOL_GIT_DIFF,
                          {"lines": dev_assistant.DEFAULT_DIFF_LINES})]
    assert record["answer"] == GROUNDED_REPLY


def test_no_context_at_all_skips_the_model(dev_client, dev_stub):
    """Ни документации, ни MCP: модель не вызывается, ответ — честный отказ."""
    service = make_service(index=FakeIndexService(hits=[]),
                           mcp=FakeMCP(empty_tools=(dev_assistant.TOOL_GIT_BRANCH,)),
                           client=dev_client)

    record = service.handle_help("что в текущей git-ветке?")

    assert record["answer"] == dev_assistant.EMPTY_CONTEXT_ANSWER
    assert dev_stub.calls == []
    assert record["mcp_tools_used"][0]["ok"] is True
    assert any(dev_assistant.TOOL_GIT_BRANCH in warning for warning in record["warnings"])


def test_unavailable_llm_is_reported(session_factory):
    """Недоступный провайдер: честный текст в ответе и предупреждение, не исключение."""
    stub = RagStubClient(error=RuntimeError("сеть недоступна"))
    client = LLMClient(agent_id=dev_assistant.AGENT_ID, client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    service = make_service(client=client)

    record = service.handle_help("/help как запустить тесты?")

    assert record["answer"].startswith("Провайдер «")
    assert "сеть недоступна" in record["answer"]
    assert record["warnings"]
    assert record["sources"]
    assert record["mcp_tools_used"] == []


def test_local_provider_failure_names_ollama(session_factory):
    """Сбой локального провайдера называется своим текстом, провайдер — в ответе."""
    stub = RagStubClient(error=RuntimeError("connection refused"))
    client = LLMClient(agent_id=dev_assistant.AGENT_ID, client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    service = make_service(client=client)

    record = service.handle_help("/help как запустить тесты?", llm_provider.PROVIDER_LOCAL)

    assert record["provider"] == llm_provider.PROVIDER_LOCAL
    assert record["answer"].startswith("Ollama не запущена")
    assert "connection refused" in record["answer"]


def test_text_only_tool_goes_into_context(dev_client, dev_stub):
    """Инструмент без структурированного результата попадает в контекст текстом."""
    service = make_service(mcp=FakeMCP(results={dev_assistant.TOOL_GIT_BRANCH: None}),
                           client=dev_client)

    record = service.handle_help("что в текущей git-ветке?")

    prompt = dev_stub.calls[-1]["messages"][-1]["content"]
    assert "текст без структуры" in prompt
    assert record["warnings"] == [] and record["mcp_tools_used"][0]["ok"] is True


def test_empty_question_is_rejected():
    """Пустой вопрос (и вопрос из одной команды ``/help``) — ``ValueError`` для роутера."""
    service = make_service()
    with pytest.raises(ValueError):
        service.handle_help("   ")
    with pytest.raises(ValueError):
        service.handle_help("/help   ")


def test_documentation_sources_are_indexed():
    """Таблица источников корпуса покрывает всю документацию ассистента."""
    indexed = {source.path for source in rag_corpus_spec.RAG_CORPUS_SOURCES}
    assert indexed >= set(dev_assistant.DOCUMENTATION_SOURCES)
