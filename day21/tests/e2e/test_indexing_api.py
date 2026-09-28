"""Тесты эндпоинтов индексации (день 21).

Проверяется контракт ``/indexing``: запуск прогона и демо-сценария, прогресс,
статистика, поиск, примеры чанков, история, отчёт и очистка. Отдельно — контракт
ошибок: 400 на неизвестную стратегию и на пустой запрос, 409 на поиск по
непостроенному индексу, 404 на неизвестный запуск, 422 на непрошедшие проверку
параметры. И поле ``indexing`` ответа генерации — то, ради чего день делался: агент
находит фрагменты документов и добавляет их в системный промпт.

Эмбеддер фейковый (``indexing_fakes``): настоящая модель весит сотни мегабайт и
требует сети, а тест проверяет контракт API, а не качество эмбеддингов.
"""
import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.services.document_loader import DocumentLoader
from backend.services.index_service import IndexService
from backend.services.indexing_service import IndexingService
from backend.storage import database
from backend.storage.chunk_store import ChunkStore
from backend.storage.database import init_db, make_engine, make_session_factory
from backend.storage.index_run_store import IndexRunStore

from indexing_fakes import FakeEmbedder, make_documents
from support import FakeClient

#: Реплика с признаком оркестрации: такой ход шаг поиска по индексу не делает.
ORCHESTRATION_PROMPT = "выполни оркестрацию по серверам и сохрани в базу"

#: Обычная реплика: по ней агент ищет фрагменты в индексе документов.
PLAIN_PROMPT = "расскажи про чанкинг и покрытие документов"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с изолированной БД, фейковым эмбеддером и службой индексации."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'indexing.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    import backend.api.main as main

    store = ChunkStore(session_factory=factory)
    index_service = IndexService(embedder=FakeEmbedder(), store=store,
                                index_dir=tmp_path / "index")
    make_documents(tmp_path / "documents")
    loader = DocumentLoader(documents_dir=tmp_path / "documents", sources=())
    run_store = IndexRunStore(session_factory=factory)
    service = IndexingService(index_service=index_service, loader=loader,
                              run_store=run_store)
    manager = AgentManager(session_factory=factory, indexing_service=service)
    monkeypatch.setattr(main, "get_manager", lambda: manager)
    monkeypatch.setattr(main, "get_indexing_service", lambda: service)
    monkeypatch.setattr(main, "get_index_service", lambda: index_service)
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient())

    instance = TestClient(main.app)
    instance.service = service
    instance.index_service = index_service
    instance.index_run_store = run_store
    return instance


def _demo(client, background=False):
    """Запускает демо-сценарий через API и требует успешного ответа."""
    response = client.post("/indexing/demo", json={"background": background})
    assert response.status_code == 200, response.text
    return response.json()


# ---------- запуск ----------
def test_demo_run_is_synchronous_and_complete(client):
    """Синхронный демо-прогон отдаёт статус completed и метрики сравнения."""
    body = _demo(client)
    assert body["background"] is False
    assert body["status"] == "completed"
    assert body["strategy"] == "demo"
    assert body["error"] is None
    assert len(body["metrics"]["comparison"]) > 1
    assert len(body["metrics"]["queries"]) == 5


def test_demo_run_builds_both_indexes(client):
    """После демо-прогона статистика показывает чанки обеих стратегий."""
    _demo(client)
    stats = client.get("/indexing/stats").json()
    assert stats["fixed"]["chunks"] > 0
    assert stats["structural"]["chunks"] > 0
    assert stats["structural"]["with_section"] > 0
    assert stats["fixed"]["index_file"].endswith("fixed.index")


