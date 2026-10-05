"""Тесты эндпоинтов режима RAG.

Проверяется контракт ``/rag``: ответ по корпусу с источниками и без них,
конфигурация режима, сравнение двух ответов, сравнение режимов отбора (день 23),
переформулировка вопроса, порог отсечения и перевод отказов службы в статусы
(400 — пустой вопрос, незнакомая стратегия и незнакомый режим, 409 —
непроиндексированный корпус, 502 — сбой вызова модели, когда откат тоже не удался;
422 — порог вне ``[0, 1]``). Модель и реранкер подменены заглушками: через HTTP
проверяется связка слоёв, а не сеть.
"""
import pytest
from fastapi.testclient import TestClient

from backend.domain import rag_filter, rag_quotes
from backend.domain.rag_mode import RAG_DEFAULT_STRATEGY, RAG_LLM_ATTEMPTS
from backend.services import llm_factory
from backend.services.rag_service import RAGService
from backend.storage import database

from rag_fakes import GROUNDED_REPLY, LocalDictStubClient
from support import FakeClient

#: Ровно те поля, которые видит интерфейс: текст фрагмента через API не уходит.
SOURCE_KEYS = {"source", "title", "section", "chunk_id", "score", "vector_score",
               "lexical_score", "rerank_score"}

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
    """Корневая точка перечисляет группу RAG и все шесть её эндпоинтов."""
    body = client.get("/").json()

    assert "/rag/query" in body["rag"]
    for path in ("POST /rag/query", "GET /rag/config", "POST /rag/compare",
                 "POST /rag/compare_modes", "GET /rag/demo-questions",
                 "POST /rag/demo-run"):
        assert body["endpoints"].count(path) == 1
    assert "rag" in body


def test_demo_questions_lists_ten(client):
    """Контрольные вопросы демо: десять записей с ожидаемым режимом каждая."""
    response = client.get("/rag/demo-questions")

    assert response.status_code == 200, response.text
    questions = response.json()["questions"]
    assert len(questions) == 10
    for item in questions:
        assert item["question"]
        assert item["expected_mode"] in {rag_quotes.RAG_MODE_RAG,
                                        rag_quotes.RAG_MODE_DONT_KNOW}


