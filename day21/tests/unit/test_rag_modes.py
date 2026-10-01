"""Режимы отбора RAG (день 23): переформулировка, реранк, порог, сравнение режимов.

Отдельный модуль от ``test_rag_service.py`` по лимиту 400 строк: там контракт самой
службы (поиск, промпт, ответы, отказы), здесь — что добавляет второй этап отбора.
Реранкер подменён заглушкой ``RagStubReranker`` (``tests/rag_fakes.py``): сеть и
веса кросс-энкодера в быстром прогоне не нужны.
"""
import pytest

from backend.domain import rag_filter, rag_mode, rag_quotes
from backend.domain.rag_mode import RAG_STRATEGY_STRUCTURAL
from backend.services.rag_errors import RAGRejected
from backend.services.rag_service import RAGService
from backend.services.rerank_service import RerankError

from rag_fakes import GROUNDED_REPLY

QUESTION = "Чему равен CHARS_PER_PAGE?"


def test_retrieve_exposes_three_scores_without_rerank(rag_service):
    """Базовый режим: балл слов и близость видны по отдельности, реранкер не звался."""
    hits = rag_service.retrieve(QUESTION, top_k=5)

    assert hits and hits[0]["source"] == "rules.md"
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    for hit in hits:
        assert hit["rerank_score"] is None
        assert hit["lexical_score"] >= 0.0
        # Гибридная формула дня 22: балл слов плюс 0.2 от близости, не меньше балла слов.
        assert hit["score"] == pytest.approx(
            hit["lexical_score"] + rag_mode.RAG_VECTOR_WEIGHT * hit["vector_score"],
            abs=1e-3)
    assert hits[0]["lexical_score"] > 0.0


def test_mode_rewrite_searches_with_rewritten_query(rag_service, rag_stub):
    """Режим переформулировки: первый вызов модели даёт запрос, второй — ответ."""
    rag_stub.replies = ["CHARS_PER_PAGE страницу символов", GROUNDED_REPLY]

    record = rag_service.rag_query(QUESTION, top_k=3,
                                   mode=rag_filter.RAG_MODE_REWRITE)

    assert len(rag_stub.calls) == 2
    assert rag_stub.calls[0]["messages"][0]["content"] == \
        rag_filter.RAG_REWRITE_SYSTEM_PROMPT
    assert rag_stub.calls[0]["messages"][1]["content"] == QUESTION
    assert record["rewritten"] is True
    assert record["query_used"] == "CHARS_PER_PAGE страницу символов"
    assert record["rewrite_warning"] == ""
    assert record["answer"] == GROUNDED_REPLY
    assert record["sources"]


def test_rewrite_failure_falls_back_to_question(rag_service, rag_stub):
    """Сбой переформулировки не отменяет ответ: поиск идёт по исходному вопросу."""
    class FailingRewrite:
        """Клиент, у которого падает только вызов переформулировки."""

        def generate_with_context(self, **kwargs):
            if kwargs.get("system") == rag_filter.RAG_REWRITE_SYSTEM_PROMPT:
                raise RuntimeError("сеть недоступна")
            return rag_service.llm_client.generate_with_context(**kwargs)

    service = RAGService(index_service=rag_service.index_service,
                         loader=rag_service.loader, store=rag_service.store,
                         llm_client=FailingRewrite(),
                         rerank_service=rag_service.rerank_service,
                         sleep=lambda _seconds: None)

    record = service.rag_query(QUESTION, mode=rag_filter.RAG_MODE_REWRITE)

    assert record["rewritten"] is False
    assert record["query_used"] == QUESTION
    assert "Переформулировка не удалась" in record["rewrite_warning"]
    assert record["answer"] == GROUNDED_REPLY
    assert record["sources"]


def test_empty_rewrite_keeps_original_query(rag_service, rag_stub):
    """Пустая переформулировка — тоже отказ переформулировать, а не поиск по пустому."""
    rag_stub.replies = ["", GROUNDED_REPLY]

    record = rag_service.rag_query(QUESTION, mode=rag_filter.RAG_MODE_REWRITE)

    assert record["query_used"] == QUESTION
    assert record["rewrite_warning"] == rag_filter.RAG_REWRITE_EMPTY_WARNING


def test_mode_rerank_sorts_by_rerank_score(rag_service, rag_reranker):
    """Реранкер задаёт порядок и балл источника: видно «до и после» второй ступени."""
    record = rag_service.rag_query(QUESTION, top_k=2,
                                   mode=rag_filter.RAG_MODE_RERANK)

    scores = [hit["rerank_score"] for hit in record["sources"]]
    assert len(rag_reranker.calls) == 1
    assert rag_reranker.calls[0]["query"] == QUESTION
    assert len(rag_reranker.calls[0]["texts"]) == record["candidates"]
    assert all(score is not None for score in scores)
    assert scores == sorted(scores, reverse=True)
    # Балл отбора — тот же балл реранкера, по которому источники отсортированы.
    assert [hit["score"] for hit in record["sources"]] == scores
    assert record["reranked"] is True
    assert record["kept"] == len(record["sources"])
    assert record["candidates"] >= record["kept"]
    assert record["rerank_warning"] == ""


