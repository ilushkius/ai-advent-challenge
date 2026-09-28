"""Тесты эндпоинтов планировщика (день 18).

Проверяется контракт ``/scheduler``: каталог инструментов, создание задачи (201 и
отказы 400/422), список и состояние планировщика, пауза и возобновление (409 на
неверном состоянии), удаление, история запусков, ручной запуск, напоминания,
собранные данные, сводки, очередь уведомлений и их отметка «прочитано». В конце —
то, ради чего день делался: ответ генерации несёт поле ``schedule``, когда реплика
поставила фоновую задачу.

Планировщик в тесте — заглушка без таймеров (``SchedulerStub``): расписание
считается и пишется в БД, тик исполняется по требованию, а фоновых задач в тестах
не появляется. Настоящая связка с APScheduler проверяется отдельно
(``tests/integration/test_scheduler_apscheduler.py``).
"""
import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.services.mcp_registry import MCPRegistry
from backend.services.schedule_service import ScheduleService
from backend.services.scheduler import TaskScheduler
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory
from backend.storage.scheduler_data_store import SchedulerDataStore
from backend.storage.scheduler_store import SchedulerStore

from mcp_fakes import FAKE_TOOL_CATALOG, make_mcp_factory
from scheduler_fakes import FakeFetcher, SchedulerStub
from support import FakeClient

COLLECT = {"source_url": "https://example.test/posts", "interval_seconds": 10,
           "name": "posts"}

#: Реплика, по которой агент сам ставит фоновую задачу (ключевые слова + время).
REMINDER_QUESTION = "Напомни мне через 30 секунд проверить почту"

#: Плоский ответ инструмента планировщика (как его собирает MCP-сервер дня).
REMINDER_RESULT = {
    "task_id": 12, "reminder_id": 3, "text": "проверить почту",
    "remind_at": "2026-09-23T10:00:30+00:00", "status": "scheduled",
    "next_run_at": "2026-09-23T10:00:30+00:00",
    "message": "Напоминание запланировано на 10:00:30 UTC",
}


def _build_client(tmp_path, monkeypatch, *, connected: bool = True):
    """TestClient с изолированной БД, заглушкой планировщика и фейковым реестром MCP."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'scheduler.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    import backend.api.main as main

    fetcher = FakeFetcher()
    store = SchedulerStore(session_factory=factory)
    data = SchedulerDataStore(session_factory=factory)
    scheduler = SchedulerStub(TaskScheduler(store=store, data=data, fetch=fetcher))
    service = ScheduleService(scheduler=scheduler, store=store, data=data, fetch=fetcher)

    registry = MCPRegistry(client_factory=make_mcp_factory(
        tools=FAKE_TOOL_CATALOG, call_result=REMINDER_RESULT))
    if connected:
        registry.connect("uv run python mcp_server/server.py")
    manager = AgentManager(session_factory=factory, mcp_registry=registry)

    monkeypatch.setattr(main, "get_scheduler", lambda: scheduler)
    monkeypatch.setattr(main, "get_schedule_service", lambda: service)
    monkeypatch.setattr(main, "get_manager", lambda: manager)
    monkeypatch.setattr(main, "get_mcp_registry", lambda: registry)
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient())

    test_client = TestClient(main.app)
    test_client.fetcher = fetcher
    test_client.scheduler = scheduler
    return test_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с подключённым фейковым сервером дня."""
    with _build_client(tmp_path, monkeypatch) as test_client:
        yield test_client


def _create(client, tool="collect_data", arguments=None, **extra):
    """Создаёт задачу через API и возвращает ответ."""
    payload = {"tool": tool, "arguments": COLLECT if arguments is None else arguments}
    payload.update(extra)
    return client.post("/scheduler/tasks", json=payload)


def test_tools_catalog(client):
    """GET /scheduler/tools отдаёт три инструмента с аргументами и подсказкой."""
    body = client.get("/scheduler/tools").json()
    assert body["count"] == 3
    names = [item["name"] for item in body["tools"]]
    assert names == ["schedule_reminder", "collect_data", "generate_summary"]
    collect = next(item for item in body["tools"] if item["name"] == "collect_data")
    assert [arg["name"] for arg in collect["arguments"]] == [
        "source_url", "interval_seconds", "name"
    ]
    assert collect["schedule_help"]


