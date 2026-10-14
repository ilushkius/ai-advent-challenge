"""Юнит-тесты службы ассистента поддержки (день 33): контекст, отказы и панели.

Проверяется ОДНО поведение — как служба собирает контекст клиента и что отдаёт в
ответе: профиль из тикета, вызовы инструментов, предупреждения, текст отказа.
Панельные методы (``users``, ``user``, ``ticket``, ``user_tickets``) и ленивое
соединение со stdio-сервером проверяются в тех же трёх функциях: тестовых функций
здесь ровно три, а набор фейков один (``tests/support_fakes.py``).
Без сети, моделей и процессов: индекс — фейк, MCP-клиент — фейк, модель —
``RagStubClient``. Настоящий корпус и настоящий процесс ``support_server`` проверяет
slow-интеграция (``tests/integration/test_support_flow.py``).
"""
from __future__ import annotations

import pytest

from backend.domain import llm_provider, rag_corpus_spec, support
from backend.services import support_service as support_module
from backend.services.index_service import IndexNotBuiltError
from backend.services.llm_client import LLMClient
from backend.services.mcp_errors import MCPCallError
from backend.services.support_service import SupportMCPError
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import GROUNDED_REPLY, RagStubClient
from support_fakes import (HITS, USER_STRUCTURED, FailingStdioClient, FakeIndexService,
                           FakeMCP, FakeStdioClient, make_service, product_result)


@pytest.fixture
def support_stub() -> RagStubClient:
    """Заглушка DeepSeek: пишет сообщения вызова и отвечает текстом про корпус."""
    return RagStubClient()


@pytest.fixture
def support_client(session_factory, support_stub) -> LLMClient:
    """Обёртка вызова модели на заглушке и временном журнале расходов."""
    return LLMClient(agent_id=support.AGENT_ID, client_factory=lambda: support_stub,
                     store=LLMUsageStore(session_factory=session_factory))


