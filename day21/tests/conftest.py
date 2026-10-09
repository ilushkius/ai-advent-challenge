"""Фикстуры pytest дня 21: временная БД (копия общей схемы), агент с подменённым
клиентом DeepSeek, планировщик без таймеров и пайплайн на фейковом MCP-реестре.

Общие фейки и утилиты — в `tests/support.py` (импортируются как `from support
import ...`, для чего `tests` добавлена в pythonpath в pytest.ini). Фейки
планировщика — в `tests/scheduler_fakes.py`, фейки пайплайна — в
`tests/pipeline_fakes.py`.

Фикстуры флота MCP-серверов и оркестрации (день 20) живут в
`tests/fixtures_fleet.py`, индексации документов (день 21) — в
`tests/fixtures_indexing.py`: conftest упёрся бы в лимит 400 строк. Импортированные
сюда фикстуры pytest видит как объявленные здесь.
"""
import shutil
import socket

from datetime import datetime, timezone

import pytest

from backend.core import config
from backend.storage.database import AgentRecord, init_db, make_engine, make_session_factory
from backend.services.task_state import TaskStateMachine
from backend.storage.scheduler_data_store import SchedulerDataStore
from backend.storage.scheduler_store import SchedulerStore
from backend.services.mcp_tool_runner import MCPToolRunner
from backend.services.pipeline import Pipeline
from backend.services.pipeline_service import PipelineService
from backend.services.schedule_service import ScheduleService
from backend.services.scheduler import TaskScheduler
from backend.storage.pipeline_store import PipelineStore

from pipeline_fakes import make_pipeline_registry
from scheduler_fakes import FakeFetcher
from support import FakeClient, create_agent
from stub_api import stub_api
from backend_stub import backend_api_stub

from fixtures_fleet import (  # noqa: F401  (фикстуры: pytest читает их как свои)
    fleet_registry,
    no_real_fleet,
    offline_planner,
    orchestration_service,
    orchestration_store,
    orchestrator,
)
from fixtures_indexing import (  # noqa: F401  (фикстуры: pytest читает их как свои)
    chunk_store,
    document_loader,
    documents,
    documents_dir,
    fake_embedder,
    index_run_store,
    index_service,
    indexing_service,
    isolated_indexing,
)
from fixtures_mini_chat import (  # noqa: F401  (фикстуры: pytest читает их как свои)
    mini_chat_broken_service,
    mini_chat_service,
    mini_chat_stub,
    mini_chat_weak_service,
)
from fixtures_rag import (  # noqa: F401  (фикстуры: pytest читает их как свои)
    empty_index_service,
    rag_client,
    rag_corpus_dir,
    rag_documents,
    rag_index_service,
    rag_loader,
    rag_reranker,
    rag_service,
    rag_stub,
    rag_usage_store,
)


def pytest_addoption(parser):
    """Добавляет `--run-slow`: полный прогон, включая тяжёлые тесты.

    По умолчанию `pytest.ini` оставляет быстрый набор (`-m "not slow"`), поэтому
    полный прогон требовал бы помнить выражение маркеров; флаг делает это явным.
    """
    parser.addoption(
        "--run-slow", action="store_true", default=False,
        help="запустить и медленные тесты (маркер slow: подпроцессы MCP, e2e)",
    )


def pytest_collection_modifyitems(config, items):
    """`--run-slow` снимает дефолтное `-m "not slow"` из `addopts` (pytest.ini).

    Явное выражение маркеров, переданное в командной строке, остаётся в силе:
    флаг меняет только дефолт из `addopts`, а не выбор пользователя.
    """
    if not config.getoption("--run-slow", default=False):
        return
    args = config.invocation_params.args
    explicit = any(a == "-m" or a.startswith("-m=") or a.startswith("--markexpr") for a in args)
    if not explicit and config.option.markexpr == "not slow":
        config.option.markexpr = ""


