"""Стоимость хода агента: PromptBuilder, сжатие блоков и журнал расходов (день 21).

Проверяется, что механизмы оптимизации РЕАЛЬНО работают в ходе агента, а не лежат
рядом:

* системное сообщение собирается по зонам — стабильный префикс, динамическая часть,
  хвост с пределом длины ответа (и профиль остаётся первым в стабильной части);
* повторная сборка промпта попадает в кэш стабильного префикса;
* динамическая часть и блоки результатов инструментов сжимаются, и `added_tokens`
  считаются уже по сжатому тексту;
* вызов идёт через обёртку `LLMClient`: модель и предел ответа выбираются по типу
  задачи, а строка с `cache_hit`/`cache_miss` попадает в журнал `llm_usage`;
* в отчёте хода есть поле `llm` — по нему видно, сколько стоил ход.

Клиент DeepSeek подменяется `FakeClient` из `tests/support.py` (та же точка подмены,
что и в остальных тестах дня), БД — временная.
"""
import json

import pytest

from backend.core import config
from backend.core.prompt_builder import PromptBuilder
from backend.domain.profiles import PROFILE_HEADER
from backend.storage.llm_usage_store import LLMUsageStore

from support import FakeClient, create_agent, seed_dialog, seed_profile

#: Блок с JSON и комментарием: то, что сжатие обязано уменьшить.
COMPRESSIBLE_BLOCK = (
    "## Данные MCP-инструмента\n"
    "Результат:\n"
    "```json\n"
    + json.dumps({"count": 3, "items": [{"id": 1, "title": "demo"},
                                        {"id": 2, "title": "run"},
                                        {"id": 3, "title": "report"}]},
                 ensure_ascii=False, indent=4)
    + "\n```\n"
    + "\n".join("- одинаковый пункт" for _ in range(5))
    + "\n<!-- документ усечён -->"
)


@pytest.fixture
def agent(session_factory, monkeypatch):
    """Агент со своим строителем промптов и подменённым клиентом DeepSeek."""
    fake = FakeClient(reply="Ответ")
    created = create_agent(session_factory, "cost01", user_id="ivan",
                           system_prompt="Ты — ассистент проекта.",
                           prompt_builder=PromptBuilder())
    monkeypatch.setattr(created, "_make_client", lambda: fake)
    created.fake_client = fake
    return created


def test_system_prompt_is_built_by_zones(agent, session_factory):
    """Стабильный префикс идёт первым, динамика — после, хвост с пределом — последним."""
    seed_profile(session_factory, "ivan", name="Инженер")
    agent.profile = agent.profile_store.load("ivan")
    agent.add_working("цель", "снизить расходы")
    text = agent._system_message(
        memory=agent.build_memory_context("какая цель?"))[0]["content"]
    assert text.startswith(PROFILE_HEADER)
    assert text.index("Ты — ассистент проекта.") < text.index("Рабочая память")
    assert text.rstrip().endswith("токенов.")
    assert str(config.LLM_MAX_RESPONSE_TOKENS) in text


def test_stable_prefix_is_cached_between_turns(agent):
    """Вторая сборка промпта переиспользует стабильный префикс (кэш приложения)."""
    builder = agent.prompt_builder
    builder.reset()
    agent._system_message(memory=None)
    first = builder.stats()
    agent._system_message(memory=None)
    second = builder.stats()
    assert first["cache_misses"] == 1 and first["cache_hits"] == 0
    assert second["cache_hits"] == 1
    assert second["cache_hit_percent"] > 0


def test_dynamic_change_does_not_invalidate_prefix(agent):
    """Изменение динамики (память/задача) не мешает попаданию в кэш префикса."""
    builder = agent.prompt_builder
    builder.reset()
    agent._system_message()
    agent.add_working("новая цель", "уложиться в лимит")
    agent._system_message(memory=agent.build_memory_context("цель?"))
    stats = builder.stats()
    assert stats["requests"] == 2 and stats["cache_hits"] == 1


def test_appended_blocks_are_compressed(agent):
    """Блок результата инструмента сжимается, и токены считаются по сжатому тексту."""
    payload = agent._system_message()
    before = agent.count_tokens(COMPRESSIBLE_BLOCK)
    returned = agent._append_system_block(
        payload, COMPRESSIBLE_BLOCK)
    after = agent.count_tokens(returned)
    assert after < before, "сжатие должно уменьшить блок результата инструмента"
    assert "документ усечён" not in returned
    assert returned in payload[0]["content"]


def test_generate_reports_llm_costs(agent):
    """Отчёт хода несёт модель, токены, кэш и стоимость."""
    record = agent.generate("Сколько стоит запрос?")
    assert record["status"] == "ok"
    llm = record["llm"]
    assert llm["model"] == config.MODEL_CHAT
    assert llm["request_type"] == config.LLM_TASK_CHAT
    assert llm["max_tokens"] == config.LLM_MAX_RESPONSE_TOKENS
    assert llm["prompt_tokens"] > 0 and llm["completion_tokens"] > 0
    assert llm["cache_miss_tokens"] >= llm["prompt_tokens"] - llm["cache_hit_tokens"]
    assert llm["cost_estimate"] > 0


def test_generate_writes_usage_journal(agent, session_factory):
    """Каждый ход попадает в журнал `llm_usage` с агентом и типом задачи."""
    agent.generate("Раз, два, три")
    agent.generate("И ещё раз")
    rows = LLMUsageStore(session_factory=session_factory).recent(agent_id="cost01")
    # Журнал ведётся по ВСЕМ вызовам агента, поэтому ход даёт больше одной строки:
    # ответ — тип `chat`, проверка инвариантов — тип `classify`. Считаем по типу.
    chat_rows = [row for row in rows if row["request_type"] == config.LLM_TASK_CHAT]
    assert len(chat_rows) == 2
    for row in chat_rows:
        assert row["agent_id"] == "cost01"
        assert row["request_type"] == config.LLM_TASK_CHAT
        assert row["model"] == config.MODEL_CHAT
        assert row["prompt_tokens"] > 0
        assert row["cost_estimate"] > 0
        assert row["timestamp"] and row["cache_miss_tokens"] >= 0


def test_summary_call_is_logged_as_its_own_type(agent, session_factory):
    """Сводка истории — отдельный тип задачи: её видно в журнале отдельно от чата."""
    # Сводке нужен материал: наполняем диалог и просим сжатие явно.
    seed_dialog(agent, turns=6)
    agent.compress_now(force=True)
    rows = LLMUsageStore(session_factory=session_factory).recent(agent_id="cost01")
    kinds = {row["request_type"] for row in rows}
    assert config.LLM_TASK_SUMMARY in kinds
    summary_row = next(row for row in rows
                       if row["request_type"] == config.LLM_TASK_SUMMARY)
    assert summary_row["model"] == config.MODEL_CHAT


def test_generation_is_not_broken_when_journal_is_down(agent, monkeypatch):
    """Сбой журнала не ломает генерацию: расходы — учёт, а не функциональность."""
    monkeypatch.setattr(LLMUsageStore, "add",
                        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("нет БД")))
    record = agent.generate("Проверка устойчивости")
    assert record["status"] == "ok"
    assert record["response"] == "Ответ"


def test_llm_client_is_reused_between_turns(agent):
    """Обёртка вызова живёт вместе с агентом: её модель и журнал не пересоздаются."""
    first = agent.llm_client
    agent.generate("Первый")
    assert agent.llm_client is first
