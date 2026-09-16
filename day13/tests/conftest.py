"""Фикстуры pytest дня 13: временная БД и агент с подменённым клиентом DeepSeek.

Общие фейки и утилиты — в `tests/support.py` (импортируются как `from support
import ...`, для чего `tests` добавлена в pythonpath в pytest.ini).
"""
from datetime import datetime, timezone

import pytest

from backend import config
from backend.agent import Agent
from backend.database import AgentRecord, init_db, make_engine, make_session_factory
from backend.task_state import TaskStateMachine

from support import FakeClient, create_agent


@pytest.fixture
def session_factory(tmp_path):
    """Фабрика сессий на временной SQLite-базе (файл живёт до конца теста)."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def make_agent(session_factory, monkeypatch):
    """Создаёт агента на временной БД с подменённым клиентом DeepSeek."""
    created: list = []

    def factory(fake: FakeClient | None = None, **overrides):
        agent = create_agent(session_factory, f"test{len(created):02d}", **overrides)
        client = fake or FakeClient()
        monkeypatch.setattr(agent, "_make_client", lambda: client)
        agent.fake_client = client
        created.append(agent)
        agent.refresh_context_state()
        return agent

    return factory


@pytest.fixture
def task_session_factory(session_factory):
    """Временная БД со строкой агента: task_states ссылается на agents по FK."""
    with session_factory() as session:
        session.add(AgentRecord(
            agent_id="task01", name="Задачи", model=config.MODEL_CHAT,
            temperature=0.0, system_prompt="", max_tokens=100,
            current_session_id="sess0001", current_task_id=config.DEFAULT_TASK_ID,
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()
    return session_factory


@pytest.fixture
def task_machine(task_session_factory):
    """TaskStateMachine на временной БД: состояние живёт в БД, не в памяти."""
    return TaskStateMachine(session_factory=task_session_factory)
