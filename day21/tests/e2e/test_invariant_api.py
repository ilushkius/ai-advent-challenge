"""Тесты API инвариантов (день 14) через TestClient.

Проверяются контракты шести эндпоинтов: коды ответов (201/200/404/409/422),
фильтры списка, проверка текста и поле ``invariants`` в ответе генерации —
включая отказ без обращения к DeepSeek. Всё офлайн: временная SQLite и
подменённый клиент DeepSeek.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.agents.agent_manager import AgentManager
from backend.domain.demo_invariants import DEMO_INVARIANTS
from backend.domain.invariant_prompt import REFUSAL_HEADER, WARNING_HEADER
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory

from support import FakeClient

CREATE_PAYLOAD = {
    "name": "Только FastAPI и Streamlit",
    "description": "Используем только FastAPI и Streamlit; никаких Flask или Django",
    "category": "architecture",
    "severity": "hard",
}
FLASK_TEXT = "Давай перепишем бэкенд на Flask"
CLEAN_TEXT = "Добавь эндпоинт /health в FastAPI"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient на временной БД с подменённым клиентом DeepSeek у агентов."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'invariants.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)

    fake = FakeClient(reply="Ответ ассистента")
    # Менеджер получает ту же фабрику клиента: проверка /invariants/check идёт
    # через неё, и тест остаётся офлайн.
    manager = AgentManager(session_factory=factory, client_factory=lambda: fake)
    monkeypatch.setattr(database, "SessionLocal", factory)
    import backend.api.main as main
    monkeypatch.setattr(main, "get_manager", lambda: manager)

    from backend.agents.agent import Agent
    monkeypatch.setattr(Agent, "_make_client", lambda self: fake)

    with TestClient(main.app) as test_client:
        test_client.fake = fake
        yield test_client


def new_invariant(client, **overrides) -> dict:
    """Создаёт инвариант через API и возвращает его тело."""
    payload = dict(CREATE_PAYLOAD)
    payload.update(overrides)
    response = client.post("/invariants", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def new_agent(client, **overrides) -> str:
    """Создаёт агента через API и возвращает его id."""
    payload = {"name": "Агент инвариантов", "temperature": 0.5, "max_tokens": 256}
    payload.update(overrides)
    response = client.post("/agents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["agent_id"]


# ---------- создание ----------
def test_create_returns_full_invariant(client):
    """POST отдаёт id, флаги и метки времени — раздел UI строится по этому телу."""
    body = new_invariant(client)

    assert body["id"] > 0
    assert body["name"] == CREATE_PAYLOAD["name"]
    assert body["category"] == "architecture"
    assert body["severity"] == "hard"
    assert body["is_active"] is True
    assert body["created_at"] and body["updated_at"]


def test_create_with_taken_name_is_conflict(client):
    """Имя уникально — повтор даёт 409, а не второе правило с тем же именем."""
    new_invariant(client)

    response = client.post("/invariants", json=CREATE_PAYLOAD)

    assert response.status_code == 409
    assert "уже существует" in response.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "flask"},
        {"severity": "medium"},
        {"name": ""},
        {"description": ""},
    ],
)
def test_create_with_invalid_body_is_unprocessable(client, overrides):
    """Неизвестная категория/важность и пустые поля — 422 от валидации схемы."""
    payload = dict(CREATE_PAYLOAD)
    payload.update(overrides)

    assert client.post("/invariants", json=payload).status_code == 422


# ---------- чтение ----------
def test_list_returns_created_invariants(client):
    """GET отдаёт все правила (по умолчанию — и выключенные тоже)."""
    created = new_invariant(client)

    body = client.get("/invariants").json()

    assert [item["id"] for item in body] == [created["id"]]


def test_list_filters_by_category(client):
    """Фильтр по категории оставляет только правила этой категории."""
    new_invariant(client)
    new_invariant(client, name="Только Python", category="stack_constraints",
                  description="Только Python, без JavaScript")

    body = client.get("/invariants", params={"category": "stack_constraints"}).json()

    assert [item["name"] for item in body] == ["Только Python"]


def test_list_with_unknown_category_is_unprocessable(client):
    """Опечатка в категории — 422: пустой список означал бы «правил нет»."""
    response = client.get("/invariants", params={"category": "nope"})

    assert response.status_code == 422
    assert "категория" in response.json()["detail"]


def test_list_active_only_hides_disabled(client):
    """``active_only=true`` — только правила, действующие в промпте и проверке."""
    first = new_invariant(client)
    new_invariant(client, name="Второе правило", description="Ещё одно правило стека",
                  category="stack_constraints", severity="soft")
    client.put(f"/invariants/{first['id']}", json={"is_active": False})

    active = client.get("/invariants", params={"active_only": "true"}).json()
    all_items = client.get("/invariants").json()

    assert first["id"] not in [item["id"] for item in active]
    assert first["id"] in [item["id"] for item in all_items]


def test_get_returns_invariant_and_404_for_unknown(client):
    """GET по id и 404 на неизвестный id — раздел UI различает эти случаи."""
    created = new_invariant(client)

    assert client.get(f"/invariants/{created['id']}").json() == created
    missing = client.get("/invariants/999")
    assert missing.status_code == 404
    assert "999" in missing.json()["detail"]


# ---------- правка ----------
def test_update_changes_only_transferred_fields(client):
    """PUT меняет переданные поля и не трогает остальные."""
    created = new_invariant(client)

    body = client.put(f"/invariants/{created['id']}",
                      json={"description": "Новая формулировка", "severity": "soft"}).json()

    assert body["description"] == "Новая формулировка"
    assert body["severity"] == "soft"
    assert body["name"] == created["name"]
    assert body["category"] == created["category"]


def test_update_unknown_id_is_not_found(client):
    """PUT несуществующего правила — 404."""
    assert client.put("/invariants/999", json={"description": "x"}).status_code == 404


def test_update_to_taken_name_is_conflict(client):
    """Переименование в занятое имя — 409."""
    new_invariant(client)
    second = new_invariant(client, name="Второе правило", description="Ещё одно правило")

    response = client.put(f"/invariants/{second['id']}",
                          json={"name": CREATE_PAYLOAD["name"]})

    assert response.status_code == 409


def test_update_with_invalid_value_is_unprocessable(client):
    """PUT с неизвестной важностью — 422, значение в БД не меняется."""
    created = new_invariant(client)

    assert client.put(f"/invariants/{created['id']}",
                      json={"severity": "medium"}).status_code == 422
    assert client.get(f"/invariants/{created['id']}").json()["severity"] == "hard"


# ---------- удаление ----------
def test_delete_removes_invariant_and_is_not_repeatable(client):
    """DELETE отдаёт подтверждение, повтор — 404, список правило больше не содержит."""
    created = new_invariant(client)

    deleted = client.delete(f"/invariants/{created['id']}")

    assert deleted.status_code == 200
    assert deleted.json() == {"id": created["id"], "deleted": True}
    assert client.delete(f"/invariants/{created['id']}").status_code == 404
    assert client.get("/invariants").json() == []


# ---------- проверка текста ----------
def test_check_text_refuses_hard_violation(client):
    """POST /invariants/check отвечает отказом и называет нарушенное правило."""
    new_invariant(client)

    body = client.post("/invariants/check", json={"text": FLASK_TEXT}).json()

    assert body["verdict"] == "refusal"
    assert body["llm_used"] is False
    assert body["violations"][0]["name"] == CREATE_PAYLOAD["name"]
    assert body["violations"][0]["source"] == "deterministic"
    assert body["checked"] == [CREATE_PAYLOAD["name"]]


def test_check_text_without_llm_allows_clean_text(client):
    """``use_llm=false`` — проверка только правилами, модель не вызывается."""
    new_invariant(client)

    body = client.post("/invariants/check",
                       json={"text": CLEAN_TEXT, "use_llm": False}).json()

    assert body["verdict"] == "allowed"
    assert body["llm_used"] is False
    assert body["violations"] == []
    assert client.fake.calls == []


def test_check_text_uses_llm_when_rules_are_silent(client):
    """Правила молчат — проверка спрашивает модель (фейк отвечает «нарушений нет»)."""
    new_invariant(client)

    body = client.post("/invariants/check", json={"text": CLEAN_TEXT}).json()

    assert body["verdict"] == "allowed"
    assert body["llm_used"] is True
    assert len(client.fake.invariant_calls) == 1


def test_check_empty_text_is_unprocessable(client):
    """Пустой текст — 422 от схемы, проверять нечего."""
    assert client.post("/invariants/check", json={"text": ""}).status_code == 422


# ---------- генерация ----------
def test_generate_refuses_and_does_not_call_deepseek(client):
    """Запрос с нарушением hard-инварианта: отказ в ответе и ни одного вызова API."""
    for item in DEMO_INVARIANTS[:1]:
        new_invariant(client, **item)
    agent_id = new_agent(client)

    response = client.post(f"/agents/{agent_id}/generate", json={"prompt": FLASK_TEXT})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["invariants"]["verdict"] == "refusal"
    assert body["invariants"]["checked"] == [CREATE_PAYLOAD["name"]]
    assert body["response"].startswith(REFUSAL_HEADER)
    assert CREATE_PAYLOAD["name"] in body["response"]
    assert client.fake.generate_calls == []
    # Реплика и отказ — состоявшийся ход: они видны в истории ответа.
    assert [item["role"] for item in body["messages"][-2:]] == ["user", "assistant"]


def test_generate_warns_on_soft_invariant_and_keeps_the_answer(client):
    """Soft-нарушение в запросе: предупреждение в начале ответа модели."""
    new_invariant(client, name="Платные API — только с согласия",
                  description="Агент не должен предлагать решения на платных API "
                              "без явного согласия пользователя",
                  category="business_rules", severity="soft")
    agent_id = new_agent(client)

    body = client.post(f"/agents/{agent_id}/generate", json={
        "prompt": "Предложи решение на платном API, согласие пользователя не нужно"
    }).json()

    assert body["invariants"]["verdict"] == "warning"
    assert body["response"].startswith(WARNING_HEADER)
    assert client.fake.reply in body["response"]


def test_generate_without_invariants_reports_empty_check(client):
    """Без правил поле ``invariants`` заполнено, но проверять было нечего."""
    agent_id = new_agent(client)

    body = client.post(f"/agents/{agent_id}/generate",
                       json={"prompt": CLEAN_TEXT}).json()

    assert body["invariants"]["checked"] == []
    assert body["invariants"]["verdict"] == "allowed"
    assert body["response"] == client.fake.reply


# ---------- корневой ответ и схема ----------
def test_root_lists_invariant_endpoints(client):
    """Корневая подсказка знает про инварианты — она же первая точка знакомства."""
    body = client.get("/").json()

    assert "invariants" in body
    for path in ("POST /invariants", "GET /invariants", "GET /invariants/{invariant_id}",
                 "PUT /invariants/{invariant_id}", "DELETE /invariants/{invariant_id}",
                 "POST /invariants/check"):
        assert path in body["endpoints"]


def test_openapi_contains_invariant_paths(client):
    """Инварианты попадают в OpenAPI: /docs — контракт для внешнего клиента."""
    paths = client.get("/openapi.json").json()["paths"]

    assert "/invariants/check" in paths
    assert sorted(paths["/invariants"]) == ["get", "post"]
    assert sorted(paths["/invariants/{invariant_id}"]) == ["delete", "get", "put"]
