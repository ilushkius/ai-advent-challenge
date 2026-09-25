"""Тесты шага оркестрации в ходе агента (день 20).

Два требования дня проверяются здесь вместе: реплика «найди данные и сохрани в
базу» запускает флоу по трём серверам, а его результат уходит модели системным
блоком того же запроса; реплика дня 19 «найди …, сделай сводку и сохрани в файл»
ОБЯЗАНА остаться пайплайном — иначе один и тот же ход запускал бы два прогона с
побочными эффектами, а контракт дня 19 (файл, а не база) был бы сломан.
"""
import pytest

from backend.services.orchestration_service import OrchestrationService
from backend.services.orchestrator import Orchestrator
from backend.services.pipeline_service import PipelineService
from backend.storage.orchestration_store import OrchestrationStore
from backend.storage.pipeline_store import PipelineStore

from orchestration_fakes import make_fleet_factory, make_fleet_registry
from support import FakeClient, create_agent

#: Реплика, которая обязана попасть в оркестрацию (сохранение в базу).
ORCH_REPLY = "найди данные про RAG и сохрани в базу"

#: Реплика дня 19: она обязана остаться пайплайном.
PIPELINE_REPLY = "найди статьи про RAG, сделай сводку и сохрани в файл"


def _agent(session_factory, tmp_path, **kwargs):
    """Агент с фейковым флотом, службами дня и подменённым клиентом DeepSeek."""
    factory = make_fleet_factory()
    registry = make_fleet_registry(tmp_path, factory=factory)
    registry.connect_all()
    store = OrchestrationStore(session_factory)
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry, store=store), store=store)
    pipeline = PipelineService(store=PipelineStore(session_factory))
    fake = FakeClient()
    agent = create_agent(session_factory, kwargs.pop("agent_id", "orch01"),
                         mcp_registry=registry, pipeline_service=pipeline, **kwargs)
    agent._orchestration_service = service
    agent._make_client = lambda: fake
    return agent, fake, registry, service


def test_orchestration_reply_runs_the_fleet_and_goes_into_prompt(session_factory, tmp_path):
    """Реплика про базу запускает флоу, а его результат уходит в системный промпт."""
    agent, fake, registry, service = _agent(session_factory, tmp_path)
    try:
        record = agent.generate(ORCH_REPLY)
    finally:
        registry.close()

    assert record["status"] == "ok"
    report = record["orchestration"]
    assert report["detected"] is True
    assert report["status"] == "completed"
    assert report["servers_used"] == ["search_server", "data_server",
                                      "storage_server"]
    assert report["tools_used"] == ["search_web", "summarize", "extract_keywords",
                                    "save_to_file", "save_to_db"]
    assert report["count"] == 5
    assert report["used_in_prompt"] is True
    assert report["added_tokens"] > 0
    assert report["run_id"] == service.list_runs()["runs"][0]["id"]

    # Один ход — один автоматизм: пайплайн и одиночный MCP-шаг пропущены.
    assert record["pipeline"]["detected"] is False
    assert record["pipeline"]["used_in_prompt"] is False
    assert record["mcp"] is None

    # Блок попал в системное сообщение этого же запроса — вместе с серверами.
    messages = fake.generate_calls[-1]["messages"]
    blocks = [str(item["content"]) for item in messages
              if "## Результат оркестрации" in str(item.get("content", ""))]
    assert len(blocks) == 1
    block = blocks[0]
    assert "Серверы: search_server, data_server, storage_server" in block
    assert "- search_web (search_server): ok" in block
    assert "Итог: оркестрация выполнена" in block
    assert record["system_prompt"].endswith(block.splitlines()[-1])


def test_pipeline_reply_stays_a_pipeline(session_factory, tmp_path):
    """Реплика дня 19 остаётся пайплайном: оркестрация её не перехватывает."""
    agent, _fake, registry, _service = _agent(session_factory, tmp_path,
                                              agent_id="orch02")
    try:
        record = agent.generate(PIPELINE_REPLY)
    finally:
        registry.close()
    assert record["status"] == "ok"
    assert record["orchestration"]["detected"] is False
    assert record["orchestration"]["status"] == ""
    assert record["orchestration"]["run_id"] is None
    assert record["pipeline"]["detected"] is True
    assert record["mcp"] is None


def test_plain_reply_touches_nothing(session_factory, tmp_path):
    """Обычная реплика не запускает ни оркестрацию, ни пайплайн."""
    agent, _fake, registry, _service = _agent(session_factory, tmp_path,
                                              agent_id="orch03")
    try:
        record = agent.generate("Сколько будет 2+2?")
    finally:
        registry.close()
    assert record["orchestration"] == {
        "detected": False, "run_id": None, "status": "", "message": "",
        "plan_source": "", "servers_used": [], "tools_used": [], "steps": [],
        "count": 0, "failed_at_step": None, "error": None,
        "total_duration_ms": 0, "used_in_prompt": False, "added_tokens": 0}


def test_failure_of_the_run_does_not_break_the_turn(session_factory, tmp_path):
    """Сбой оркестрации не роняет ход: реплика распознана, ответ собран без данных."""
    agent, fake, registry, service = _agent(session_factory, tmp_path,
                                            agent_id="orch04")
    try:
        def boom(*_args, **_kwargs):
            raise RuntimeError("реестр недоступен")

        service.orchestrator.execute = boom
        record = agent.generate(ORCH_REPLY)
    finally:
        registry.close()
    assert record["status"] == "ok"
    assert record["orchestration"]["detected"] is True
    assert record["orchestration"]["status"] == "failed"
    assert "реестр недоступен" in record["orchestration"]["error"]
    assert record["orchestration"]["used_in_prompt"] is False
    assert record["orchestration"]["added_tokens"] == 0
    # Данные неудачного прогона в промпт не попадают (правило дня 17).
    assert "## Результат оркестрации" not in str(fake.generate_calls[-1]["messages"])


def test_empty_fleet_reports_failure_without_breaking_the_turn(session_factory, tmp_path):
    """Пустой флот: реплика распознана, прогон не удался, ответ по-прежнему есть."""
    registry = make_fleet_registry(tmp_path, names=())
    registry.connect_all()
    store = OrchestrationStore(session_factory)
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry, store=store), store=store)
    fake = FakeClient()
    agent = create_agent(session_factory, "orch05", mcp_registry=registry,
                         pipeline_service=PipelineService(store=PipelineStore(session_factory)))
    agent._orchestration_service = service
    agent._make_client = lambda: fake
    try:
        record = agent.generate(ORCH_REPLY)
    finally:
        registry.close()
    assert record["status"] == "ok"
    assert record["orchestration"]["detected"] is True
    assert record["orchestration"]["status"] == "failed"
    assert record["orchestration"]["error"]
    assert record["orchestration"]["used_in_prompt"] is False
    assert service.list_runs()["count"] == 0
