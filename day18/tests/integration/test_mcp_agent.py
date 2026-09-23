"""Тесты шага MCP в агенте (день 17): решение по реплике и данные в промпте.

Проверяется то, что день добавляет к ходу агента: инструмент вызывается только по
ключевым словам реплики, его данные уходят системным блоком в тот же запрос (это
видно и в сообщениях клиента DeepSeek, и в отчёте ``record["system_prompt"]``), а
неудачи — отказ правил, ошибка инструмента, отсутствие соединения — ход не роняют:
ответ всё равно приходит со статусом ``ok``.
"""
import pytest

from backend.services.mcp_registry import MCPRegistry

from mcp_fakes import FAKE_TOOL_CATALOG, make_mcp_factory
from support import FakeClient, create_agent, seed_invariant

QUESTION = "Найди информацию о пользователе с ID 1"
USER = {"id": 1, "name": "Leanne Graham", "city": "Gwenborough"}
BLOCK_HEADER = "## Данные MCP-инструмента"


def _agent(session_factory, monkeypatch, factory, fake=None):
    """Агент с фейковым реестром MCP и подменённым клиентом DeepSeek."""
    registry = MCPRegistry(client_factory=factory)
    if factory is not None:
        registry.connect("uvx mcp-server-fetch")
    agent = create_agent(session_factory, "mcp01", mcp_registry=registry)
    fake_client = fake or FakeClient()
    monkeypatch.setattr(agent, "_make_client", lambda: fake_client)
    agent.fake_client = fake_client
    agent.refresh_context_state()
    return agent


@pytest.fixture
def factory():
    """Фабрика MCP-клиентов с инструментами своего сервера и готовым ответом."""
    return make_mcp_factory(tools=FAKE_TOOL_CATALOG, call_result=USER)


def test_generate_calls_tool_and_puts_data_into_prompt(session_factory, monkeypatch,
                                                       factory):
    """Реплика про пользователя: вызов ``get_user`` и данные в системном промпте."""
    agent = _agent(session_factory, monkeypatch, factory)

    record = agent.generate(QUESTION)
    assert record["status"] == "ok"
    report = record["mcp"]
    assert report["tool"] == "get_user"
    assert report["arguments"] == {"user_id": 1}
    assert report["state"] == "done" and report["called"] is True
    assert report["used_in_prompt"] is True and report["added_tokens"] > 0
    assert report["result"]["structured"] == USER

    system = agent.fake_client.calls[-1]["messages"][0]
    assert system["role"] == "system"
    assert BLOCK_HEADER in system["content"] and "Leanne Graham" in system["content"]
    assert BLOCK_HEADER in record["system_prompt"]
    assert factory.created[0].call_calls == [{"tool": "get_user",
                                             "arguments": {"user_id": 1}}]


def test_generate_without_keywords_does_not_call_tool(session_factory, monkeypatch,
                                                      factory):
    """Без ключевых слов инструмент не вызывается и промпт не меняется."""
    agent = _agent(session_factory, monkeypatch, factory)

    record = agent.generate("Сколько будет 2+2?")
    assert record["status"] == "ok"
    report = record["mcp"]
    assert report["detected"] is False and report["called"] is False
    assert report["used_in_prompt"] is False and report["added_tokens"] == 0
    assert BLOCK_HEADER not in record["system_prompt"]
    assert factory.created[0].call_calls == []


def test_generate_without_number_falls_back_to_missing_argument(session_factory,
                                                                monkeypatch, factory):
    """Реплика без номера: вызов отклонён правилами, ответ всё равно приходит."""
    agent = _agent(session_factory, monkeypatch, factory)

    record = agent.generate("Расскажи про пользователя")
    assert record["status"] == "ok"
    report = record["mcp"]
    assert report["accepted"] is False
    assert report["reason_code"] == "bad_arguments"
    assert "user_id" in report["error"]
    assert report["used_in_prompt"] is False
    assert factory.created[0].call_calls == []


def test_generate_without_connection_reports_it(session_factory, monkeypatch):
    """Без MCP-подключения шаг пропускается: агент отвечает как обычно."""
    agent = _agent(session_factory, monkeypatch, None)

    record = agent.generate(QUESTION)
    assert record["status"] == "ok"
    report = record["mcp"]
    assert report["connected"] is False and report["detected"] is False
    assert report["used_in_prompt"] is False
    assert record["response"]


def test_tool_error_does_not_break_the_turn(session_factory, monkeypatch):
    """Ошибка инструмента видна в отчёте, но ход завершается успешно."""
    factory = make_mcp_factory(tools=FAKE_TOOL_CATALOG, call_error="id не найден")
    agent = _agent(session_factory, monkeypatch, factory)

    record = agent.generate(QUESTION)
    assert record["status"] == "ok"
    report = record["mcp"]
    assert report["state"] == "failed" and report["reason_code"] == "tool_error"
    assert report["error"] == "id не найден"
    assert report["used_in_prompt"] is False
    assert BLOCK_HEADER not in record["system_prompt"]


def test_transport_failure_does_not_break_the_turn(session_factory, monkeypatch):
    """Сбой связи с сервером — тоже исход, а не исключение из генерации."""
    factory = make_mcp_factory(tools=FAKE_TOOL_CATALOG, call_fail="сервер оборвался")
    agent = _agent(session_factory, monkeypatch, factory)

    record = agent.generate(QUESTION)
    assert record["status"] == "ok"
    assert record["mcp"]["reason_code"] == "transport"
    assert "сервер оборвался" in record["mcp"]["error"]


def test_refusal_by_invariants_skips_the_tool(session_factory, monkeypatch, factory):
    """Отказ по инвариантам стоит до шага MCP: наружу запрос не уходит.

    Проверка запроса бесплатна и локальна, а вызов инструмента — HTTP-запрос наружу,
    поэтому правило hard-инварианта останавливает ход ДО обращения к серверу.
    """
    from backend.domain.demo_invariants import DEMO_INVARIANTS

    agent = _agent(session_factory, monkeypatch, factory)
    seed_invariant(session_factory, **DEMO_INVARIANTS[0])  # «Только FastAPI и Streamlit»

    record = agent.generate("Перепишем бэкенд на Flask и найдём пользователя 1")
    assert record["invariants"]["verdict"] == "refusal"
    assert record["mcp"] is None
    assert factory.created[0].call_calls == []


def test_block_appended_to_existing_system_message(session_factory, monkeypatch, factory):
    """Блок дописывается в существующее системное сообщение, а не заменяет его."""
    from backend.schemas import AgentConfig

    registry = MCPRegistry(client_factory=factory)
    registry.connect("uvx mcp-server-fetch")
    cfg = AgentConfig(name="Агент с промптом", system_prompt="Ты — помощник.")
    agent = create_agent(session_factory, "mcp02", cfg=cfg, mcp_registry=registry)
    fake = FakeClient()
    monkeypatch.setattr(agent, "_make_client", lambda: fake)

    record = agent.generate(QUESTION)
    assert record["mcp"]["used_in_prompt"] is True
    content = fake.calls[-1]["messages"][0]["content"]
    assert "Ты — помощник." in content
    assert BLOCK_HEADER in content
    assert content.index("Ты — помощник.") < content.index(BLOCK_HEADER)