def test_create_task_returns_task_result_and_message(client):
    """Создание задачи: 201, расписание в ответе, первая запись уже собрана."""
    response = _create(client)
    assert response.status_code == 201
    body = response.json()
    assert body["task"]["schedule_type"] == "interval"
    assert body["task"]["next_run_at"]
    assert body["task"]["status"] == "active"
    assert body["result"]["collection"]["records_saved"] == 1
    assert body["immediate"] is True
    assert "Сбор" in body["message"]
    assert body["error"] is None


def test_create_task_validation_errors(client):
    """Незнакомый инструмент и негодные аргументы — 400 с текстом причины."""
    unknown = _create(client, tool="нет такого", arguments={})
    assert unknown.status_code == 400
    assert "не входит в планировщик" in unknown.json()["detail"]

    bad_interval = _create(client, arguments={"source_url": "https://x.test/p",
                                             "interval_seconds": 0, "name": "p"})
    assert bad_interval.status_code == 400
    assert "от 1 до 86400" in bad_interval.json()["detail"]

    bad_url = _create(client, arguments={"source_url": "ftp://x.test/p",
                                        "interval_seconds": 10, "name": "p"})
    assert bad_url.status_code == 400
    assert "http:// или https://" in bad_url.json()["detail"]


def test_create_task_rejects_bad_schedule(client):
    """Неразобранное расписание — 400, а не «создалось как получилось»."""
    response = _create(client, schedule_type="cron", schedule_value={"cron": "* *"})
    assert response.status_code == 400
    assert "пяти полей" in response.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"arguments": {}},                                    # нет tool
    {"tool": "", "arguments": {}},                        # пустой tool
    {"tool": "collect_data", "arguments": {}, "schedule_type": "ежедневно"},
    {"tool": "collect_data", "arguments": {}, "name": ""},
])
def test_create_task_validates_body(client, payload):
    """Невалидное тело ловит Pydantic: 422 до всякой доменной логики."""
    assert client.post("/scheduler/tasks", json=payload).status_code == 422


def test_tasks_list_and_scheduler_status(client):
    """Список задач идёт с блоком состояния планировщика; фильтр по состоянию работает."""
    _create(client)
    body = client.get("/scheduler/tasks").json()
    assert body["count"] == 1
    assert body["scheduler"]["running"] is True
    assert body["scheduler"]["sync_seconds"] > 0
    assert client.get("/scheduler/tasks?status=paused").json()["count"] == 0
    assert client.get("/scheduler/status").json()["running"] is True
    assert client.get("/scheduler/tasks?status=нет такого").status_code == 400


