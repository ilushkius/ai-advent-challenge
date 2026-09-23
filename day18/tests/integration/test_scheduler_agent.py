"""Шаг планировщика в агенте (день 18): реплика → фоновая задача.

Проверяется то, ради чего день делался: агент по реплике САМ вызывает инструмент
планировщика, тот ставит задачу в бэкенде, а модель получает блок «Данные
планировщика» — иначе она отвечает «я не умею планировать задачи», хотя задача уже
стоит. Отдельно проверяются два «нет»: реплика без ключевых слов задачи не ставит,
а без MCP-соединения шаг вообще не выполняется (отчёт ``schedule`` — ``None``).
"""
import pytest

from backend.services.mcp_registry import MCPRegistry

from mcp_fakes import FAKE_TOOL_CATALOG, make_mcp_factory
from support import FakeClient, create_agent

REMINDER_QUESTION = "Напомни мне через 30 секунд проверить почту"
SUMMARY_QUESTION = "Покажи сводку за последний час"
PLAIN_QUESTION = "Сколько будет 2+2?"

#: Плоский ответ инструмента планировщика — как его собирает MCP-сервер дня.
REMINDER_RESULT = {
    "task_id": 12,
    "reminder_id": 3,
    "text": "проверить почту",
    "remind_at": "2026-09-23T10:00:30+00:00",
    "status": "scheduled",
    "next_run_at": "2026-09-23T10:00:30+00:00",
    "message": "Напоминание запланировано на 10:00:30 UTC",
}

BLOCK_HEADER = "## Данные планировщика"


def _agent(session_factory, monkeypatch, registry=None):
    """Агент с фейковым реестром MCP и подменённым клиентом DeepSeek."""
    agent = create_agent(session_factory, "sched01", mcp_registry=registry)
    fake_client = FakeClient()
    monkeypatch.setattr(agent, "_make_client", lambda: fake_client)
    agent.fake_client = fake_client
    agent.refresh_context_state()
    return agent


def _connected_registry(**client_kwargs) -> MCPRegistry:
    """Реестр с подключённым фейковым сервером дня (каталог из шести инструментов)."""
    registry = MCPRegistry(client_factory=make_mcp_factory(
        tools=FAKE_TOOL_CATALOG, **client_kwargs))
    registry.connect("uv run python mcp_server/server.py")
    return registry


def test_reminder_utterance_registers_a_task(session_factory, monkeypatch):
    """Реплика про напоминание: инструмент вызван с аргументами, задача видна в отчёте."""
    registry = _connected_registry(call_result=REMINDER_RESULT)
    agent = _agent(session_factory, monkeypatch, registry)
    record = agent.generate(REMINDER_QUESTION)

    assert record["status"] == "ok"
    assert record["mcp"]["tool"] == "schedule_reminder"
    assert record["mcp"]["arguments"] == {"text": "проверить почту", "delay_seconds": 30}
    schedule = record["schedule"]
    assert schedule is not None and schedule["registered"] is True
    assert schedule["tool"] == "schedule_reminder"
    assert schedule["task"]["id"] == 12
    assert "запланировано" in schedule["message"]
    assert BLOCK_HEADER in record["system_prompt"]


def test_summary_utterance_registers_a_summary(session_factory, monkeypatch):
    """Реплика про сводку уходит инструменту сводки с периодом из вопроса."""
    registry = _connected_registry(call_result={
        "task_id": 13, "summary_id": 4, "name": "данные", "total_records": 2,
        "summary_text": "Сводка «данные» за период 09:00:00 — 10:00:00 (3600 с).",
        "message": "Сводка сформирована",
    })
    agent = _agent(session_factory, monkeypatch, registry)
    record = agent.generate(SUMMARY_QUESTION)

    assert record["mcp"]["tool"] == "generate_summary"
    assert record["mcp"]["arguments"]["interval_seconds"] == 3600
    assert record["schedule"]["registered"] is True
    assert record["schedule"]["summary"].startswith("Сводка «данные»")


def test_plain_utterance_registers_nothing(session_factory, monkeypatch):
    """Реплика без ключевых слов: задача не ставится, отчёт ``schedule`` пуст."""
    registry = _connected_registry(call_result=REMINDER_RESULT)
    agent = _agent(session_factory, monkeypatch, registry)
    record = agent.generate(PLAIN_QUESTION)

    assert record["mcp"]["called"] is False
    assert record["schedule"] is None
    assert BLOCK_HEADER not in record["system_prompt"]


def test_without_connection_step_is_skipped(session_factory, monkeypatch):
    """Без соединения каталога нет, вызов не распознаётся: задачи не появляется."""
    agent = _agent(session_factory, monkeypatch, registry=None)
    record = agent.generate(REMINDER_QUESTION)

    assert record["status"] == "ok"
    assert record["schedule"] is None
    assert record["mcp"]["connected"] is False
    assert record["mcp"]["detected"] is False and record["mcp"]["called"] is False
    assert BLOCK_HEADER not in record["system_prompt"]


def test_tool_error_does_not_report_a_task(session_factory, monkeypatch):
    """Ошибка инструмента — не зарегистрированная задача: отчёт ``schedule`` пуст."""
    registry = _connected_registry(call_error="бэкенд дня недоступен")
    agent = _agent(session_factory, monkeypatch, registry)
    record = agent.generate(REMINDER_QUESTION)

    assert record["status"] == "ok"
    assert record["schedule"] is None
    assert "бэкенд дня недоступен" in record["mcp"]["error"]
    assert BLOCK_HEADER not in record["system_prompt"]


def test_scheduler_block_goes_into_the_same_request(session_factory, monkeypatch):
    """Блок промпта уходит модели в этом же запросе (а не висит только в отчёте)."""
    registry = _connected_registry(call_result=REMINDER_RESULT)
    agent = _agent(session_factory, monkeypatch, registry)
    agent.generate(REMINDER_QUESTION)

    sent = agent.fake_client.generate_calls[-1]["messages"]
    system = next(item["content"] for item in sent if item["role"] == "system")
    assert BLOCK_HEADER in system
    assert "Задача №12" in system


@pytest.mark.parametrize("question,tool", [
    (REMINDER_QUESTION, "schedule_reminder"),
    (SUMMARY_QUESTION, "generate_summary"),
])
def test_added_tokens_include_scheduler_block(session_factory, monkeypatch, question, tool):
    """Токены блока планировщика входят в контроль лимита (``added_tokens`` > 0)."""
    registry = _connected_registry(call_result=REMINDER_RESULT)
    agent = _agent(session_factory, monkeypatch, registry)
    record = agent.generate(question)
    assert record["mcp"]["tool"] == tool
    assert record["mcp"]["used_in_prompt"] is True
    assert record["mcp"]["added_tokens"] > 0
