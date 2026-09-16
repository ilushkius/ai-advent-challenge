"""Тесты API слоёв памяти (день 11) через TestClient.

Проверяются контракты десяти эндпоинтов ``/agents/{id}/memory/...``: коды
ответов, форма тел, поведение при неизвестном агенте и записи (404), валидация
категории и уверенности (422), а также отчёт ``memory`` в ответе генерации.
Всё офлайн: временная SQLite и подменённый клиент DeepSeek.
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
    engine = make_engine(f"sqlite:///{(tmp_path / 'memory.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)

    # Менеджер-синглтон приложения подменяем на изолированный (своя БД).
    manager = AgentManager(session_factory=factory)
    monkeypatch.setattr(database, "SessionLocal", factory)
    import backend.main as main
    monkeypatch.setattr(main, "get_manager", lambda: manager)

    from backend.agent import Agent
    fake = FakeClient()
    monkeypatch.setattr(Agent, "_make_client", lambda self: fake)

    with TestClient(main.app) as test_client:
        yield test_client


def create_agent(client, **overrides):
    """Создаёт агента через API и возвращает JSON-ответ."""
    payload = {
        "name": "Агент памяти",
        "model": "deepseek-chat",
        "temperature": 0.5,
        "max_tokens": 512,
        "summary_enabled": True,
        "keep_last_messages": 2,
        "summarize_every": 2,
    }
    payload.update(overrides)
    response = client.post("/agents", json=payload)
    assert response.status_code == 201
    return response.json()


def test_new_agent_has_session_and_task(client):
    """Создание агента сразу задаёт активные сессию и задачу (день 11)."""
    info = create_agent(client)

    assert len(info["session_id"]) == 8
    assert info["task_id"] == "default"
    listed = client.get("/agents").json()[0]
    assert (listed["session_id"], listed["task_id"]) == (
        info["session_id"], info["task_id"],
    )


def test_short_term_endpoints_roundtrip(client):
    """POST → GET → DELETE → пусто, с сохранением порядка реплик."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    first = client.post(f"/agents/{agent_id}/memory/short-term",
                        json={"role": "user", "content": "первый вопрос"})
    second = client.post(f"/agents/{agent_id}/memory/short-term",
                         json={"role": "assistant", "content": "первый ответ"})

    assert first.status_code == second.status_code == 201
    assert first.json()["session_id"] == info["session_id"]
    assert first.json()["created_at"]

    body = client.get(f"/agents/{agent_id}/memory/short-term").json()
    assert [m["content"] for m in body["messages"]] == [
        "первый вопрос", "первый ответ",
    ]
    assert body["session_id"] == info["session_id"]

    deleted = client.delete(f"/agents/{agent_id}/memory/short-term").json()
    assert deleted["deleted"] == 2
    assert client.get(f"/agents/{agent_id}/memory/short-term").json()["messages"] == []


def test_short_term_rejects_unknown_role_and_limit_bounds(client):
    """Роль и размер страницы валидируются: 422 вне контракта."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    assert client.post(f"/agents/{agent_id}/memory/short-term",
                       json={"role": "robot", "content": "текст"}).status_code == 422
    assert client.get(f"/agents/{agent_id}/memory/short-term",
                      params={"limit": 0}).status_code == 422
    assert client.get(f"/agents/{agent_id}/memory/short-term",
                      params={"limit": 501}).status_code == 422


def test_short_term_limit_returns_tail(client):
    """GET отдаёт последние limit реплик сессии (в хронологическом порядке)."""
    info = create_agent(client)
    agent_id = info["agent_id"]
    for index in range(1, 5):
        client.post(f"/agents/{agent_id}/memory/short-term",
                    json={"role": "user", "content": f"реплика {index}"})

    body = client.get(f"/agents/{agent_id}/memory/short-term",
                      params={"limit": 2}).json()

    assert [m["content"] for m in body["messages"]] == ["реплика 3", "реплика 4"]


def test_working_endpoints_upsert_and_switch_task(client):
    """Рабочая память: upsert по ключу и переключение активной задачи."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    created = client.post(f"/agents/{agent_id}/memory/working",
                          json={"key": "цель", "value": "портал"})
    assert created.status_code == 201
    assert created.json()["task_id"] == "default"

    updated = client.post(f"/agents/{agent_id}/memory/working",
                          json={"key": "цель", "value": "лендинг"}).json()
    assert updated["id"] == created.json()["id"]

    body = client.get(f"/agents/{agent_id}/memory/working").json()
    assert [e["value"] for e in body["entries"]] == ["лендинг"]
    assert body["tasks"] == ["default"]

    switched = client.put(f"/agents/{agent_id}/memory/task",
                          json={"task_id": "tz-portal"})
    assert switched.status_code == 200
    assert switched.json() == {"agent_id": agent_id, "task_id": "tz-portal",
                               "entries": 0}
    assert client.get(f"/agents/{agent_id}").json()["task_id"] == "tz-portal"

    client.post(f"/agents/{agent_id}/memory/working",
                json={"key": "срок", "value": "3 месяца"})
    in_task = client.get(f"/agents/{agent_id}/memory/working").json()
    assert [e["key"] for e in in_task["entries"]] == ["срок"]
    assert in_task["tasks"] == ["default", "tz-portal"]

    # Возврат к первой задаче: её запись на месте, вторая не видна.
    client.put(f"/agents/{agent_id}/memory/task", json={"task_id": "default"})
    back = client.get(f"/agents/{agent_id}/memory/working").json()
    assert [e["value"] for e in back["entries"]] == ["лендинг"]


