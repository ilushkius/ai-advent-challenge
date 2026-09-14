"""Тесты API-эндпоинтов дня 11 (стратегии, ветки, факты) через TestClient.

Эндпоинты проверяются на временной БД с подменённым клиентом DeepSeek:
смена стратегии не теряет диалог, ветвление создаёт дерево и переключает
активную ветку, факты возвращаются для sticky_facts.
"""
import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.agent_manager import AgentManager
from backend.database import init_db, make_engine, make_session_factory

from support import FakeClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient на временной БД с подменённым клиентом DeepSeek у агентов."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)

    manager = AgentManager(session_factory=factory)
    monkeypatch.setattr(database, "SessionLocal", factory)
    import backend.main as main
    monkeypatch.setattr(main, "get_manager", lambda: manager)

    from backend.agent import Agent
    fake = FakeClient()
    monkeypatch.setattr(Agent, "_make_client", lambda self: fake)

    with TestClient(main.app) as test_client:
        test_client.manager = manager
        test_client.fake = fake
        yield test_client


def create_agent(client, **overrides):
    payload = {
        "name": "Агент API",
        "model": "deepseek-chat",
        "temperature": 0.5,
        "max_tokens": 512,
    }
    payload.update(overrides)
    response = client.post("/agents", json=payload)
    assert response.status_code == 201
    return response.json()


def test_strategy_endpoints_set_and_persist(client):
    info = create_agent(client)
    agent_id = info["agent_id"]

    listing = client.get(f"/agents/{agent_id}/strategies").json()
    assert listing["strategy"] == "summary"
    assert listing["available"] == [
        "sliding_window", "sticky_facts", "branching", "summary",
    ]

    changed = client.post(
        f"/agents/{agent_id}/strategy",
        json={"strategy": "sliding_window", "window_size": 4},
    ).json()
    assert changed["strategy"] == "sliding_window"
    assert changed["window_size"] == 4

    # Стратегия сохранилась в конфигурации агента (GET /agents/{id}).
    agent = client.get(f"/agents/{agent_id}").json()
    assert agent["strategy"] == "sliding_window"
    assert agent["window_size"] == 4


def test_strategy_endpoint_rejects_unknown_value(client):
    info = create_agent(client)
    response = client.post(
        f"/agents/{info['agent_id']}/strategy", json={"strategy": "nope"}
    )
    assert response.status_code == 422


def test_strategy_unknown_agent_returns_404(client):
    assert client.post(
        "/agents/nope/strategy", json={"strategy": "summary"}
    ).status_code == 404
    assert client.get("/agents/nope/strategies").status_code == 404


def test_branching_endpoints_create_switch_list(client):
    info = create_agent(client, strategy="branching")
    agent_id = info["agent_id"]

    # Пара ходов через /generate создаёт корневой чекпоинт.
    assert client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": "Название: портал"}).status_code == 200
    assert client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": "Стек: FastAPI"}).status_code == 200

    tree = client.get(f"/agents/{agent_id}/branches").json()
    assert len(tree["branches"]) == 1
    root_id = tree["active_branch_id"]

    # Создать ветку от текущего состояния.
    tree = client.post(f"/agents/{agent_id}/branches", json={}).json()
    assert tree["active_branch_id"] != root_id
    new_id = tree["active_branch_id"]
    by_id = {b["id"]: b for b in tree["branches"]}
    assert by_id[new_id]["parent_id"] == root_id

    # Переключение на корень.
    tree = client.post(
        f"/agents/{agent_id}/branches/{root_id}/switch", json={}
    ).json()
    assert tree["active_branch_id"] == root_id


def test_branching_unknown_agent_returns_404(client):
    assert client.get("/agents/nope/branches").status_code == 404
    assert client.post("/agents/nope/branches", json={}).status_code == 404
    assert client.post(
        "/agents/nope/branches/1/switch", json={}
    ).status_code == 404


def test_facts_endpoint_returns_facts(client):
    info = create_agent(client, strategy="sticky_facts")
    agent_id = info["agent_id"]

    assert client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": "Имя: Иван; Бюджет: 5000"}).status_code == 200

    facts = client.get(f"/agents/{agent_id}/facts").json()["facts"]
    by_key = {f["key"]: f["value"] for f in facts}
    assert by_key["имя"] == "Иван"
    assert by_key["бюджет"] == "5000"

    assert client.get("/agents/nope/facts").status_code == 404
