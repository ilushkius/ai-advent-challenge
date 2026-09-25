"""Сценарий 4 дня 20: перезапуск приложения не теряет ни флот, ни историю.

Смысл проверки: журнал оркестрации лежит в SQLite, а конфигурация флота — в файле,
поэтому после остановки процесса (``registry.close()``) новый реестр и новая служба
на ТОЙ ЖЕ базе обязаны показать прошлые запуски с шагами, а ``connect_all()`` —
поднять флот заново и обновить кэш инструментов в файле конфигурации.
"""
import json

from backend.services.mcp_registry import MCPRegistry
from backend.services.orchestration_service import OrchestrationService
from backend.services.orchestrator import Orchestrator
from backend.storage.orchestration_store import OrchestrationStore

from orchestration_fakes import make_fleet_factory, make_fleet_registry, write_servers_file

#: Столько шагов у демо-сценария: по ним проверяется, что история не «худеет».
DEMO_STEPS = 5


def test_history_and_fleet_survive_a_restart(tmp_path, session_factory):
    """После «перезапуска»: история на месте, флот переподключён, кэш записан."""
    path = write_servers_file(tmp_path / "mcp_servers.json")
    factory = make_fleet_factory()
    registry = make_fleet_registry(tmp_path, servers_file=path, factory=factory)
    registry.connect_all()
    store = OrchestrationStore(session_factory)
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry, store=store), store=store)
    started = service.start_demo(background=False)
    assert started["status"] == "completed"
    ran_id = started["run_id"]
    registry.refresh_tools()
    registry.close()
    assert registry.fleet_status()["connected"] == 0

    # «Перезапуск»: новые реестр и служба на той же базе и том же файле флота.
    restarted_factory = make_fleet_factory()
    restarted = MCPRegistry(fleet_factory=restarted_factory, servers_file=path,
                            cwd=str(tmp_path))
    restarted.connect_all()
    store2 = OrchestrationStore(session_factory)
    service2 = OrchestrationService(
        orchestrator=Orchestrator(registry=restarted, store=store2), store=store2)
    try:
        history = service2.list_runs()
        assert history["count"] == 1
        assert history["runs"][0]["id"] == ran_id
        assert history["runs"][0]["status"] == "completed"
        assert history["runs"][0]["servers_used"] == [
            "search_server", "data_server", "storage_server"]

        steps = service2.steps(ran_id)["steps"]
        assert len(steps) == DEMO_STEPS
        assert [step["step_index"] for step in steps] == list(range(DEMO_STEPS))
        assert all(step["status"] == "ok" for step in steps)
        assert steps[0]["output_result"]["structured"]["items"], "результат шага цел"

        status = restarted.fleet_status()
        assert status["count"] == 3 and status["connected"] == 3
        assert status["total_tools"] > 0, "каталог перечитан после перезапуска"

        # Кэш инструментов лежит в файле: следующий запуск увидит состав флота
        # даже до подключения.
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert all(item["tools_cache"] for item in payload["servers"])
        assert "search_web" in [tool["name"] for tool in payload["servers"][0]["tools_cache"]]

        # И новый прогон продолжает нумерацию, не затирая прошлый.
        again = service2.start_demo(background=False)
        assert again["run_id"] != ran_id
        assert service2.list_runs()["count"] == 2
    finally:
        restarted.close()