def test_pause_and_resume_states(client):
    """Пауза и возобновление проходят; неверное состояние — 409."""
    task_id = _create(client).json()["task"]["id"]
    paused = client.post(f"/scheduler/tasks/{task_id}/pause")
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    assert client.post(f"/scheduler/tasks/{task_id}/pause").status_code == 409
    resumed = client.post(f"/scheduler/tasks/{task_id}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"
    assert client.post(f"/scheduler/tasks/{task_id}/resume").status_code == 409
    assert client.post("/scheduler/tasks/999/pause").status_code == 404


def test_run_task_records_a_tick(client):
    """Ручной запуск пишет тик в журнал и обновляет метки задачи."""
    task_id = _create(client).json()["task"]["id"]
    response = client.post(f"/scheduler/tasks/{task_id}/run")
    assert response.status_code == 200
    assert response.json()["phase"] == "tick"
    assert response.json()["status"] == "ok"
    history = client.get(f"/scheduler/tasks/{task_id}/history").json()
    assert history["count"] == 2  # prepare при регистрации + tick
    assert {run["phase"] for run in history["runs"]} == {"prepare", "tick"}
    assert history["task"]["last_run_at"] and history["task"]["next_run_at"]


def test_delete_task_and_history_of_missing(client):
    """Удаление задачи — 200, повтор — 404; история удалённой тоже недоступна."""
    task_id = _create(client).json()["task"]["id"]
    assert client.delete(f"/scheduler/tasks/{task_id}").json() == {
        "status": "deleted", "task_id": task_id,
    }
    assert client.delete(f"/scheduler/tasks/{task_id}").status_code == 404
    assert client.get(f"/scheduler/tasks/{task_id}/history").status_code == 404
    assert client.get("/scheduler/tasks").json()["count"] == 0


def test_reminder_lifecycle_over_api(client):
    """Напоминание: создаётся, видно в списке, после запуска — выдано."""
    created = _create(client, tool="schedule_reminder",
                      arguments={"text": "позвонить клиенту", "delay_seconds": 30}).json()
    assert created["task"]["schedule_type"] == "date"
    reminders = client.get("/scheduler/reminders").json()
    assert reminders["count"] == 1
    assert reminders["reminders"][0]["status"] == "scheduled"
    assert reminders["reminders"][0]["text"] == "позвонить клиенту"

    client.post(f"/scheduler/tasks/{created['task']['id']}/run")
    assert client.get("/scheduler/reminders?status=done").json()["count"] == 1
    assert client.get("/scheduler/reminders?status=нет такого").status_code == 400


def test_collected_and_summaries_endpoints(client):
    """Собранные данные и сводки: фильтр по имени и метрики в ответе."""
    _create(client)
    collected = client.get("/scheduler/collected?name=posts").json()
    assert collected["total"] == 1 and collected["count"] == 1
    assert collected["records"][0]["payload"]

    summary = _create(client, tool="generate_summary",
                      arguments={"name": "posts", "interval_seconds": 20}).json()
    assert summary["result"]["summary"]["total_records"] == 1
    summaries = client.get("/scheduler/summaries?name=posts").json()
    assert summaries["count"] == 1
    assert summaries["summaries"][0]["key_metrics"]["numeric"]["id"]["max"] >= 1


def test_notifications_queue_and_read(client):
    """Уведомление сводки ждёт в очереди; отметка «прочитано» его снимает (404 — нет такого)."""
    _create(client, tool="generate_summary", arguments={"name": "posts",
                                                        "interval_seconds": 20})
    queue = client.get("/scheduler/notifications").json()
    assert queue["count"] == 1 and queue["unread"] == 1
    assert queue["notifications"][0]["kind"] == "summary"
    notification_id = queue["notifications"][0]["id"]

    read = client.post(f"/scheduler/notifications/{notification_id}/read")
    assert read.status_code == 200 and read.json()["unread"] is False
    assert client.get("/scheduler/notifications?unread_only=true").json()["count"] == 0
    assert client.post("/scheduler/notifications/999/read").status_code == 404


def test_generate_reports_scheduled_task(client):
    """Ответ генерации несёт поле ``schedule``: фоновая задача действительно поставлена."""
    agent_id = client.post("/agents", json={"name": "Планировщик"}).json()["agent_id"]
    response = client.post(f"/agents/{agent_id}/generate",
                           json={"prompt": REMINDER_QUESTION})
    assert response.status_code == 200
    body = response.json()
    assert body["mcp"]["tool"] == "schedule_reminder"
    schedule = body["schedule"]
    assert schedule is not None
    assert schedule["registered"] is True
    assert schedule["tool"] == "schedule_reminder"
    assert schedule["task"]["id"] == 12
    assert "## Данные планировщика" in body["system_prompt"]


def test_generate_without_scheduler_intent_has_no_report(tmp_path, monkeypatch):
    """Реплика без ключевых слов планировщика: ``schedule`` пусто, задачи нет."""
    with _build_client(tmp_path, monkeypatch) as test_client:
        agent_id = test_client.post("/agents", json={"name": "Планировщик"}).json()["agent_id"]
        body = test_client.post(f"/agents/{agent_id}/generate",
                                json={"prompt": "Сколько будет 2+2?"}).json()
        assert body["schedule"] is None
        assert body["mcp"]["called"] is False
        assert test_client.get("/scheduler/tasks").json()["count"] == 0
