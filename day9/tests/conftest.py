"""Фикстуры pytest дня 9: временная БД и агент с подменённым клиентом DeepSeek.

Общие фейки и утилиты — в `tests/support.py` (импортируются как `from support
import ...`, для чего `tests` добавлена в pythonpath в pytest.ini).
"""
import pytest

from backend.agent import Agent
from backend.database import init_db, make_engine, make_session_factory

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