def test_min_score_dropping_all_fragments_gives_dont_know(rag_service, rag_stub):
    """Порог выше любого балла отрезает все фрагменты — это режим «не знаю».

    Ответа без источников больше не бывает: инвариант дня 24 — у каждого
    ``rag``-ответа есть хотя бы один источник и одна цитата.
    """
    record = rag_service.rag_query(QUESTION, mode=rag_filter.RAG_MODE_RERANK_FILTER,
                                   min_score=0.99)

    assert record["candidates"] > 0
    assert record["kept"] == 0
    assert record["mode"] == rag_quotes.RAG_MODE_DONT_KNOW
    assert record["answer"] == rag_quotes.DONT_KNOW_ANSWER
    assert record["sources"] == [] and record["quotes"] == []
    assert record["chunks_used"] == 0
    assert record["min_score"] == 0.99
    assert "0.99" in record["filter_warning"]
    assert rag_stub.calls == []


def test_reranker_failure_keeps_day22_order(rag_service, rag_reranker):
    """Сбой реранкера — предупреждение, а не отказ: порядок и порог отступают."""
    rag_reranker.error = RerankError("нет весов")

    record = rag_service.rag_query(QUESTION, mode=rag_filter.RAG_MODE_RERANK_FILTER)

    assert "Реранкер недоступен" in record["rerank_warning"]
    assert record["reranked"] is False
    assert record["sources"], "сбой необязательной ступени не должен обнулять контекст"
    assert all(hit["rerank_score"] is None for hit in record["sources"])
    assert record["min_score"] is None
    assert record["filter_warning"] == ""


def test_unknown_mode_rejected(rag_service, rag_stub):
    """Незнакомый режим — отказ ввода: к модели запрос не уходит."""
    with pytest.raises(RAGRejected) as exc:
        rag_service.retrieve(QUESTION, mode="нет такого")

    assert exc.value.reason_code == rag_filter.REASON_RAG_BAD_MODE
    assert "нет такого" in exc.value.message
    assert rag_stub.calls == []


def test_top_k_candidates_limits_the_pool(rag_service, chunk_store):
    """Число кандидатов ограничивается пулом: до отсечения доходит ровно столько."""
    total = chunk_store.count(RAG_STRATEGY_STRUCTURAL)
    assert total >= 2, "тестовый корпус должен давать хотя бы два фрагмента"

    tight = rag_service.rag_query(QUESTION, top_k=1, top_k_candidates=1)
    wide = rag_service.rag_query(QUESTION, top_k=1)

    assert tight["top_k_candidates"] == 1
    assert tight["candidates"] == 1
    # По умолчанию пул — как в дне 22: не меньше RAG_CANDIDATE_POOL.
    assert wide["top_k_candidates"] == max(rag_mode.RAG_CANDIDATE_POOL, 1)
    assert wide["candidates"] == min(rag_mode.RAG_CANDIDATE_POOL, total)
    assert tight["kept"] <= 1


def test_compare_modes_runs_each_mode_on_one_question(rag_service, rag_reranker):
    """Сравнение режимов: одна запись на режим, у каждой свои числа отбора."""
    record = rag_service.compare_modes(
        QUESTION, top_k=2, modes=[rag_filter.RAG_MODE_BASELINE,
                                  rag_filter.RAG_MODE_RERANK_FILTER])

    assert record["question"] == QUESTION
    assert [item["mode"] for item in record["modes"]] == ["baseline", "rerank_filter"]
    baseline, filtered = (item["result"] for item in record["modes"])
    assert record["modes"][0]["label"] == rag_filter.RAG_MODE_LABELS["baseline"]
    assert baseline["reranked"] is False and baseline["min_score"] is None
    assert filtered["reranked"] is True
    assert filtered["min_score"] == rag_filter.RAG_FILTER_MIN_SCORE
    assert baseline["candidates"] == filtered["candidates"]
    assert filtered["kept"] <= baseline["kept"]


def test_compare_modes_drops_unknown_but_rejects_empty_set(rag_service):
    """Незнакомые имена отбрасываются, но пустой набор режимов — отказ."""
    record = rag_service.compare_modes(QUESTION, modes=["baseline", "нет такого"])

    assert [item["mode"] for item in record["modes"]] == ["baseline"]
    with pytest.raises(RAGRejected) as exc:
        rag_service.compare_modes(QUESTION, modes=["нет такого"])
    assert exc.value.reason_code == rag_filter.REASON_RAG_BAD_MODE