def test_demo_run_returns_rows_and_summary(client):
    """Прогон демо: строка на вопрос с вердиктом и сводка с полным распределением."""
    response = client.post("/rag/demo-run", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 10
    assert body["summary"]["total"] == 10
    assert (body["summary"]["rag"] + body["summary"]["no_rag"]
            + body["summary"]["dont_know"]) == 10
    for row in body["rows"]:
        assert row["question"] and row["verdict"]
        assert row["mode"] in {rag_quotes.RAG_MODE_RAG, rag_quotes.RAG_MODE_NO_RAG,
                               rag_quotes.RAG_MODE_DONT_KNOW}

    single = client.post("/rag/demo-run",
                         json={"question": body["rows"][0]["question"]})
    assert single.status_code == 200, single.text
    assert len(single.json()["rows"]) == 1


# ---------- режимы отбора (день 23) ----------

def test_min_score_out_of_range_is_unprocessable(client):
    """Порог вне ``[0, 1]`` — ошибка схемы, а не тихий пропуск отсечения."""
    response = client.post("/rag/query", json={"question": QUESTION, "min_score": 1.5})

    assert response.status_code == 422


def test_min_score_above_every_score_returns_dont_know(client):
    """Порог отбора срезал все фрагменты: режим «не знаю» вместо ответа без источников."""
    response = client.post("/rag/query",
                           json={"question": QUESTION, "rerank": True,
                                 "min_score": 0.99})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == rag_quotes.RAG_MODE_DONT_KNOW
    assert body["answer"] == rag_quotes.DONT_KNOW_ANSWER
    assert body["sources"] == [] and body["quotes"] == []
    assert body["chunks_used"] == 0 and body["confidence"] == 0.0
    assert body["candidates"] > 0 and body["kept"] == 0
    assert body["min_score"] == 0.99
    assert "0.99" in body["filter_warning"]


def test_min_score_without_reranker_is_hybrid_scale(client):
    """Без реранкера порог сравнивается с гибридным баллом — его шкала не ``[0, 1]``."""
    response = client.post("/rag/query",
                           json={"question": QUESTION, "min_score": 0.99})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources"], "гибридный балл выше единицы: порог 0.99 ничего не режет"
    assert body["sources"][0]["rerank_score"] is None
    assert body["sources"][0]["score"] >= 0.99
    assert body["filter_warning"] == ""


def test_rewrite_and_rerank_over_api(client, rag_stub):
    """Переформулировка и реранкер включаются полями запроса и видны в ответе."""
    rag_stub.replies = ["CHARS_PER_PAGE страницу символов", "Корпус: 1800 символов."]

    response = client.post("/rag/query",
                           json={"question": QUESTION, "top_k": 3,
                                 "rewrite": True, "rerank": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query_used"] == "CHARS_PER_PAGE страницу символов"
    assert body["rewritten"] is True and body["reranked"] is True
    assert body["rewrite_warning"] == "" and body["rerank_warning"] == ""
    assert body["candidates"] >= body["kept"] == len(body["sources"])
    assert all(source["rerank_score"] is not None for source in body["sources"])
    # Балл отбора в режиме реранкера — балл кросс-энкодера, а не гибридный.
    assert body["sources"][0]["score"] == body["sources"][0]["rerank_score"]


def test_query_without_mode_fields_keeps_day22_shape(client):
    """Запрос без полей дня 23: гибридный порядок, реранкера нет, порога нет."""
    response = client.post("/rag/query", json={"question": QUESTION, "top_k": 3})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rewritten"] is False and body["reranked"] is False
    assert body["query_used"] == QUESTION
    assert body["min_score"] is None
    assert body["kept"] == len(body["sources"]) == body["chunks_used"]
    assert body["filter_warning"] == ""
    assert all(source["rerank_score"] is None for source in body["sources"])


def test_compare_modes_returns_each_mode(client):
    """Сравнение режимов: по записи на режим, каждая со своим ответом и источниками."""
    response = client.post("/rag/compare_modes",
                           json={"question": QUESTION, "top_k": 2,
                                 "modes": ["baseline", "rerank_filter"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question"] == QUESTION
    assert [item["mode"] for item in body["modes"]] == ["baseline", "rerank_filter"]
    assert [item["label"] for item in body["modes"]] == [
        rag_filter.RAG_MODE_LABELS["baseline"],
        rag_filter.RAG_MODE_LABELS["rerank_filter"],
    ]
    for item in body["modes"]:
        assert item["result"]["answer"]
        assert set(item["result"]["sources"][0]) == SOURCE_KEYS


def test_compare_modes_unknown_mode_is_bad_request(client):
    """Незнакомый режим — 400 с кодом причины, а не пустой список режимов."""
    response = client.post("/rag/compare_modes",
                           json={"question": QUESTION, "modes": ["нет такого"]})

    assert response.status_code == 400
    assert "Неизвестный режим отбора" in response.json()["detail"]


def test_rag_config_lists_modes_and_threshold(client):
    """Каталог режимов и модель реранкера приходят из конфигурации, а не из интерфейса."""
    response = client.get("/rag/config")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["modes"]] == list(rag_filter.RAG_MODES)
    assert all(item["label"] for item in body["modes"])
    assert body["rerank_model"] == rag_filter.RAG_RERANK_MODEL
    assert body["min_score_default"] == rag_filter.RAG_FILTER_MIN_SCORE
    assert body["candidates_max"] == rag_filter.RAG_MAX_CANDIDATES


def test_rag_query_local_provider_reaches_factory(client, monkeypatch):
    """Провайдер local (день 26): запрос уходит в фабрику, ответ помечен ``local``.

    Службе подменён облачный клиент, поэтому успех возможен только если поле
    ``provider`` действительно выбирает провайдера, а словарь локального клиента
    читается так же, как ответ DeepSeek.
    """
    stub = LocalDictStubClient()
    monkeypatch.setattr(llm_factory, "get_llm_client", lambda *args, **kwargs: stub)

    response = client.post("/rag/query",
                           json={"question": QUESTION, "provider": "local"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "local"
    assert body["mode"] == "rag"
    assert body["answer"] == GROUNDED_REPLY.strip()
    assert body["tokens"]["completion_tokens"] == 0
    assert body["tokens"]["cost_estimate"] == 0.0
    assert stub.calls, "фабрика провайдера не вызвана"


def test_rag_query_unknown_provider_is_bad_request(client):
    """Незнакомое имя провайдера — 400: подменять провайдера молча нельзя."""
    response = client.post("/rag/query",
                           json={"question": QUESTION, "provider": "nope"})

    assert response.status_code == 400, response.text
    assert "nope" in response.json()["detail"]
