"""Тесты API персонализации (день 13, наследовано из дня 12): /users, /users/{id}/profile, /agents/{id}/profile.

Проверяются коды ответов и контракт: профиль создаётся/меняется/удаляется,
применяется к агентам пользователя, а генерация возвращает применённый профиль
и итоговый системный промпт. Сети нет: клиент DeepSeek подменён ``FakeClient``.
"""
import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.agent_manager import AgentManager
from backend.database import init_db, make_engine, make_session_factory
from backend.profiles import PROFILE_HEADER

from support import FakeClient


STRICT = {
    "name": "Инженер",
    "preferences": {"tone": "технический", "verbosity": "кратко",
                    "format": "plain text", "language": "русский"},
    "constraints": {"max_response_length": 600},
    "custom_instructions": "",
}

FRIENDLY = {
    "name": "Илья",
    "preferences": {"tone": "дружелюбный", "verbosity": "подробно",
                    "format": "markdown", "language": "русский"},
    "constraints": {"forbidden_topics": ["политика"]},
    "custom_instructions": "Объясняй простыми словами, используй аналогии",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient на временной БД с подменённым клиентом DeepSeek у агентов."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'profile.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)

    manager = AgentManager(session_factory=factory)
    monkeypatch.setattr(database, "SessionLocal", factory)
    import backend.main as main
    monkeypatch.setattr(main, "get_manager", lambda: manager)

    from backend.agent import Agent
    fake = FakeClient(reply="Ответ ассистента")
    monkeypatch.setattr(Agent, "_make_client", lambda self: fake)

    with TestClient(main.app) as test_client:
        test_client.manager = manager
        test_client.fake = fake
        yield test_client


def create_agent(client, **overrides):
    """Создаёт агента через API (имя обязательно, остальное — по умолчанию)."""
    payload = {"name": "Агент профиля", "user_id": "default"}
    payload.update(overrides)
    response = client.post("/agents", json=payload)
    assert response.status_code == 201
    return response.json()


def test_profile_crud_roundtrip(client):
    """POST → GET → список → PUT → DELETE по контракту дня 13."""
    created = client.post("/users/ivan/profile", json=STRICT)
    assert created.status_code == 201
    body = created.json()
    assert body["user_id"] == "ivan"
    assert body["preferences"]["tone"] == "технический"
    assert body["personalized"] is True
    assert "технический" in body["summary"]

    fetched = client.get("/users/ivan/profile")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Инженер"
    assert fetched.json()["id"] == body["id"]

    listed = client.get("/users")
    assert listed.status_code == 200
    assert [item["user_id"] for item in listed.json()] == ["ivan"]

    updated = client.put("/users/ivan/profile", json=FRIENDLY)
    assert updated.status_code == 200
    assert updated.json()["preferences"]["tone"] == "дружелюбный"
    assert updated.json()["constraints"]["max_response_length"] is None
    assert updated.json()["created_at"] == body["created_at"]

    deleted = client.delete("/users/ivan/profile")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "user_id": "ivan"}
    assert client.get("/users/ivan/profile").status_code == 404
    assert client.get("/users").json() == []


def test_create_existing_profile_conflicts(client):
    """Профиль уже есть — 409 (создание не перезаписывает настройки)."""
    client.post("/users/ivan/profile", json=STRICT)
    response = client.post("/users/ivan/profile", json=FRIENDLY)
    assert response.status_code == 409
    assert client.get("/users/ivan/profile").json()["name"] == "Инженер"


def test_update_and_delete_unknown_profile_return_404(client):
    assert client.put("/users/nobody/profile", json=STRICT).status_code == 404
    assert client.delete("/users/nobody/profile").status_code == 404


@pytest.mark.parametrize("payload", [
    {"preferences": {"tone": "токсичный"}},
    {"preferences": {"format": "yaml"}},
    {"preferences": {"скорость": "быстро"}},
    {"constraints": {"max_response_length": 5}},
    {"constraints": {"max_words": 100}},
    {"custom_instructions": "а" * 4100},
    {"name": "и" * 200},
])
def test_invalid_profile_returns_422(client, payload):
    """Невалидные настройки — 422 с текстом из profiles.py, а не 500."""
    assert client.post("/users/ivan/profile", json=payload).status_code == 422
    assert client.get("/users/ivan/profile").status_code == 404