def test_answer_uses_user_context(support_client, support_stub):
    """Вопрос про тариф с профилем: профиль и раздел продукта, документация рядом.

    Проверяется весь путь одного вопроса: поиск по поддержке, два вызова MCP
    (профиль и раздел продукта), блоки контекста в промпте и поля ответа.
    """
    mcp = FakeMCP()
    service = make_service(client=support_client, mcp=mcp)

    record = service.answer("Как сменить тариф?", "user_001")

    assert record["user_context"]["name"] == USER_STRUCTURED["name"]
    assert record["user_context"]["plan"] == "pro"
    assert record["user_context"]["registered_at"] == USER_STRUCTURED["registered_at"]
    assert record["ticket_context"] is None
    assert record["product_context"]["area"] == support.AREA_BILLING
    assert record["product_context"]["title"] == support.AREA_LABELS[support.AREA_BILLING]
    assert [item["tool"] for item in record["mcp_tools_used"]] == [
        support.TOOL_GET_USER, support.TOOL_GET_PRODUCT_INFO]
    assert all(item["ok"] for item in record["mcp_tools_used"])
    assert [(item["source"], item["section"], item["score"])
            for item in record["sources"]] == [
        ("day21-docs-support-faq.md", "Как сменить тариф?", 0.83),
        ("day21-docs-support-troubleshooting.md", "Не работает вход", 0.61),
    ]
    assert record["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert record["duration_ms"] >= 0
    assert record["warnings"] == []
    assert record["answer"] == GROUNDED_REPLY
    prompt = support_stub.calls[-1]["messages"][-1]["content"]
    assert support.CONTEXT_USER_HEADER in prompt
    assert support.CONTEXT_DOCS_HEADER in prompt
    assert HITS[0]["content"] in prompt
    assert USER_STRUCTURED["name"] in prompt and USER_STRUCTURED["plan"] in prompt
    with pytest.raises(ValueError):
        service.answer("   ")


def test_answer_uses_ticket_context(support_client, support_stub):
    """Вопрос про вход с тикетом: тикет, профиль из тикета и раздел продукта.

    Тикет знает своего владельца: ``user_id`` вопроса пуст, и профиль приходит из
    поля ``user_id`` тикета. Ненайденный тикет — предупреждение, а не отказ.
    """
    service = make_service(client=support_client, mcp=FakeMCP())

    record = service.answer("Почему не работает авторизация?", None, "ticket_007")

    assert record["ticket_context"]["subject"] == "Не работает авторизация"
    assert record["ticket_context"]["status"] == "open"
    assert record["ticket_context"]["priority"] == "high"
    assert len(record["ticket_context"]["messages"]) == 3
    assert record["user_context"]["id"] == "user_003"
    assert record["product_context"]["area"] == support.AREA_AUTH
    assert [item["tool"] for item in record["mcp_tools_used"]] == [
        support.TOOL_GET_TICKET, support.TOOL_GET_USER, support.TOOL_GET_PRODUCT_INFO]
    assert record["warnings"] == []
    prompt = support_stub.calls[-1]["messages"][-1]["content"]
    assert support.CONTEXT_TICKET_HEADER in prompt
    assert "Не работает авторизация" in prompt and '"status": "open"' in prompt

    missing = make_service(client=support_client,
                           mcp=FakeMCP(not_found=(support.TOOL_GET_TICKET,)))
    gone = missing.answer("Почему не работает авторизация?", None, "ticket_999")

    assert gone["ticket_context"] is None
    assert gone["user_context"] is None
    assert gone["mcp_tools_used"][0]["tool"] == support.TOOL_GET_TICKET
    assert gone["mcp_tools_used"][0]["ok"] is True
    assert gone["warnings"][0].startswith(support.WARN_TICKET_NOT_FOUND.split("{")[0])
    assert gone["sources"]


def test_answer_without_context(support_client, support_stub, session_factory, monkeypatch):
    """Общий вопрос без профиля: только документация, MCP не вызывается.

    Здесь же — отказы службы (пустой индекс, недоступная модель, недоступный
    MCP-сервер) и панельные методы: они отвечают данными, а не стеком.
    """
    mcp = FakeMCP()
    service = make_service(client=support_client, mcp=mcp)

    record = service.answer("Расскажи, что умеет продукт")

    assert record["user_context"] is None
    assert record["ticket_context"] is None
    assert record["product_context"] is None
    assert record["mcp_tools_used"] == []
    assert mcp.calls == []
    assert record["sources"]
    assert record["answer"] == GROUNDED_REPLY
    assert support.CONTEXT_USER_HEADER not in support_stub.calls[-1]["messages"][-1]["content"]

    # (а) индекс поддержки пуст: предупреждение вместо исключения, модель не зовётся.
    empty = make_service(index=FakeIndexService(error=IndexNotBuiltError("Индекс пуст")),
                         client=support_client)
    blank = empty.answer("Расскажи, что умеет продукт")
    assert blank["warnings"] == [support.WARN_INDEX_EMPTY.format(error="Индекс пуст")]
    assert blank["answer"] == support.EMPTY_CONTEXT_ANSWER
    assert blank["sources"] == []

    # (б) провайдер недоступен: честный текст в ответе, локальный — своим шаблоном.
    broken_stub = RagStubClient(error=RuntimeError("сеть недоступна"))
    broken_client = LLMClient(agent_id=support.AGENT_ID,
                              client_factory=lambda: broken_stub,
                              store=LLMUsageStore(session_factory=session_factory))
    failed = make_service(client=broken_client).answer("Как сменить тариф?")
    assert failed["answer"].startswith("Провайдер «")
    assert "сеть недоступна" in failed["answer"]
    assert failed["warnings"]

    local = make_service(client=broken_client).answer("Как сменить тариф?",
                                                      provider=llm_provider.PROVIDER_LOCAL)
    assert local["provider"] == llm_provider.PROVIDER_LOCAL
    assert local["answer"].startswith("Ollama не запущена")
    with pytest.raises(ValueError):
        make_service(client=support_client).answer("Как сменить тариф?", provider="gemini")

    # (в) ошибка одного инструмента — предупреждение и запись ok=False, ответ есть.
    broken_tool = make_service(client=support_client, mcp=FakeMCP(tool_error="нет данных"))
    partial = broken_tool.answer("Как сменить тариф?", "user_003")
    assert any("get_user" in warning for warning in partial["warnings"])
    assert all(item["ok"] is False for item in partial["mcp_tools_used"])
    assert partial["answer"] == GROUNDED_REPLY

    # (г) обрыв связи с сервером: все записи с ошибкой, ответ по документации.
    dropped = make_service(client=support_client,
                           mcp=FakeMCP(error=MCPCallError("сервер не отвечает")))
    offline = dropped.answer("Как сменить тариф?", "user_003")
    assert all(item["ok"] is False for item in offline["mcp_tools_used"])
    assert any("недоступен" in warning for warning in offline["warnings"])
    assert offline["user_context"] is None and offline["sources"]

    # (д) соединение служба поднимает сама: один раз на процесс и закрывается по close().
    monkeypatch.setattr(support_module, "MCPClient", FakeStdioClient)
    own = support_module.SupportService(index_service=FakeIndexService(),
                                        llm_client=support_client,
                                        mcp_target="support-server", sleep=lambda _s: None)
    assert own.answer("Как сменить тариф?", "user_003")["mcp_tools_used"][0]["ok"] is True
    assert own.server.connected is True
    own.close()
    assert own.answer("Как сменить тариф?", "user_003")["sources"]

    # (е) сервер не поднимается: служба отвечает по RAG, панели отдают причину.
    monkeypatch.setattr(support_module, "MCPClient", FailingStdioClient)
    absent = support_module.SupportService(index_service=FakeIndexService(),
                                           llm_client=support_client,
                                           mcp_target="нет-такой-команды",
                                           sleep=lambda _s: None)
    fallback = absent.answer("Как сменить тариф?", "user_003")
    assert any(support.WARN_MCP_UNAVAILABLE.split("{")[0] in warning
               for warning in fallback["warnings"])
    assert fallback["user_context"] is None
    assert fallback["answer"] == GROUNDED_REPLY
    assert absent.users()["count"] == 0 and absent.users()["error"]
    assert absent.user_tickets("user_003")["tickets"] == []
    with pytest.raises(SupportMCPError):
        absent.user("user_003")
    with pytest.raises(SupportMCPError):
        absent.ticket("ticket_007")

    # (ж) панельные методы на живом соединении: каталог, профиль, тикеты.
    panel = make_service(client=support_client, mcp=FakeMCP())
    assert [item["id"] for item in panel.users()["users"]] == ["user_003", "user_001"]
    assert panel.users()["count"] == 2 and panel.users()["error"] == ""
    assert panel.user("user_003")["user"]["id"] == "user_003"
    assert panel.ticket("ticket_007")["ticket"]["subject"] == "Не работает авторизация"
    assert panel.user_tickets("user_003")["count"] == 2
    panel.close()

    # (з) запись не найдена: панель отдаёт причину, а не пустой профиль.
    absent_user = make_service(client=support_client,
                               mcp=FakeMCP(not_found=(support.TOOL_GET_USER,
                                                      support.TOOL_GET_TICKET)))
    assert absent_user.user("user_999")["user"] is None
    assert absent_user.user("user_999")["error"] == "not found"
    assert absent_user.ticket("ticket_999")["ticket"] is None
    assert absent_user.ticket("ticket_999")["error"] == "not found"

    # (и) инструмент ответил ошибкой: панели показывают её текст, не падая.
    error_only = make_service(client=support_client, mcp=FakeMCP(tool_error="каталог упал"))
    assert error_only.users()["error"] == "каталог упал"
    assert error_only.user_tickets("user_003")["error"] == "каталог упал"
    assert error_only.user("user_003")["user"] is None

    # (к) фабрика клиента DeepSeek: без ключа — понятный отказ, с ключом — клиент.
    monkeypatch.setattr(support_module.config, "resolve_api_key", lambda: "")
    with pytest.raises(RuntimeError):
        support_module.make_support_client()
    monkeypatch.setattr(support_module.config, "resolve_api_key", lambda: "test-key")
    assert support_module.make_support_client() is not None

    # (л) неизвестный раздел продукта: инструмент ответил, области нет — предупреждение.
    unknown = make_service(client=support_client,
                           mcp=FakeMCP(results={support.TOOL_GET_USER: USER_STRUCTURED},
                                       not_found=(support.TOOL_GET_PRODUCT_INFO,)))
    area_missing = unknown.answer("Как сменить тариф?", "user_003")
    assert area_missing["product_context"] is None
    assert area_missing["mcp_tools_used"][-1]["ok"] is True
    assert any(support.WARN_TOOL_FAILED.split("{")[0] in warning
               for warning in area_missing["warnings"])

    # (м) раздел продукта по известной области приходит с описанием и FAQ.
    described = make_service(client=support_client,
                             mcp=FakeMCP(results={support.TOOL_GET_PRODUCT_INFO:
                                                  product_result(support.AREA_API)}))
    api_record = described.answer("Как получить API-ключ?")
    assert api_record["product_context"]["area"] == support.AREA_API
    assert api_record["product_context"]["faq"]

    # документация поддержки действительно попала в таблицу источников корпуса.
    indexed = {source.path for source in rag_corpus_spec.RAG_CORPUS_SOURCES}
    assert indexed >= set(support.SUPPORT_SOURCES)
    assert set(support.SUPPORT_SLUGS) == {"day21-docs-support-faq.md",
                                         "day21-docs-support-troubleshooting.md",
                                         "day21-docs-support-api_reference.md"}
