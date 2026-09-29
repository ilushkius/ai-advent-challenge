"""Тесты эндпоинтов режима RAG (день 22).

Проверяется контракт ``/rag``: ответ по корпусу с источниками и без них,
конфигурация режима, сравнение двух ответов и перевод отказов службы в статусы
(400 — пустой вопрос и незнакомая стратегия, 409 — непроиндексированный корпус,
502 — сбой вызова модели, когда откат тоже не удался). Модель подменена
заглушкой: через HTTP проверяется связка слоёв, а не сеть.
"""
import pytest
from fastapi.testclient import TestClient

from backend.domain.rag_mode import RAG_DEFAULT_STRATEGY, RAG_LLM_ATTEMPTS
from backend.services.rag_service import RAGService
from backend.storage import database

from support import FakeClient

#: Ровно те поля, которые видит интерфейс: текст фрагмента через API не уходит.
SOURCE_KEYS = {"source", "title", "section", "chunk_id", "score"}

QUESTION = "Чему равен CHARS_PER_PAGE?"


@pytest.fixture
def client(session_factory, rag_service, monkeypatch):
    """TestClient на временной БД с подменённой службой RAG."""
    monkeypatch.setattr(database, "SessionLocal", session_factory)

    import backend.api.main as main
    monkeypatch.setattr(main, "get_rag_service", lambda: rag_service)

    from backend.agents.agent import Agent
    monkeypatch.setattr(Agent, "_make_client", lambda self: FakeClient())

    with TestClient(main.app) as test_client:
        test_client.rag_service = rag_service
        yield test_client


def test_rag_query_returns_answer_with_sources(client):
    """Режим с RAG: ответ, использованные фрагменты и метрики контекста."""
    response = client.post("/rag/query", json={"question": QUESTION, "top_k": 3})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "rag" and body["answer"]
    assert body["question"] == QUESTION
    assert body["sources"] and len(body["sources"]) <= 3
    assert set(body["sources"][0]) == SOURCE_KEYS
    assert body["chunks_used"] == len(body["sources"])
    assert body["context_tokens"] > 0
    assert body["fallback"] is False and body["warning"] == ""
    assert body["grounding"]
    assert body["tokens"]["model"]


def test_rag_query_without_rag_returns_no_sources(client):
    """Переключатель выключен: тот же вопрос уходит модели без блока контекста."""
    response = client.post("/rag/query",
                           json={"question": QUESTION, "use_rag": False})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "no_rag"
    assert body["answer"]
    assert body["sources"] == [] and body["chunks_used"] == 0
    assert body["context_tokens"] == 0 and body["grounding"] == ""
    assert body["tokens"]["model"]


def test_rag_config_reports_corpus_and_limits(client):
    """Конфигурация режима: объём корпуса, чанки стратегий и лимиты."""
    response = client.get("/rag/config")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["corpus"]["documents"] == 2
    assert body["corpus"]["pages"] < body["corpus"]["min_pages"]
    assert body["chunks_total"] == sum(item["chunks"] for item in body["indexes"])
    assert body["chunks_total"] > 0
    assert body["default_strategy"] == "rag_corpus_structural"
    assert len(body["strategies"]) == 2
    assert body["top_k_default"] == 5 and body["top_k_max"] == 10
    assert body["context_max_tokens"] > 0 and body["chunk_max_chars"] > 0


def test_empty_question_is_bad_request(client):
    """Пустой вопрос — 400 с кодом причины, а не 422 схемы запроса."""
    response = client.post("/rag/query", json={"question": "   "})

    assert response.status_code == 400
    assert "Вопрос пуст" in response.json()["detail"]


def test_unknown_strategy_is_bad_request(client):
    """Стратегии вне корпуса нет: 400, поиск по умолчанию не подставляется."""
    response = client.post("/rag/query",
                           json={"question": QUESTION, "strategy": "fixed"})

    assert response.status_code == 400
    assert "fixed" in response.json()["detail"]


def test_real_strategy_name_passes_schema(client):
    """Имя стратегии корпуса (19 символов) схема не режет: 200 на обоих эндпоинтах."""
    for path in ("/rag/query", "/rag/compare"):
        response = client.post(path, json={"question": QUESTION,
                                           "strategy": RAG_DEFAULT_STRATEGY})

        assert response.status_code == 200, response.text


def test_empty_index_is_conflict(client, monkeypatch, rag_loader,
                                 empty_index_service, chunk_store, rag_client):
    """Непроиндексированный корпус — 409 с подсказкой о скриптах сборки."""
    import backend.api.main as main
    service = RAGService(index_service=empty_index_service, loader=rag_loader,
                         store=chunk_store, llm_client=rag_client,
                         sleep=lambda _seconds: None)
    monkeypatch.setattr(main, "get_rag_service", lambda: service)

    response = client.post("/rag/query", json={"question": QUESTION})

    assert response.status_code == 409
    assert "prepare_rag_corpus.py" in response.json()["detail"]


def test_model_failure_falls_back_over_api(client, rag_stub):
    """Сбой вызова с контекстом: 200, но ответ без RAG, пометка отката и источников нет."""
    rag_stub.error = RuntimeError("boom")
    rag_stub.error_times = RAG_LLM_ATTEMPTS

    response = client.post("/rag/query", json={"question": QUESTION})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fallback"] is True
    assert "boom" in body["warning"]
    assert body["mode"] == "rag" and body["answer"]
    assert body["sources"] == [] and body["chunks_used"] == 0


def test_model_failure_everywhere_is_bad_gateway(client, rag_stub):
    """Сломан и откат: наружу уходит 502 с текстом ошибки."""
    rag_stub.error = RuntimeError("boom")
    rag_stub.error_times = None

    response = client.post("/rag/query", json={"question": QUESTION})

    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


def test_compare_returns_both_answers(client):
    """Сравнение: рядом ответ без RAG и ответ по корпусу."""
    response = client.post("/rag/compare", json={"question": QUESTION, "top_k": 2})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question"] == QUESTION
    assert body["no_rag"]["mode"] == "no_rag" and body["no_rag"]["answer"]
    assert body["no_rag"]["sources"] == []
    assert body["rag"]["mode"] == "rag" and body["rag"]["answer"]
    assert body["rag"]["sources"] and len(body["rag"]["sources"]) <= 2


def test_root_lists_rag_group(client):
    """Корневая точка перечисляет группу RAG и все три её эндпоинта."""
    body = client.get("/").json()

    assert "/rag/query" in body["rag"]
    for path in ("POST /rag/query", "GET /rag/config", "POST /rag/compare"):
        assert body["endpoints"].count(path) == 1
    assert "rag" in body