def test_generate_returns_applied_profile_and_system_prompt(client):
    """POST /agents/{id}/generate отдаёт профиль, его элементы и промпт."""
    client.post("/users/ivan/profile", json=STRICT)
    info = create_agent(client, user_id="ivan")

    body = client.post(
        f"/agents/{info['agent_id']}/generate",
        json={"prompt": "Как ускорить запрос в PostgreSQL?"},
    ).json()

    assert body["status"] == "ok"
    assert body["profile"]["user_id"] == "ivan"
    assert body["profile"]["personalized"] is True
    elements = {item["field"]: item["value"] for item in body["profile"]["elements"]}
    assert elements["preferences.tone"] == "технический"
    assert elements["preferences.format"] == "plain text"
    assert elements["constraints.max_response_length"] == "600"
    assert body["system_prompt"].startswith(PROFILE_HEADER)
    # Промпт в ответе — это ровно то, что ушло в модель.
    sent_system = client.fake.generate_calls[-1]["messages"][0]
    assert sent_system["content"] == body["system_prompt"]


def test_generate_without_profile_reports_no_personalization(client):
    """Без профиля генерация работает как раньше, но честно это сообщает."""
    info = create_agent(client, user_id="nobody")

    body = client.post(f"/agents/{info['agent_id']}/generate",
                       json={"prompt": "Привет"}).json()

    assert body["status"] == "ok"
    assert body["profile"]["personalized"] is False
    assert body["profile"]["elements"] == []
    assert body["system_prompt"] == ""


def test_patch_agent_switches_profile(client):
    """PATCH /agents/{id} с user_id переключает профиль (быстрая смена в UI)."""
    client.post("/users/ivan/profile", json=STRICT)
    client.post("/users/anna/profile", json=FRIENDLY)
    info = create_agent(client, user_id="ivan")
    agent_id = info["agent_id"]
    assert "технический" in client.get(
        f"/agents/{agent_id}/profile"
    ).json()["system_prompt"]

    patched = client.patch(f"/agents/{agent_id}", json={"user_id": "anna"})
    assert patched.status_code == 200
    assert patched.json()["user_id"] == "anna"

    state = client.get(f"/agents/{agent_id}/profile").json()
    assert state["user_id"] == "anna"
    assert "дружелюбный" in state["system_prompt"]
    assert {item["field"] for item in state["elements"]} >= {
        "name", "preferences.tone", "preferences.format",
        "preferences.verbosity", "custom_instructions",
    }
    # Профиль виден и в списке агентов (селектор в интерфейсе).
    assert client.get("/agents").json()[0]["user_id"] == "anna"


def test_profile_update_reaches_running_agent(client):
    """PUT профиля применяется к живому агенту: applied_to_agents > 0."""
    client.post("/users/ivan/profile", json=STRICT)
    info = create_agent(client, user_id="ivan")

    response = client.put("/users/ivan/profile", json=FRIENDLY).json()
    assert response["applied_to_agents"] == 1

    state = client.get(f"/agents/{info['agent_id']}/profile").json()
    assert "дружелюбный" in state["system_prompt"]
    assert "политика" in state["system_prompt"]
    assert state["instructions"] == [
        "Объясняй простыми словами, используй аналогии"
    ]


def test_delete_profile_keeps_agent_without_personalization(client):
    """Удаление профиля не ломает агента: он просто теряет персонализацию."""
    client.post("/users/ivan/profile", json=STRICT)
    info = create_agent(client, user_id="ivan")
    agent_id = info["agent_id"]

    assert client.delete("/users/ivan/profile").status_code == 200

    state = client.get(f"/agents/{agent_id}/profile").json()
    assert state["personalized"] is False
    assert state["system_prompt"] == ""
    body = client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": "Привет"}).json()
    assert body["status"] == "ok"
    assert body["profile"]["personalized"] is False


def test_agent_profile_unknown_agent_returns_404(client):
    assert client.get("/agents/ffffffff/profile").status_code == 404


def test_root_and_docs_list_personalization_endpoints(client):
    """Корневой ответ перечисляет эндпоинты персонализации (навигация в UI)."""
    root = client.get("/").json()
    assert "personalization" in root
    for path in (
        "GET /users",
        "GET /users/{user_id}/profile",
        "POST /users/{user_id}/profile",
        "PUT /users/{user_id}/profile",
        "DELETE /users/{user_id}/profile",
        "GET /agents/{agent_id}/profile",
    ):
        assert path in root["endpoints"]

    schema = client.get("/openapi.json").json()
    assert "/users/{user_id}/profile" in schema["paths"]
    assert set(schema["paths"]["/users/{user_id}/profile"]) >= {
        "get", "post", "put", "delete",
    }