def test_single_strategy_run(client):
    """Прогон одной стратегии оставляет её индекс и не пишет метрик сравнения."""
    response = client.post("/indexing/run",
                           json={"strategy": "fixed", "background": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed" and body["strategy"] == "fixed"
    assert "comparison" not in body["metrics"]
    stats = client.get("/indexing/stats").json()
    assert stats["fixed"]["chunks"] > 0 and stats["structural"]["chunks"] == 0


def test_run_rejects_unknown_strategy(client):
    """Неизвестная стратегия — 400 с перечнем допустимых."""
    response = client.post("/indexing/run", json={"strategy": "окно"})
    assert response.status_code == 400
    assert "structural" in response.json()["detail"]


def test_run_validates_body(client):
    """Невалидное тело — 422 (Pydantic), как у остальных эндпоинтов."""
    assert client.post("/indexing/run", json={"background": "нет"}).status_code == 422


def test_background_demo_is_pollable(client):
    """Фоновый прогон отвечает сразу, а прогресс читается через ``/status``."""
    body = _demo(client, background=True)
    assert body["background"] is True and body["metrics"] is None
    status = client.get("/indexing/status").json()["run"]
    assert status["id"] == body["run_id"]
    assert status["documents_total"] >= 0


# ---------- прогресс и история ----------
def test_status_without_runs(client):
    """До первого прогона ``/status`` отдаёт ``run: null`` (интерфейс не падает)."""
    assert client.get("/indexing/status").json() == {"run": None}


def test_stats_before_any_run(client):
    """Статистика доступна сразу: обе стратегии с нулями, а не 404."""
    body = client.get("/indexing/stats").json()
    assert body["fixed"]["chunks"] == 0 and body["structural"]["chunks"] == 0
    assert body["fixed"]["histogram"]


def test_runs_history(client):
    """История запусков идёт от свежих к старым и считает их."""
    first = _demo(client)["run_id"]
    second = client.post("/indexing/run",
                         json={"strategy": "structural", "background": False}).json()
    body = client.get("/indexing/runs").json()
    assert [run["id"] for run in body["runs"]] == [second["run_id"], first]
    assert body["count"] == 2
    assert client.get("/indexing/runs", params={"limit": 1}).json()["count"] == 1


def test_run_report_returns_metrics(client):
    """Отчёт о запуске отдаёт строку запуска и метрики (то, что показывает интерфейс)."""
    run_id = _demo(client)["run_id"]
    body = client.get(f"/indexing/runs/{run_id}").json()
    assert body["run"]["id"] == run_id and body["run"]["status"] == "completed"
    assert body["metrics"]["comparison"]
    assert body["metrics"]["documents"]
    assert all(entry["source"] for entry in body["metrics"]["documents"])


def test_unknown_run_is_not_found(client):
    """Неизвестный запуск — 404."""
    assert client.get("/indexing/runs/4242").status_code == 404


# ---------- поиск и примеры чанков ----------
def test_search_on_empty_index_is_conflict(client):
    """Поиск до индексации — 409: индекса нет, а не «ничего не нашлось»."""
    response = client.get("/indexing/search", params={"query": "чанкинг"})
    assert response.status_code == 409
    assert "пуст" in response.json()["detail"]


def test_empty_query_is_rejected(client):
    """Пустой запрос — 400 даже при построенном индексе."""
    _demo(client)
    assert client.get("/indexing/search", params={"query": "   "}).status_code == 400


def test_search_returns_hits_with_metadata(client):
    """Поиск отдаёт попадания с метаданными чанка и убывающей оценкой."""
    _demo(client)
    body = client.get("/indexing/search",
                      params={"query": "структурный чанкинг секции", "top_k": 3,
                              "strategy": "structural"}).json()
    assert body["query"] == "структурный чанкинг секции"
    assert body["strategy"] == "structural" and body["top_k"] == 3
    assert body["count"] == len(body["results"]) == 3
    assert [hit["rank"] for hit in body["results"]] == [1, 2, 3]
    assert [hit["score"] for hit in body["results"]] == sorted(
        [hit["score"] for hit in body["results"]], reverse=True)
    for hit in body["results"]:
        assert hit["chunk_id"] and hit["source"] and hit["content"]


def test_search_validates_top_k(client):
    """``top_k`` вне границ — 422 (проверка параметра, а не молчаливый зажим)."""
    _demo(client)
    assert client.get("/indexing/search",
                      params={"query": "x", "top_k": 0}).status_code == 422
    assert client.get("/indexing/search",
                      params={"query": "x", "top_k": 500}).status_code == 422


def test_search_rejects_unknown_strategy(client):
    """Неизвестная стратегия поиска — 400."""
    _demo(client)
    assert client.get("/indexing/search",
                      params={"query": "x", "strategy": "окно"}).status_code == 400


def test_chunks_endpoint(client):
    """Примеры чанков приходят стратегией, с ограничением и текстом."""
    _demo(client)
    body = client.get("/indexing/chunks",
                      params={"strategy": "structural", "limit": 2}).json()
    assert body["strategy"] == "structural" and body["count"] == 2
    for chunk in body["chunks"]:
        assert chunk["strategy"] == "structural"
        assert chunk["chunk_id"] and chunk["content"]
        assert chunk["embedding_id"] == chunk["id"]


def test_chunks_rejects_unknown_strategy(client):
    """Примеры чанков для неизвестной стратегии — 400."""
    assert client.get("/indexing/chunks", params={"strategy": "окно"}).status_code == 400


# ---------- очистка ----------
def test_clear_removes_one_strategy(client):
    """Очистка одной стратегии оставляет вторую рабочей, а её поиск — 409."""
    _demo(client)
    body = client.post("/indexing/clear", json={"strategy": "fixed"}).json()
    assert body["removed"]["fixed"] > 0
    assert client.get("/indexing/search",
                      params={"query": "чанкинг", "strategy": "fixed"}).status_code == 409
    assert client.get("/indexing/search",
                      params={"query": "чанкинг", "strategy": "structural"}).status_code == 200


def test_clear_all(client):
    """``all`` очищает обе стратегии сразу."""
    _demo(client)
    body = client.post("/indexing/clear", json={"strategy": "all"}).json()
    assert set(body["removed"]) == {"fixed", "structural"}
    assert client.get("/indexing/stats").json()["fixed"]["chunks"] == 0


def test_clear_rejects_unknown_strategy(client):
    """Очистка неизвестной стратегии — 400."""
    assert client.post("/indexing/clear", json={"strategy": "окно"}).status_code == 400


# ---------- шаг агента ----------
def test_generate_reports_index_step(client):
    """При построенном индексе ход агента ищет фрагменты и сообщает об этом."""
    _demo(client)
    agent_id = client.post("/agents", json={"name": "Агент с индексом"}).json()["agent_id"]
    body = client.post(f"/agents/{agent_id}/generate",
                      json={"prompt": PLAIN_PROMPT}).json()
    report = body["indexing"]
    assert report["detected"] is True
    assert report["strategy"] == "structural"
    assert report["hits"] == 3
    assert report["used_in_prompt"] is True and report["added_tokens"] > 0
    assert report["sources"] and report["error"] is None
    assert "индекса документов" in body["system_prompt"]


def test_generate_without_index_skips_step(client):
    """Пока индекс не построен, поле ``indexing`` заполнено, но поиска не было."""
    agent_id = client.post("/agents", json={"name": "Агент без индекса"}).json()["agent_id"]
    body = client.post(f"/agents/{agent_id}/generate",
                      json={"prompt": PLAIN_PROMPT}).json()
    assert body["indexing"]["detected"] is False
    assert body["indexing"]["hits"] == 0
    assert body["indexing"]["used_in_prompt"] is False


def test_generate_keeps_one_automation_per_turn(client):
    """Реплика, занятая оркестрацией, поиск по индексу не делает."""
    _demo(client)
    agent_id = client.post("/agents", json={"name": "Агент оркестрации"}).json()["agent_id"]
    body = client.post(f"/agents/{agent_id}/generate",
                      json={"prompt": ORCHESTRATION_PROMPT}).json()
    assert body["orchestration"]["detected"] is True
    assert body["indexing"]["detected"] is False


# ---------- справочник ----------
def test_root_lists_indexing(client):
    """Корневая точка перечисляет эндпоинты индексации."""
    body = client.get("/").json()
    assert "/indexing/demo" in body["indexing"]
    assert "POST /indexing/clear" in body["endpoints"]
    assert body["name"].endswith("День 21")
