"""Фикстуры pytest дня 20: временная БД, агент с подменённым клиентом DeepSeek,
планировщик без таймеров, пайплайн на фейковом MCP-реестре и ФЛОТ серверов дня 20.

Общие фейки и утилиты — в `tests/support.py` (импортируются как `from support
import ...`, для чего `tests` добавлена в pythonpath в pytest.ini). Фейки
планировщика — в `tests/scheduler_fakes.py`, фейки пайплайна — в
`tests/pipeline_fakes.py`, фейки флота серверов — в `tests/orchestration_fakes.py`.
"""
from datetime import datetime, timezone

import pytest

from backend.core import config
from backend.agents.agent import Agent
from backend.storage.database import AgentRecord, init_db, make_engine, make_session_factory
from backend.services.task_state import TaskStateMachine
from backend.storage.scheduler_data_store import SchedulerDataStore
from backend.storage.scheduler_store import SchedulerStore
from backend.services.mcp_tool_runner import MCPToolRunner
from backend.services.pipeline import Pipeline
from backend.services.pipeline_service import PipelineService
from backend.services.schedule_service import ScheduleService
from backend.services.orchestration_service import OrchestrationService
from backend.services.orchestration_planner import OrchestrationPlanner
from backend.services.orchestrator import Orchestrator
from backend.services.scheduler import TaskScheduler
from backend.storage.pipeline_store import PipelineStore
from backend.storage.orchestration_store import OrchestrationStore
from backend.services.document_loader import DocumentLoader
from backend.services.index_service import IndexService
from backend.services.indexing_service import IndexingService
from backend.storage.chunk_store import ChunkStore
from backend.storage.index_run_store import IndexRunStore

from indexing_fakes import FakeEmbedder, make_documents
from orchestration_fakes import make_fleet_registry, make_fleet_factory, write_servers_file
from pipeline_fakes import make_pipeline_registry
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


# ---------- флот MCP-серверов и оркестрация (день 20) ----------
@pytest.fixture(autouse=True)
def no_real_fleet(tmp_path, monkeypatch):
    """Не даёт тестам поднимать настоящий флот MCP-серверов.

    ``lifespan`` приложения на старте зовёт ``connect_all()``: тот читает
    ``mcp_servers.json`` и запускает по процессу на сервер. В тестах этого быть не
    должно (медленно, зависит от окружения и от рабочего файла дня), поэтому путь
    к файлу конфигурации подменяется ПУСТЫМ временным файлом — серверов нет,
    процессов нет. Так же защищены реестры, которые тесты собирают сами в
    фикстурах: они читают путь из ``config`` в момент создания.

    Тесты, которым нужен флот (``fleet_registry`` и e2e оркестрации), передают
    серверам реестра свой файл конфигурации явно — тогда подмена пути не важна.
    """
    import backend.api.main as main

    from backend.core import config

    # Файл-заглушка лежит в подкаталоге: `tmp_path` тесты используют и как рабочий
    # каталог (например, каталог вывода `save_to_file`), и посторонний файл в нём
    # попадал бы в проверки списка файлов.
    guard_dir = tmp_path / "fleet-guard"
    guard_dir.mkdir(exist_ok=True)
    empty = write_servers_file(guard_dir / "mcp_servers.json", names=())
    monkeypatch.setattr(config, "MCP_SERVERS_FILE", empty)
    registry = make_fleet_registry(guard_dir, servers_file=empty)
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)
    yield registry


@pytest.fixture
def orchestration_store(session_factory):
    """Хранилище запусков оркестрации на временной БД."""
    return OrchestrationStore(session_factory=session_factory)


@pytest.fixture
def fleet_registry(tmp_path):
    """Реестр на фейковом флоте из трёх серверов (настоящие процессы не поднимаются)."""
    registry = make_fleet_registry(tmp_path)
    registry.connect_all()
    try:
        yield registry
    finally:
        registry.close()


@pytest.fixture
def orchestrator(fleet_registry, orchestration_store):
    """Оркестратор на фейковом флоте и временном журнале (без модели: план — эвристика)."""
    return Orchestrator(registry=fleet_registry, store=orchestration_store)


@pytest.fixture
def orchestration_service(orchestrator, orchestration_store):
    """Служба оркестрации поверх того же оркестратора и журнала."""
    return OrchestrationService(orchestrator=orchestrator, store=orchestration_store)


