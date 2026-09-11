"""Тесты API дня 9 (FastAPI TestClient).

Проверяются контракты эндпоинтов: коды ответов, форма тел, поведение при
неизвестном agent_id и — главное — что новые эндпоинты сжатия работают без
реальных запросов к DeepSeek (сравнение режимов считает токены и без ключа,
суммаризация без ключа деградирует в отчёт с ошибкой, а не в 500).
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

    # Менеджер-синглтон приложения подменяем на изолированный (своя БД).
    manager = AgentManager(session_factory=factory)
    monkeypatch.setattr(database, "SessionLocal", factory)
    import backend.main as main
    monkeypatch.setattr(main, "get_manager", lambda: manager)

    # Клиент DeepSeek: фейк подставляется каждому созданному агенту.
    from backend.agent import Agent
    fake = FakeClient()
    monkeypatch.setattr(Agent, "_make_client", lambda self: fake)

    with TestClient(main.app) as test_client:
        test_client.manager = manager
        test_client.fake = fake
        yield test_client


def create_agent(client, **overrides):
    """Создаёт агента через API и возвращает JSON-ответ."""
    payload = {
        "name": "Агент API",
        "model": "deepseek-chat",
        "temperature": 0.5,
        "system_prompt": "Ты — тестовый ассистент.",
        "max_tokens": 512,
        "summary_enabled": True,
        "keep_last_messages": 2,
        "summarize_every": 2,
    }
    payload.update(overrides)
    response = client.post("/agents", json=payload)
    assert response.status_code == 201
    return response.json()


def seed_via_api(client, agent_id, turns=4):
    """Наполняет диалог через /generate (клиент DeepSeek подменён фейком).

    Реплики намеренно длинные (как в реальном диалоге): сжатие экономит токены
    только когда конспект дешевле заменяемых им реплик.
    """
    detail = ("Разбираем управление контекстом: конспект заменяет старые реплики, "
              "последние сообщения уходят как есть, экономию считаем по tiktoken. ")
    for index in range(turns):
        response = client.post(
            f"/agents/{agent_id}/generate",
            json={"prompt": f"Вопрос номер {index}. " + detail * 8},
        )
        assert response.status_code == 200
    return response.json()


def test_create_and_read_agent(client):
    """Создание возвращает настройки сжатия, а GET их же отдаёт."""
    info = create_agent(client, keep_last_messages=4, summarize_every=6)

    assert info["summary_enabled"] is True
    assert info["keep_last_messages"] == 4
    assert info["summarize_every"] == 6
    assert info["summary_count"] == 0

    fetched = client.get(f"/agents/{info['agent_id']}").json()
    assert fetched["keep_last_messages"] == 4
    assert fetched["summarize_every"] == 6


def test_create_agent_validates_compression_settings(client):
    """Некорректные настройки сжатия отклоняются с 422."""
    response = client.post("/agents", json={"name": "Плохой",
                                            "keep_last_messages": 0})
    assert response.status_code == 422
    response = client.post("/agents", json={"name": "Плохой",
                                            "summarize_every": 999})
    assert response.status_code == 422


def test_patch_toggles_compression_on_live_agent(client):
    """PATCH переключает сжатие, не теряя диалог."""
    info = create_agent(client)
    seed_via_api(client, info["agent_id"], turns=2)
    before = len(client.get(f"/agents/{info['agent_id']}/history").json())
    assert before == 4

    patched = client.patch(f"/agents/{info['agent_id']}",
                           json={"summary_enabled": False,
                                 "keep_last_messages": 8}).json()

    assert patched["summary_enabled"] is False
    assert patched["keep_last_messages"] == 8
    assert len(client.get(f"/agents/{info['agent_id']}/history").json()) == before


def test_generate_reports_compression_block(client):
    """Ответ генерации содержит блок сжатия и состояние FSM."""
    info = create_agent(client)
    record = seed_via_api(client, info["agent_id"], turns=1)

    compression = record["context"]["compression"]
    assert compression["enabled"] is True
    assert compression["full_context_tokens"] >= compression["sent_context_tokens"]
    assert compression["saved_tokens"] >= 0
    assert record["context"]["state"] in (
        "idle", "tracking", "summary_pending", "summarizing", "error"
    )


def test_generate_creates_summary_and_savings(client):
    """После серии ходов появляется конспект, а метрики показывают экономию."""
    info = create_agent(client, keep_last_messages=2, summarize_every=2)
    seed_via_api(client, info["agent_id"], turns=5)

    summary = client.get(f"/agents/{info['agent_id']}/summary").json()
    assert summary["summary_count"] >= 1
    assert summary["current"] is not None
    assert summary["covered_messages"] >= 4
    assert summary["message_count"] == 10

    usage = client.get(f"/agents/{info['agent_id']}/usage").json()
    assert usage["compressed_requests"] >= 1
    assert usage["total_saved_tokens"] > 0
    assert usage["total_net_saved_tokens"] == summary["net_saved_tokens"]
    assert usage["total_net_saved_tokens"] < usage["total_saved_tokens"]


def test_history_marks_summarized_messages(client):
    """История помечает покрытые конспектом реплики флагом summarized."""
    info = create_agent(client, keep_last_messages=2, summarize_every=2)
    seed_via_api(client, info["agent_id"], turns=4)

    history = client.get(f"/agents/{info['agent_id']}/history").json()
    assert len(history) == 8
    assert any(row["summarized"] for row in history)
    assert all(row["summarized"] is False for row in history[-2:])


def test_summarize_endpoint_reports_noop(client):
    """Принудительное сжатие при коротком диалоге — отчёт created:false, не ошибка."""
    info = create_agent(client, keep_last_messages=4, summarize_every=10)
    seed_via_api(client, info["agent_id"], turns=1)

    response = client.post(f"/agents/{info['agent_id']}/summarize",
                           json={"force": False})

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["attempted"] is False
    assert body["summary"]["summary_count"] == 0


def test_summarize_endpoint_forces_compression(client):
    """force=True сжимает ниже порога, оставляя последние keep_last реплик."""
    info = create_agent(client, keep_last_messages=2, summarize_every=10)
    seed_via_api(client, info["agent_id"], turns=3)

    body = client.post(f"/agents/{info['agent_id']}/summarize",
                       json={"force": True}).json()

    assert body["created"] is True
    assert body["summarized_messages"] == 4
    assert body["state"] == "tracking"
    assert body["summary"]["current"]["content"]
    assert body["summary"]["uncovered_messages"] == 2


def test_summarize_endpoint_disabled_agent(client):
    """Выключенное сжатие: отчёт с причиной, конспектов нет."""
    info = create_agent(client, summary_enabled=False)
    seed_via_api(client, info["agent_id"], turns=3)

    body = client.post(f"/agents/{info['agent_id']}/summarize",
                       json={"force": True}).json()

    assert body["created"] is False
    assert "выключено" in body["error"]
    assert body["summary"]["summary_count"] == 0


def test_compare_endpoint_without_api(client):
    """Сравнение без call_api не делает вызовов и показывает экономию."""
    info = create_agent(client, keep_last_messages=2, summarize_every=2)
    seed_via_api(client, info["agent_id"], turns=4)
    client.post(f"/agents/{info['agent_id']}/summarize", json={"force": True})
    calls_before = len(client.fake.generate_calls)

    body = client.post(f"/agents/{info['agent_id']}/compare",
                       json={"prompt": "Сравни режимы", "call_api": False}).json()

    assert body["call_api"] is False
    assert body["saved_tokens"] > 0
    assert body["compressed"]["sent_context_tokens"] < \
        body["full"]["sent_context_tokens"]
    assert len(client.fake.generate_calls) == calls_before


def test_compare_endpoint_with_api(client):
    """Сравнение с call_api делает два вызова и возвращает оба ответа."""
    info = create_agent(client, keep_last_messages=2, summarize_every=2)
    seed_via_api(client, info["agent_id"], turns=4)
    calls_before = len(client.fake.generate_calls)

    body = client.post(f"/agents/{info['agent_id']}/compare",
                       json={"prompt": "Сравни ответы", "call_api": True}).json()

    assert body["full"]["response"] == "Ответ ассистента"
    assert body["compressed"]["response"] == "Ответ ассистента"
    assert len(client.fake.generate_calls) == calls_before + 2
    # История не изменилась: compare не сохраняет реплики.
    assert len(client.get(f"/agents/{info['agent_id']}/history").json()) == 8


def test_clear_history_resets_summaries_and_usage(client):
    """Очистка истории сбрасывает конспекты и счётчик экономии."""
    info = create_agent(client, keep_last_messages=2, summarize_every=2)
    seed_via_api(client, info["agent_id"], turns=4)
    assert client.get(f"/agents/{info['agent_id']}/summary").json()["summary_count"] > 0

    body = client.delete(f"/agents/{info['agent_id']}/history").json()

    assert body["message_count"] == 0
    summary = client.get(f"/agents/{info['agent_id']}/summary").json()
    assert summary["summary_count"] == 0
    assert summary["message_count"] == 0
    usage = client.get(f"/agents/{info['agent_id']}/usage").json()
    assert usage["total_requests"] == 0
    assert usage["total_saved_tokens"] == 0


def test_generate_error_without_api_key(client, monkeypatch):
    """Без ключа генерация — 502 со структурированной ошибкой, история цела."""
    from backend.agent import Agent, AgentError

    def no_key(self):
        raise AgentError("Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day9/.env")

    monkeypatch.setattr(Agent, "_make_client", no_key)
    info = create_agent(client)

    response = client.post(f"/agents/{info['agent_id']}/generate",
                           json={"prompt": "Вопрос без ключа"})

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "error"
    assert "Ключ API не задан" in body["error"]
    assert body["messages"] == []
    # Ход не сохранился: и реплик, и метрик — ноль.
    usage = client.get(f"/agents/{info['agent_id']}/usage").json()
    assert usage["total_requests"] == 0


def test_unknown_agent_returns_404(client):
    """Неизвестный agent_id — 404 на всех «агентских» эндпоинтах."""
    paths = [
        ("get", "/agents/nope"),
        ("get", "/agents/nope/history"),
        ("get", "/agents/nope/summary"),
        ("get", "/agents/nope/usage"),
        ("get", "/agents/nope/usage/graph"),
        ("delete", "/agents/nope"),
    ]
    for method, path in paths:
        response = getattr(client, method)(path)
        assert response.status_code == 404, path
    assert client.post("/agents/nope/generate",
                       json={"prompt": "привет"}).status_code == 404
    assert client.post("/agents/nope/summarize", json={}).status_code == 404
    assert client.post("/agents/nope/compare",
                       json={"prompt": "привет"}).status_code == 404
    assert client.patch("/agents/nope", json={"name": "новое"}).status_code == 404


def test_delete_agent(client):
    """Удаление агента возвращает статус, повторное — 404."""
    info = create_agent(client)

    assert client.delete(f"/agents/{info['agent_id']}").json()["status"] == "deleted"
    assert client.delete(f"/agents/{info['agent_id']}").status_code == 404


def test_agents_list_and_root(client):
    """Список агентов и корневая точка описывают все эндпоинты дня 9."""
    info = create_agent(client)

    agents = client.get("/agents").json()
    assert [row["agent_id"] for row in agents] == [info["agent_id"]]
    assert agents[0]["summary_enabled"] is True

    root = client.get("/").json()
    assert "POST /agents/{agent_id}/compare" in root["endpoints"]
    assert "GET /agents/{agent_id}/summary" in root["endpoints"]


def test_usage_graph_exposes_compression_columns(client):
    """Записи /usage/graph содержат колонки сжатия для графика экономии."""
    info = create_agent(client, keep_last_messages=2, summarize_every=2)
    seed_via_api(client, info["agent_id"], turns=4)

    rows = client.get(f"/agents/{info['agent_id']}/usage/graph").json()

    assert rows
    row = rows[-1]
    assert set(row) >= {
        "mode", "full_context_tokens", "sent_context_tokens", "saved_tokens",
        "summary_tokens", "summarized_messages", "summary_used",
    }
    assert row["mode"] in ("full", "compressed")
