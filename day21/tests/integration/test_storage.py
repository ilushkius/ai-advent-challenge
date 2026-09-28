"""Тесты хранилища дня 11: таблица summaries и метрики сжатия.

Проверяем наблюдаемое поведение БД, а не реализацию: конспект сохраняется и
читается последним, watermark переживает «рестарт» (новый Agent на той же БД),
каскады удаляют связанные строки, а агрегаты token_usage считают экономию.
"""
from datetime import datetime, timezone

import pytest

from backend.core import config
from backend.storage import database
from backend.agents.agent import Agent
from backend.storage.database import AgentRecord, Summary, TokenUsage
from backend.schemas import AgentConfig

from support import FakeClient, create_agent, seed_dialog


def test_summary_saved_and_read_back(session_factory):
    """Сохранённый конспект возвращается как последний и задаёт watermark."""
    cfg = AgentConfig(name="Хранилище", keep_last_messages=2, summarize_every=2)
    agent = create_agent(session_factory, "store01", cfg=cfg)
    seed_dialog(agent, turns=3)

    with session_factory() as session:
        session.add(Summary(
            agent_id="store01", content="Конспект первой части",
            covered_from_message_id=1, covered_to_message_id=4,
            covered_messages=4, source_tokens=120, summary_tokens=20,
            prompt_tokens=130, completion_tokens=20, cost=0.00005,
            created_at=datetime.now(timezone.utc),
        ))
        session.add(Summary(
            agent_id="store01", content="Конспект с дополнением",
            covered_from_message_id=1, covered_to_message_id=6,
            covered_messages=6, source_tokens=180, summary_tokens=28,
            prompt_tokens=190, completion_tokens=28, cost=0.00008,
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()

    assert agent.compressor.watermark() == 6
    latest = agent.compressor.latest_row()
    assert latest.content == "Конспект с дополнением"
    assert len(agent.compressor.history()) == 2

    # Непокрытыми остаются реплики с id > watermark — их и отправляем «как есть».
    uncovered = agent.compressor.uncovered_rows()
    assert [row.content for row in uncovered] == [] or all(
        row.id > 6 for row in uncovered
    )


def test_watermark_survives_agent_recreation(session_factory):
    """Конспект и границы читаются новым объектом Agent (эмуляция рестарта)."""
    seed = create_agent(session_factory, "restart1", name="Рестарт")
    seed_dialog(seed, turns=2)
    with session_factory() as session:
        session.add(Summary(
            agent_id="restart1", content="Старый конспект",
            covered_from_message_id=1, covered_to_message_id=4,
            covered_messages=4, created_at=datetime.now(timezone.utc),
        ))
        session.commit()

    restored = create_agent(session_factory, "restart1", name="Рестарт",
                            ensure_record=False)
    assert restored.compressor.watermark() == 4
    assert restored.compressor.latest_row().content == "Старый конспект"


def test_history_marks_summarized_messages(session_factory):
    """API-история помечает покрытые конспектом реплики флагом summarized."""
    agent = create_agent(session_factory, "flags01", name="Флаги")
    seed_dialog(agent, turns=3)
    with session_factory() as session:
        session.add(Summary(
            agent_id="flags01", content="Конспект",
            covered_from_message_id=1, covered_to_message_id=4,
            covered_messages=4, created_at=datetime.now(timezone.utc),
        ))
        session.commit()

    rows = agent.history_rows()
    assert [row["summarized"] for row in rows] == [True, True, True, True, False, False]


def test_delete_agent_removes_summaries(session_factory):
    """Удаление агента сносит и конспекты (каскад/явная чистка)."""
    cfg = AgentConfig(name="Каскад")
    with session_factory() as session:
        session.add(AgentRecord(
            agent_id="cascade1", name=cfg.name, model=cfg.model,
            temperature=cfg.temperature, system_prompt="", max_tokens=cfg.max_tokens,
            current_session_id="cascade1", current_task_id=config.DEFAULT_TASK_ID,
            created_at=datetime.now(timezone.utc),
        ))
        session.add(Summary(
            agent_id="cascade1", content="Конспект",
            covered_from_message_id=1, covered_to_message_id=2,
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()

    with session_factory() as session:
        session.query(Summary).filter(Summary.agent_id == "cascade1").delete()
        session.query(AgentRecord).filter(AgentRecord.agent_id == "cascade1").delete()
        session.commit()
        assert session.query(Summary).count() == 0


def test_clear_history_removes_summaries_and_usage(session_factory):
    """«Очистить историю» сбрасывает и конспекты, и счётчик сэкономленных токенов."""
    agent = create_agent(session_factory, "clear01", name="Сброс")
    seed_dialog(agent, turns=2)
    with session_factory() as session:
        session.add(Summary(
            agent_id="clear01", content="Конспект",
            covered_from_message_id=1, covered_to_message_id=2,
            created_at=datetime.now(timezone.utc),
        ))
        session.add(TokenUsage(
            agent_id="clear01", timestamp=datetime.now(timezone.utc),
            saved_tokens=500, summary_tokens=30, summary_used=True,
        ))
        session.commit()

    deleted = agent.clear_history()

    assert deleted == 4
    assert agent.compressor.history() == []
    assert agent.compressor.watermark() == 0
    assert agent.saved_tokens_from_usage() == 0
    assert agent.message_count == 0


def test_usage_columns_persist(session_factory):
    """Новые колонки token_usage сохраняются и читаются как есть."""
    agent = create_agent(session_factory, "usage01", name="Метрики")
    seed_dialog(agent, turns=1)
    agent._save_turn("вопрос", "ответ", metrics={
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        "history_tokens": 8, "response_tokens": 5, "cost": 0.0001,
        "mode": "compressed", "full_context_tokens": 900,
        "sent_context_tokens": 300, "saved_tokens": 600,
        "summary_tokens": 40, "summarized_messages": 6, "summary_used": True,
    })

    with session_factory() as session:
        row = session.query(TokenUsage).filter(
            TokenUsage.agent_id == "usage01"
        ).one()
    assert row.mode == "compressed"
    assert (row.full_context_tokens, row.sent_context_tokens) == (900, 300)
    assert row.saved_tokens == 600
    assert row.summary_used is True
    assert agent.saved_tokens_from_usage() == 600