# ---------- индексация документов (день 21) ----------
@pytest.fixture(autouse=True)
def offline_planner(monkeypatch):
    """Планировщик оркестрации в тестах не ходит в модель.

    ``OrchestrationPlanner`` по умолчанию читает ключ DeepSeek из ``.env`` дня и
    зовёт API: тогда результат теста зависит от сети, квоты и таймаутов, а план
    приходит то эвристикой, то моделью — тесты «без плана сработала эвристика»
    падали именно так (проверено: полный прогон дня 21 дал шесть таких падений).
    Тесты, которым нужен план модели, подставляют планировщик явно.

    Побочный эффект приятный: набор тестов перестаёт ждать таймаутов сети
    (в днях 20 и раньше один только этот тест занимал минуту).
    """
    monkeypatch.setattr(OrchestrationPlanner, "plan",
                        lambda self, query, tools: None)


@pytest.fixture(autouse=True)
def isolated_indexing(tmp_path, monkeypatch):
    """Уводит индексацию от рабочих файлов дня и запрещает загрузку модели.

    Две ловушки, которые эта фикстура закрывает для ВСЕХ тестов дня:

    * ``lifespan`` приложения зовёт ``load_all``/``save_all`` у службы индексов
      процесса — то есть читал и писал бы рабочие ``day21/index/*.index`` и держал
      бы их в общем singleton между тестами. Поэтому ``main.get_index_service``
      подменяется службой на ``tmp_path``: файлов там нет, писать нечего;
    * модель эмбеддингов весит сотни мегабайт и требует сети. ``warmup`` в
      демон-потоке старта попытался бы её загрузить, поэтому ``EmbeddingService._load``
      заменён функцией-ошибкой: случайная загрузка настоящей модели = падение теста
      (у ``warmup`` исключение ловится, поэтому старт приложения не ломается).
    """
    import backend.api.main as main

    from backend.services import embedding_service as embedding_module
    from backend.services import index_service as index_module
    from backend.services import indexing_service as indexing_module
    from backend.services.embedding_service import EmbeddingService
    from backend.services.index_service import IndexService

    monkeypatch.setattr(indexing_module, "_service", None)
    monkeypatch.setattr(index_module, "_service", None)
    monkeypatch.setattr(embedding_module, "_service", None)

    def no_real_model(_self):
        """Настоящая модель в тестах не загружается (сеть и сотни мегабайт)."""
        raise AssertionError("тест попытался загрузить настоящую модель эмбеддингов")

    monkeypatch.setattr(EmbeddingService, "_load", no_real_model)

    isolated = IndexService(embedder=EmbeddingService(),
                            index_dir=tmp_path / "index-isolated")
    monkeypatch.setattr(main, "get_index_service", lambda: isolated)
    yield isolated


@pytest.fixture
def documents_dir(tmp_path):
    """Папка с тремя тестовыми документами: markdown, plain text и Python."""
    base = tmp_path / "documents"
    make_documents(base)
    return base


@pytest.fixture
def documents(documents_dir):
    """Три тестовых документа как ``Document`` (метаданные — эвристиками домена)."""
    return DocumentLoader(documents_dir=documents_dir,
                          sources=()).ensure_documents()


@pytest.fixture
def document_loader(documents_dir):
    """Загрузчик на тестовой папке: сборка из репозитория тесту не нужна."""
    return DocumentLoader(documents_dir=documents_dir, sources=())


@pytest.fixture
def fake_embedder():
    """Эмбеддер на хешах слов: детерминированный, без модели и без сети."""
    return FakeEmbedder()


@pytest.fixture
def chunk_store(session_factory):
    """Хранилище чанков на временной БД."""
    return ChunkStore(session_factory=session_factory)


@pytest.fixture
def index_run_store(session_factory):
    """Хранилище запусков индексации на временной БД."""
    return IndexRunStore(session_factory=session_factory)


@pytest.fixture
def index_service(tmp_path, fake_embedder, chunk_store):
    """Служба индексов на фейковом эмбеддере, временной БД и временном каталоге."""
    return IndexService(embedder=fake_embedder, store=chunk_store,
                        index_dir=tmp_path / "index")


@pytest.fixture
def indexing_service(index_service, document_loader, index_run_store):
    """Служба индексации: те же три документа, фейковый эмбеддер, временная БД."""
    return IndexingService(index_service=index_service, loader=document_loader,
                           run_store=index_run_store)
