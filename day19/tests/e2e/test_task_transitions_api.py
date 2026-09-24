"""Тесты API контролируемых переходов (день 15) через TestClient.

Проверяются контракты правил допуска: 400 с причиной и подсказкой на недопустимый
переход, эндпоинты ``PATCH /tasks/{task_id}/context`` (флаги-согласования) и
``GET /tasks/{task_id}/allowed-next``, журнал отклонённых попыток и то, как
допустимые переходы видны в ответе генерации. Всё офлайн: временная SQLite и
подменённый клиент DeepSeek.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.storage import database
from backend.agents.agent_manager import AgentManager
from backend.storage.database import init_db, make_engine, make_session_factory

from support import FakeClient

TASK_ID = "tz"
AGENT_PAYLOAD = {"name": "Агент задачи", "temperature": 0.5, "max_tokens": 256}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient на временной БД с подменённым клиентом DeepSeek у агентов."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'transitions.db').as_posix()}")
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


def test_transition_skipping_a_stage_is_refused_with_explanation(client):
    """planning → done — 400 с перечислением пропущенных этапов."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    response = client.post(f"/tasks/{TASK_ID}/transition", json={"stage": "done"})
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Нельзя перейти из planning в done: пропущены этапы execution и validation "
        "Сначала перейдите в execution и пройдите этапы по порядку."
    )
    assert client.get(f"/tasks/{TASK_ID}/state").json()["stage"] == "planning"


def test_transition_without_flag_is_refused_with_hint(client):
    """planning → execution без plan_approved — 400 с причиной и подсказкой."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    response = client.post(f"/tasks/{TASK_ID}/transition", json={"stage": "execution"})
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Нельзя перейти в execution: план не утверждён "
        "Утвердите план: отметьте флаг «📝 План утверждён» в панели задачи."
    )


def test_flags_endpoint_opens_the_transition(client):
    """PATCH контекста выставляет флаг, после чего переход проходит."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    state = set_flags(client, plan_approved=True)
    assert state["context"]["plan_approved"] is True
    assert state["allowed_next"] == ["execution", "paused"]

    moved = client.post(f"/tasks/{TASK_ID}/transition", json={"stage": "execution"})
    assert moved.status_code == 200
    assert moved.json()["stage"] == "execution"
    assert moved.json()["context"]["plan_approved"] is True


def test_flags_endpoint_rejects_empty_and_unknown_bodies(client):
    """Тело без единого флага и тело с опечаткой в имени — 422."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    assert client.patch(f"/tasks/{TASK_ID}/context", json={}).status_code == 422
    assert client.patch(
        f"/tasks/{TASK_ID}/context", json={"nope": True}
    ).status_code == 422
    assert client.patch(
        f"/tasks/{TASK_ID}/context", json={"plan_aproved": True}
    ).status_code == 422
    # Ни одна из попыток ничего не изменила.
    assert client.get(f"/tasks/{TASK_ID}/state").json()["context"] == {
        "task_id": TASK_ID, "working_memory": {},
    }


def test_allowed_next_endpoint_reports_graph(client):
    """GET allowed-next отдаёт доступные и недоступные этапы с причинами."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    body = client.get(f"/tasks/{TASK_ID}/allowed-next").json()
    assert body == {
        "task_id": TASK_ID,
        "stage": "planning",
        "allowed_next": ["paused"],
        "blocked": [
            {
                "stage": "execution",
                "reason": "Нельзя перейти в execution: план не утверждён",
            },
            {
                "stage": "validation",
                "reason": "Нельзя перейти из planning в validation: пропущен этап execution",
            },
            {
                "stage": "done",
                "reason": "Нельзя перейти из planning в done: пропущены этапы execution и validation",
            },
        ],
    }
    assert set(body) == {"task_id", "stage", "allowed_next", "blocked"}


def test_rejected_attempt_lands_in_history(client):
    """Отклонённая попытка видна в журнале с accepted=false и причиной."""
    agent_id = new_agent(client)
    new_task(client, agent_id)

    client.post(f"/tasks/{TASK_ID}/transition", json={"stage": "done"})

    entries = client.get(f"/tasks/{TASK_ID}/history").json()["entries"]
    assert [entry["accepted"] for entry in entries] == [True, False]
    assert entries[-1]["to_stage"] == "done"
    assert entries[-1]["reason"].startswith("Нельзя перейти из planning в done")
    assert client.get(f"/tasks/{TASK_ID}/state").json()["stage"] == "planning"


def test_generate_reports_transition_lists_and_refusal_rule(client):
    """task_state несёт допустимые переходы, а промпт — запрет их нарушать."""
    agent_id = new_agent(client)
    new_task(client, agent_id, initial_stage="validation")

    body = client.post(
        f"/agents/{agent_id}/generate", json={"prompt": "покажи план"}
    ).json()

    assert body["task_state"]["allowed_next"] == ["execution", "paused"]
    # Недоступны: возврат в planning (откат идёт по одному этапу) и done без флага.
    assert [item["stage"] for item in body["task_state"]["blocked"]] == [
        "planning", "done",
    ]
    assert (
        "Не пытайся перейти в недопустимый этап — сначала заверши текущий."
        in body["system_prompt"]
    )
    assert body["task_intent"] is None
    assert body["task_proposal"] is None