def test_working_entry_writes_to_explicit_task(client):
    """task_id в теле POST пишет запись в указанную задачу, не переключая её."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    entry = client.post(f"/agents/{agent_id}/memory/working",
                        json={"key": "бюджет", "value": "пять тысяч",
                              "task_id": "side"}).json()

    assert entry["task_id"] == "side"
    assert client.get(f"/agents/{agent_id}").json()["task_id"] == "default"
    assert client.get(f"/agents/{agent_id}/memory/working").json()["entries"] == []


def test_long_term_endpoints_crud_and_delete_404(client):
    """CRUD долговременной памяти: upsert, фильтр по категории, удаление."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    created = client.post(f"/agents/{agent_id}/memory/long-term", json={
        "category": "preference", "key": "язык_интерфейса",
        "value": "русский", "confidence": 0.95,
    })
    assert created.status_code == 201
    entry_id = created.json()["id"]

    client.post(f"/agents/{agent_id}/memory/long-term", json={
        "category": "decision", "key": "бд", "value": "PostgreSQL",
        "confidence": 0.8,
    })
    updated = client.post(f"/agents/{agent_id}/memory/long-term", json={
        "category": "preference", "key": "язык_интерфейса",
        "value": "русский", "confidence": 0.7,
    }).json()
    assert updated["id"] == entry_id  # та же пара (category, key) — та же запись

    body = client.get(f"/agents/{agent_id}/memory/long-term").json()
    assert [e["key"] for e in body["entries"]] == ["бд", "язык_интерфейса"]
    assert body["categories"] == ["profile", "preference", "decision", "knowledge"]
    assert body["category"] is None

    filtered = client.get(f"/agents/{agent_id}/memory/long-term",
                          params={"category": "decision"}).json()
    assert [e["key"] for e in filtered["entries"]] == ["бд"]
    assert filtered["category"] == "decision"

    deleted = client.delete(f"/agents/{agent_id}/memory/long-term/{entry_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "agent_id": agent_id,
                              "entry_id": entry_id}
    assert [e["key"] for e in
            client.get(f"/agents/{agent_id}/memory/long-term").json()["entries"]] == ["бд"]

    missing = client.delete(f"/agents/{agent_id}/memory/long-term/{entry_id}")
    assert missing.status_code == 404
    assert "не найдена" in missing.json()["detail"]


