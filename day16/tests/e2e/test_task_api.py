"""Тесты API состояния задачи (день 15) через TestClient.

Проверяются контракты одиннадцати эндпоинтов ``/agents/{id}/tasks`` и
``/tasks/{id}/...``: коды ответов (201/200/400/404/409/422), полный цикл жизни
задачи, контролируемые переходы (граф допуска, guard-условия на флаги, журнал
отклонённых попыток) и поле ``task_state`` в ответе генерации.
Всё офлайн: временная SQLite и подменённый клиент DeepSeek.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.storage import database
from backend.agents.agent_manager import AgentManager
from backend.storage.database import init_db, make_engine, make_session_factory
from backend.domain.task_fsm import TaskStage, TaskStep

from support import FakeClient

TASK_ID = "tz"
AGENT_PAYLOAD = {"name": "Агент задачи", "temperature": 0.5, "max_tokens": 256}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient на временной БД с подменённым клиентом DeepSeek у агентов."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'tasks.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)

    manager = AgentManager(session_factory=factory)
    monkeypatch.setattr(database, "SessionLocal", factory)
    import backend.api.main as main
    monkeypatch.setattr(main, "get_manager", lambda: manager)

    from backend.agents.agent import Agent
    fake = FakeClient(reply="Ответ ассистента")
    monkeypatch.setattr(Agent, "_make_client", lambda self: fake)

    with TestClient(main.app) as test_client:
        test_client.fake = fake
        yield test_client


def new_agent(client, **overrides) -> str:
    """Создаёт агента через API и возвращает его id."""
    payload = dict(AGENT_PAYLOAD)
    payload.update(overrides)
    response = client.post("/agents", json=payload)
    assert response.status_code == 201
    return response.json()["agent_id"]


def new_task(client, agent_id: str, **body) -> dict:
    """Создаёт задачу через API и возвращает её состояние."""
    payload = {"task_id": TASK_ID}
    payload.update(body)
    response = client.post(f"/agents/{agent_id}/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def set_flags(client, task_id: str = TASK_ID, **flags) -> dict:
    """Выставляет флаги-согласования задачи (PATCH контекста) и отдаёт состояние."""
    response = client.patch(f"/tasks/{task_id}/context", json=flags)
    assert response.status_code == 200, response.text
    return response.json()


def test_create_task_returns_first_step_of_planning(client):
    """POST создаёт задачу на planning/gather_requirements с блоком промпта."""
    agent_id = new_agent(client)
    body = new_task(client, agent_id)

    assert body["task_id"] == TASK_ID
    assert body["agent_id"] == agent_id
    assert body["stage"] == TaskStage.PLANNING.value
    assert body["current_step"] == TaskStep.GATHER_REQUIREMENTS.value
    assert body["is_active"] is True
    assert body["rollback_stage"] is None
    assert body["prompt_block"].startswith("Состояние задачи")
    assert body["expected_action"].startswith("ожидается")

    state = client.get(f"/tasks/{TASK_ID}/state").json()
    assert state == body


def test_create_task_from_other_stage(client):
    """Стартовый этап можно задать телом запроса."""
    agent_id = new_agent(client)
    body = new_task(client, agent_id, initial_stage="validation")
    assert body["stage"] == TaskStage.VALIDATION.value
    assert body["current_step"] == TaskStep.REVIEW.value


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"task_id": TASK_ID}, 409),
        ({"task_id": "tz2", "initial_stage": "paused"}, 422),
        ({"task_id": "tz2", "initial_stage": "done"}, 422),
        ({"task_id": "tz2", "initial_stage": "нет-такого"}, 422),
        ({"task_id": ""}, 422),
        ({"task_id": "x" * 100}, 422),
    ],
)
def test_create_task_error_contract(client, body, expected):
    """Повторный id — 409, невалидный или пустой этап — 422."""
    agent_id = new_agent(client)
    if expected == 409:
        new_task(client, agent_id)
    response = client.post(f"/agents/{agent_id}/tasks", json=body)
    assert response.status_code == expected


def test_create_task_for_unknown_agent_returns_404(client):
    response = client.post("/agents/nobody/tasks", json={"task_id": TASK_ID})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/tasks/nope/state", None),
        ("get", "/tasks/nope/history", None),
        ("get", "/tasks/nope/allowed-next", None),
        ("patch", "/tasks/nope/context", {"plan_approved": True}),
        ("post", "/tasks/nope/pause", None),
        ("post", "/tasks/nope/resume", None),
        ("post", "/tasks/nope/advance", None),
        ("post", "/tasks/nope/rollback", {"to_stage": "planning"}),
        ("post", "/tasks/nope/transition", {"stage": "done"}),
    ],
)
def test_unknown_task_returns_404(client, method, path, body):
    """Неизвестная задача — 404 на всех эндпоинтах домена."""
    response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert response.status_code == 404
    assert "не найдена" in response.json()["detail"]


def test_agent_tasks_list_excludes_finished(client):
    """GET /agents/{id}/tasks отдаёт незавершённые задачи агента."""
    agent_id = new_agent(client)
    new_task(client, agent_id)
    new_task(client, agent_id, task_id="tz2", initial_stage="validation")

    listed = client.get(f"/agents/{agent_id}/tasks").json()
    assert [item["task_id"] for item in listed] == [TASK_ID, "tz2"]

    set_flags(client, task_id="tz2", validation_passed=True)
    client.post("/tasks/tz2/transition", json={"stage": "done"})
    assert [
        item["task_id"] for item in client.get(f"/agents/{agent_id}/tasks").json()
    ] == [TASK_ID]


def test_pause_resume_keep_step(client):
    """Пауза сохраняет шаг, продолжение возвращает в тот же этап и шаг."""
    agent_id = new_agent(client)
    new_task(client, agent_id, initial_stage="execution")

    paused = client.post(f"/tasks/{TASK_ID}/pause")
    assert paused.status_code == 200
    assert paused.json()["stage"] == TaskStage.PAUSED.value
    assert paused.json()["current_step"] == TaskStep.IMPLEMENT.value
    assert paused.json()["paused_from_stage"] == TaskStage.EXECUTION.value

    assert client.get(f"/tasks/{TASK_ID}/state").json()["stage"] == "paused"

    resumed = client.post(f"/tasks/{TASK_ID}/resume").json()
    assert resumed["stage"] == TaskStage.EXECUTION.value
    assert resumed["current_step"] == TaskStep.IMPLEMENT.value
    assert resumed["paused_from_stage"] is None

    assert client.post(f"/tasks/{TASK_ID}/pause").status_code == 200
    assert client.post(f"/tasks/{TASK_ID}/pause").status_code == 400
    assert client.post(f"/tasks/{TASK_ID}/resume").status_code == 200
    assert client.post(f"/tasks/{TASK_ID}/resume").status_code == 400


def test_advance_rollback_cycle(client):
    """advance ведёт по шагам и этапам, rollback возвращает на этап назад.

    Границы этапов закрыты согласованиями: без флага шаг вперёд с последнего
    шага этапа отклоняется, поэтому флаги выставляются по ходу.
    """
    agent_id = new_agent(client)
    new_task(client, agent_id)

    set_flags(client, plan_approved=True)
    for _ in range(3):
        body = client.post(f"/tasks/{TASK_ID}/advance").json()
    assert (body["stage"], body["current_step"]) == ("execution", "implement")

    set_flags(client, implementation_complete=True)
    for _ in range(2):
        body = client.post(f"/tasks/{TASK_ID}/advance").json()
    assert (body["stage"], body["current_step"]) == ("validation", "review")

    rolled = client.post(
        f"/tasks/{TASK_ID}/rollback", json={"to_stage": "execution"}
    )
    assert rolled.status_code == 200
    assert (rolled.json()["stage"], rolled.json()["current_step"]) == (
        "execution", "implement",
    )

    assert client.post(
        f"/tasks/{TASK_ID}/rollback", json={"to_stage": "validation"}
    ).status_code == 400
    assert client.post(
        f"/tasks/{TASK_ID}/rollback", json={"to_stage": "нет-такого"}
    ).status_code == 422


def test_transition_to_done_then_advance_is_rejected(client):
    """Завершение задачи одним вызовом; после done переходов нет вовсе."""
    agent_id = new_agent(client)
    new_task(client, agent_id, initial_stage="validation")

    set_flags(client, validation_passed=True)
    done = client.post(
        f"/tasks/{TASK_ID}/transition",
        json={"stage": "done", "reason": "задача завершена"},
    )
    assert done.status_code == 200
    body = done.json()
    assert body["stage"] == TaskStage.DONE.value
    assert body["current_step"] == TaskStep.FINALIZE.value
    assert body["is_active"] is False
    assert body["allowed_next"] == []
    assert body["expected_action"] == "задача завершена; ожидается новая задача"

    assert client.post(f"/tasks/{TASK_ID}/advance").status_code == 400
    pause = client.post(f"/tasks/{TASK_ID}/pause")
    assert pause.status_code == 400
    assert "этап done терминальный" in pause.json()["detail"]
    assert client.post(f"/tasks/{TASK_ID}/resume").status_code == 400


def test_transition_body_validation(client):
    """Тело перехода проверяется схемой: неизвестные этап/шаг — 422."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    assert client.post(
        f"/tasks/{TASK_ID}/transition", json={"stage": "нет-такого"}
    ).status_code == 422
    assert client.post(
        f"/tasks/{TASK_ID}/transition",
        json={"stage": "execution", "step": "нет-такого"},
    ).status_code == 422
    assert client.post(
        f"/tasks/{TASK_ID}/transition",
        json={"stage": "execution", "reason": "я" * 300},
    ).status_code == 422
    # Недопустимая пара этапов — это уже 400 (валидация стейт-машины).
    assert client.post(
        f"/tasks/{TASK_ID}/transition", json={"stage": "validation"}
    ).status_code == 400


