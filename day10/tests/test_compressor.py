"""Тесты компрессора: план сжатия, вызов суммаризации, запись конспекта.

Клиент DeepSeek подменён фейком (см. conftest), поэтому проверяется ровно та
логика, которая принадлежит компрессору: когда сжимать, что попадает в конспект
и как выглядит вызов суммаризации (модель, промпт, обновление прошлого
конспекта), а также деградация при сбое.
"""
import pytest

from backend.agent import Agent
from backend.compressor import CompressionError
from backend.config import SUMMARY_MODEL
from backend.models import AgentConfig

from support import FakeClient, create_agent, seed_dialog


def test_plan_waits_for_threshold(session_factory):
    """Пока порог не набран, сжатие не запускается (conspect не пишется)."""
    agent = create_agent(session_factory, "plan01", name="Порог", keep_last_messages=2,
                              summarize_every=4)
    seed_dialog(agent, turns=2)  # 4 реплики, backlog = 4 - 2 = 2 < 4

    plan = agent.compressor.plan()
    assert plan.should_compress is False
    assert plan.uncovered_count == 4
    assert plan.keep_count == 4


def test_plan_fires_at_threshold(session_factory):
    """Порог набран: в конспект уходит все, кроме последних keep_last реплик."""
    agent = create_agent(session_factory, "plan02", name="Порог", keep_last_messages=2,
                              summarize_every=4)
    seed_dialog(agent, turns=3)  # 6 реплик, backlog = 4 >= 4

    plan = agent.compressor.plan()
    assert plan.should_compress is True
    assert plan.summarize_count == 4
    assert plan.keep_count == 2


def test_force_ignores_threshold_but_keeps_tail(session_factory):
    """force=True сжимает даже ниже порога, но последние keep_last не трогает."""
    agent = create_agent(session_factory, "plan03", name="Форс", keep_last_messages=2,
                              summarize_every=10)
    seed_dialog(agent, turns=3)  # 6 реплик, порог 10 не набран

    plan = agent.compressor.plan(force=True)
    assert plan.should_compress is True
    assert plan.summarize_count == 4
    assert plan.keep_count == 2


def test_summarize_writes_conspect_with_watermark(make_agent):
    """Успешная суммаризация пишет конспект и двигает watermark."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)

    outcome = agent.compressor.summarize()

    assert outcome.created is True
    assert outcome.covered_messages <= 6
    assert agent.compressor.latest_row().content == outcome.content
    assert agent.compressor.watermark() == outcome.covered_to_message_id
    # Последние keep_last реплик остались непокрытыми.
    assert len(agent.compressor.uncovered_rows()) >= 2


def test_summarize_uses_summary_model_and_previous_conspect(make_agent):
    """Суммаризация идёт на SUMMARY_MODEL и получает прошлый конспект в промпте."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)
    agent.compressor.summarize()
    first = agent.fake_client.summary_calls[0]
    assert first["model"] == SUMMARY_MODEL

    seed_dialog(agent, turns=2)
    agent.compressor.summarize()
    second = agent.fake_client.summary_calls[1]
    prompt_text = "\n".join(item["content"] for item in second["messages"])
    assert "Текущий конспект диалога" in prompt_text
    assert "Ответ ассистента" not in prompt_text  # в промпт идёт конспект, не реплики


def test_summarize_raises_when_nothing_to_compress(make_agent):
    """Нечего сжимать (порог не набран) — CompressionError, а не пустой конспект."""
    agent = make_agent(keep_last_messages=4, summarize_every=10)
    seed_dialog(agent, turns=2)

    with pytest.raises(CompressionError):
        agent.compressor.summarize()


def test_summarize_raises_on_disabled(make_agent):
    """Выключенное сжатие — явная ошибка компрессора."""
    agent = make_agent(summary_enabled=False)
    seed_dialog(agent, turns=5)

    with pytest.raises(CompressionError):
        agent.compressor.summarize()


def test_summarize_propagates_api_failure(make_agent):
    """Сбой API сумммаризации превращается в CompressionError (ход не ломается)."""
    agent = make_agent(fake=FakeClient(summary_error=RuntimeError("429 rate limit")),
                       keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)

    with pytest.raises(CompressionError) as excinfo:
        agent.compressor.summarize()
    assert "429" in str(excinfo.value)


def test_empty_summary_is_rejected(make_agent):
    """Пустой ответ модели не сохраняется как конспект."""
    agent = make_agent(fake=FakeClient(summary_reply="   "),
                       keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)

    with pytest.raises(CompressionError):
        agent.compressor.summarize()
    assert agent.compressor.history() == []


def test_economics_counts_summary_cost(make_agent):
    """Экономика: стоимость конспектов и токены-источники считаются по записям."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)
    agent.compressor.summarize()

    economics = agent.compressor.economics()
    summary_rows = agent.compressor.history()
    call_tokens = sum(row["prompt_tokens"] + row["completion_tokens"]
                      for row in summary_rows)

    assert economics["summary_count"] == 1
    assert economics["total_source_tokens"] > 0
    assert economics["summary_cost"] > 0
    # Ходов ещё не было: «экономия» отрицательная ровно на стоимость конспектов.
    assert economics["net_saved_tokens"] == -call_tokens