def test_long_term_invalid_category_returns_422(client):
    """Неизвестная категория — ошибка валидации, а не запись в БД."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    response = client.post(f"/agents/{agent_id}/memory/long-term", json={
        "category": "unknown", "key": "ключ", "value": "значение",
    })

    assert response.status_code == 422
    assert client.get(f"/agents/{agent_id}/memory/long-term").json()["entries"] == []


def test_confidence_out_of_range_returns_422(client):
    """Уверенность вне [0, 1] отклоняется."""
    info = create_agent(client)
    agent_id = info["agent_id"]

    for confidence in (1.5, -0.1):
        response = client.post(f"/agents/{agent_id}/memory/long-term", json={
            "category": "profile", "key": "роль", "value": "аналитик",
            "confidence": confidence,
        })
        assert response.status_code == 422, confidence


def test_task_endpoint_rejects_blank_task_id(client):
    """Пустой task_id ловится Pydantic (min_length=1)."""
    info = create_agent(client)

    response = client.put(f"/agents/{info['agent_id']}/memory/task",
                          json={"task_id": ""})

    assert response.status_code == 422


def test_memory_endpoints_unknown_agent_returns_404(client):
    """Все десять эндпоинтов памяти отвечают 404 на неизвестного агента."""
    calls = [
        ("post", "/agents/nope/memory/short-term",
         {"json": {"role": "user", "content": "текст"}}),
        ("get", "/agents/nope/memory/short-term", {}),
        ("delete", "/agents/nope/memory/short-term", {}),
        ("post", "/agents/nope/memory/working", {"json": {"key": "к", "value": "з"}}),
        ("get", "/agents/nope/memory/working", {}),
        ("post", "/agents/nope/memory/long-term",
         {"json": {"category": "profile", "key": "к", "value": "з"}}),
        ("get", "/agents/nope/memory/long-term", {}),
        ("delete", "/agents/nope/memory/long-term/1", {}),
        ("post", "/agents/nope/memory/session", {}),
        ("put", "/agents/nope/memory/task", {"json": {"task_id": "t"}}),
    ]
    for method, path, kwargs in calls:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404, path


def test_generate_returns_memory_info(client):
    """Ответ генерации содержит разбивку токенов по трём слоям памяти."""
    info = create_agent(client)
    agent_id = info["agent_id"]
    client.post(f"/agents/{agent_id}/memory/working",
                json={"key": "цель", "value": "портал для ТЗ"})
    client.post(f"/agents/{agent_id}/memory/long-term", json={
        "category": "knowledge", "key": "стек_команды",
        "value": "Python 3.14 + FastAPI", "confidence": 0.7,
    })

    body = client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": "какой у нас стек команд?"}).json()

    assert body["status"] == "ok"
    memory = body["memory"]
    assert memory["session_id"] == info["session_id"]
    assert memory["task_id"] == "default"
    assert [layer["layer"] for layer in memory["layers"]] == [
        "short_term", "working", "long_term",
    ]
    assert memory["total_tokens"] == (
        memory["short_term_tokens"] + memory["working_tokens"]
        + memory["long_term_tokens"]
    )
    assert memory["working_tokens"] > 0
    assert memory["long_term_tokens"] > 0
    assert "стек" in memory["keywords"]


def test_new_session_endpoint_clears_short_term(client):
    """POST /memory/session очищает диалог, сохраняя рабочую и долговременную."""
    info = create_agent(client)
    agent_id = info["agent_id"]
    for prompt in ("первый", "второй"):
        assert client.post(f"/agents/{agent_id}/generate",
                           json={"prompt": prompt}).status_code == 200
    client.post(f"/agents/{agent_id}/memory/working",
                json={"key": "цель", "value": "портал"})
    client.post(f"/agents/{agent_id}/memory/long-term", json={
        "category": "profile", "key": "роль_пользователя", "value": "аналитик",
    })

    body = client.post(f"/agents/{agent_id}/memory/session").json()

    assert body["deleted_messages"] == 4
    assert body["previous_session_id"] == info["session_id"]
    assert body["session_id"] != info["session_id"]
    assert client.get(f"/agents/{agent_id}/history").json() == []
    assert client.get(f"/agents/{agent_id}").json()["session_id"] == body["session_id"]
    assert [e["value"] for e in
            client.get(f"/agents/{agent_id}/memory/working").json()["entries"]] == [
        "портал",
    ]
    assert [e["key"] for e in
            client.get(f"/agents/{agent_id}/memory/long-term").json()["entries"]] == [
        "роль_пользователя",
    ]


def test_root_lists_memory_endpoints(client):
    """Корневая точка перечисляет эндпоинты слоёв памяти."""
    root = client.get("/").json()

    for path in (
        "POST /agents/{agent_id}/memory/short-term",
        "DELETE /agents/{agent_id}/memory/short-term",
        "GET /agents/{agent_id}/memory/working",
        "POST /agents/{agent_id}/memory/long-term",
        "DELETE /agents/{agent_id}/memory/long-term/{entry_id}",
        "POST /agents/{agent_id}/memory/session",
        "PUT /agents/{agent_id}/memory/task",
    ):
        assert path in root["endpoints"]
    assert "memory" in root
