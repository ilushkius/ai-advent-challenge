"""Фикстуры pytest дня 18: временная БД, агент с подменённым клиентом DeepSeek и
планировщик без таймеров.

Общие фейки и утилиты — в `tests/support.py` (импортируются как `from support
import ...`, для чего `tests` добавлена в pythonpath в pytest.ini). Фейки
планировщика — в `tests/scheduler_fakes.py`.
"""
from datetime import datetime, timezone

import pytest

from backend.core import config
from backend.agents.agent import Agent
from backend.storage.database import AgentRecord, init_db, make_engine, make_session_factory
from backend.services.task_state import TaskStateMachine
from backend.storage.scheduler_data_store import SchedulerDataStore
from backend.storage.scheduler_store import SchedulerStore
from backend.services.schedule_service import ScheduleService
from backend.services.scheduler import TaskScheduler

from scheduler_fakes import FakeFetcher
from support import FakeClient, create_agent
from stub_api import stub_api
from backend_stub import backend_api_stub


@pytest.fixture
def stub_api_base():
    """Базовый URL локального стенда внешнего API (живёт ровно один тест).

    MCP-сервер дня читает jsonplaceholder, но тесты в сеть не ходят: адрес стенда
    передаётся серверу аргументом ``--api-base`` (см. ``tests/stub_api.py``).
    """
    with stub_api() as base_url:
        yield base_url


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


# ---------- планировщик (день 18) ----------
@pytest.fixture
def scheduler_store(session_factory):
    """Хранилище задач планировщика на временной БД."""
    return SchedulerStore(session_factory=session_factory)


@pytest.fixture
def scheduler_data(session_factory):
    """Хранилище данных планировщика (напоминания, записи, сводки) на временной БД."""
    return SchedulerDataStore(session_factory=session_factory)


@pytest.fixture
def fetcher():
    """Фейковый внешний источник: детерминированные ответы вместо HTTP."""
    return FakeFetcher()


@pytest.fixture
def scheduler(scheduler_store, scheduler_data, fetcher):
    """Планировщик БЕЗ таймеров: расписание считает и пишет в БД, jobs не заводит.

    APScheduler поднимается только в отдельном тесте связки
    (``tests/integration/test_scheduler_apscheduler.py``): остальным проверкам
    таймеры не нужны, а ``start()`` требует работающего цикла событий.
    """
    return TaskScheduler(store=scheduler_store, data=scheduler_data, fetch=fetcher)


@pytest.fixture
def schedule_service(scheduler, scheduler_store, scheduler_data, fetcher):
    """Сервис расписаний поверх того же планировщика и временной БД."""
    return ScheduleService(scheduler=scheduler, store=scheduler_store,
                           data=scheduler_data, fetch=fetcher)


@pytest.fixture
def backend_api_base():
    """Базовый URL стенда бэкенда дня (живёт ровно один тест).

    Нужен тесту stdio-инструментов планировщика: MCP-сервер поднимается с
    ``--backend-url`` этого стенда, поэтому настоящий uvicorn не запускается.
    """
    with backend_api_stub() as base_url:
        yield base_url
