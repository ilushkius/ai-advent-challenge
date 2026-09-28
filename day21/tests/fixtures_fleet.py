"""Фикстуры флота MCP-серверов и оркестрации (унаследованы от дня 20).

Вынесены из `tests/conftest.py`: тот упёрся в лимит 400 строк (правила дня). Файл
импортируется обратно в conftest, поэтому тесты видят фикстуры под теми же
именами, что и раньше. Фейки флота — в `tests/orchestration_fakes.py`.
"""
import pytest

from backend.services.orchestration_planner import OrchestrationPlanner
from backend.services.orchestration_service import OrchestrationService
from backend.services.orchestrator import Orchestrator
from backend.storage.orchestration_store import OrchestrationStore

from orchestration_fakes import make_fleet_registry, write_servers_file


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