def test_history_lists_creation_and_every_transition(client):
    """Журнал: создание + по записи на переход, с причинами и временем."""
    agent_id = new_agent(client)
    new_task(client, agent_id, initial_stage="execution")
    client.post(f"/tasks/{TASK_ID}/advance")
    client.post(f"/tasks/{TASK_ID}/pause")
    client.post(f"/tasks/{TASK_ID}/resume")
    client.post(f"/tasks/{TASK_ID}/rollback", json={"to_stage": "planning"})

    body = client.get(f"/tasks/{TASK_ID}/history").json()
    assert body["task_id"] == TASK_ID
    entries = body["entries"]
    assert [entry["reason"] for entry in entries] == [
        "задача создана",
        "следующий шаг",
        "пауза",
        "продолжение после паузы",
        "откат на предыдущий этап",
    ]
    assert entries[0]["from_stage"] is None
    assert entries[0]["accepted"] is True
    assert entries[-1]["from_stage"] == "execution"
    assert entries[-1]["to_stage"] == "planning"
    assert all(entry["accepted"] for entry in entries)
    assert all(entry["created_at"] for entry in entries)


def test_generate_exposes_task_state_and_updates_it(client):
    """Ответ генерации содержит task_state, а реплика обновляет состояние."""
    agent_id = new_agent(client)
    new_task(client, agent_id, initial_stage="execution")

    body = client.post(
        f"/agents/{agent_id}/generate", json={"prompt": "покажи план"}
    ).json()
    assert body["status"] == "ok"
    assert body["task_state"]["task_id"] == TASK_ID
    assert "Текущий шаг: implement" in body["system_prompt"]

    advanced = client.post(
        f"/agents/{agent_id}/generate", json={"prompt": "подтверждаю"}
    ).json()
    assert advanced["task_state"]["current_step"] == "test_locally"
    assert "Текущий шаг: test_locally" in advanced["system_prompt"]