@pytest.fixture(autouse=True)
def no_real_network(request, monkeypatch):
    """Тесты не выходят в сеть: чужой хост — падение с понятным текстом.

    Внешние API уже подменены (``FakeClient`` — DeepSeek, autouse-фикстуры
    ``offline_planner`` и ``isolated_indexing`` — планировщик и модель
    эмбеддингов, стенды ``stub_api``/``backend_stub`` слушают 127.0.0.1), но
    самой проверки не было: новый тест мог незаметно пойти в интернет. Запрет
    ловит ровно этот случай и не мешает локальным стендам и stdio-подпроцессам.

    Тесты с маркером ``remote`` снимают запрет явно: сквозной прогон дня 30 идёт
    по настоящему туннелю Cloudflare, адрес которого из кода не виден, а подмена
    удалённого сервиса фейком проверяла бы не то (``test_remote_llm_flow``).
    """
    if request.node.get_closest_marker("remote"):
        return

    real_connect = socket.socket.connect

    def guarded(self, address, *args, **kwargs):
        """Пускает только локальные адреса; остальные — явная ошибка теста."""
        host = address[0] if isinstance(address, tuple) else address
        local = (not host) or str(host).startswith(("127.", "localhost", "::1", "0.0.0.0"))
        if not local:
            raise AssertionError(
                f"тест попытался выйти в сеть: {host}. Подмените внешний вызов "
                "фейком (tests/support.py: FakeClient, tests/stub_api.py) — "
                "тесты дня 21 работают офлайн."
            )
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def stub_api_base():
    """Базовый URL локального стенда внешнего API (живёт ровно один тест).

    MCP-сервер дня читает jsonplaceholder, но тесты в сеть не ходят: адрес стенда
    передаётся серверу аргументом ``--api-base`` (см. ``tests/stub_api.py``).
    """
    with stub_api() as base_url:
        yield base_url


@pytest.fixture(scope="session")
def schema_template(tmp_path_factory):
    """Готовая схема БД: строится ОДИН раз за прогон.

    `init_db` (create_all по ~25 таблицам) стоит ≈0,9 с — почти секунда на каждый
    тест, которому нужна база. Здесь схема строится один раз, а тесты получают
    копию файла (≈3 мс): изоляция сохраняется, потому что у каждого теста свой
    файл, меняется только способ его создания.
    """
    path = tmp_path_factory.mktemp("schema") / "schema.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    engine.dispose()
    return path


@pytest.fixture
def session_factory(tmp_path, schema_template):
    """Фабрика сессий на временной SQLite-базе: копия схемы, файл живёт до конца теста."""
    db = tmp_path / "test.db"
    shutil.copyfile(schema_template, db)
    engine = make_engine(f"sqlite:///{db.as_posix()}")
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


# ---------- пайплайн (день 19) ----------
@pytest.fixture
def pipeline_store(session_factory):
    """Хранилище запусков пайплайна на временной БД."""
    return PipelineStore(session_factory=session_factory)


@pytest.fixture
def pipeline_registry():
    """MCP-реестр на фейковых клиентах композиции (настоящий сервер не поднимается)."""
    registry = make_pipeline_registry()
    registry.connect("uv run python mcp_server/server.py")
    try:
        yield registry
    finally:
        registry.close()


@pytest.fixture
def pipeline(pipeline_registry, pipeline_store):
    """Пайплайн на фейковом реестре и временной БД: те же шаги, но без сети."""
    return Pipeline(runner=MCPToolRunner(pipeline_registry), store=pipeline_store)


@pytest.fixture
def pipeline_service(pipeline, pipeline_store):
    """Служба пайплайнов поверх того же прогона и журнала."""
    return PipelineService(pipeline=pipeline, store=pipeline_store)


@pytest.fixture
def backend_api_base():
    """Базовый URL стенда бэкенда дня (живёт ровно один тест).

    Нужен тесту stdio-инструментов планировщика: MCP-сервер поднимается с
    ``--backend-url`` этого стенда, поэтому настоящий uvicorn не запускается.
    """
    with backend_api_stub() as base_url:
        yield base_url