def test_generate_without_task_has_no_state(client):
    """Без заведённой задачи блок в промпт не попадает."""
    agent_id = new_agent(client)
    body = client.post(
        f"/agents/{agent_id}/generate", json={"prompt": "привет"}
    ).json()
    assert body["task_state"] is None
    assert "Текущий этап" not in body["system_prompt"]


def test_root_lists_task_endpoints(client):
    """Корневой ответ перечисляет эндпоинты состояния задачи (навигация в UI)."""
    root = client.get("/").json()
    assert "tasks" in root
    assert "transition" in root["task_transitions"]
    for path in (
        "POST /agents/{agent_id}/tasks",
        "GET /agents/{agent_id}/tasks",
        "GET /tasks/{task_id}/state",
        "GET /tasks/{task_id}/history",
        "GET /tasks/{task_id}/allowed-next",
        "PATCH /tasks/{task_id}/context",
        "POST /tasks/{task_id}/pause",
        "POST /tasks/{task_id}/resume",
        "POST /tasks/{task_id}/advance",
        "POST /tasks/{task_id}/rollback",
        "POST /tasks/{task_id}/transition",
    ):
        assert path in root["endpoints"]

    schema = client.get("/openapi.json").json()
    assert "/tasks/{task_id}/state" in schema["paths"]
    assert "task_state" in schema["components"]["schemas"]["GenerateResponse"][
        "properties"
    ]
