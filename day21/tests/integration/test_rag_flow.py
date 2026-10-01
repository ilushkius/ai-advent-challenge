"""Сквозной цикл RAG на настоящем корпусе: сборка, оба индекса, поиск и ответ.

Проверяется то, ради чего корпус и заведён: ``prepare_corpus`` собирает документы
дня 21 из репозитория, обе стратегии дают не меньше минимума чанков, поиск отдаёт
попадания с баллами отбора, ответ приходит с источниками, а каждый контрольный
вопрос опирается на факт, который в корпусе действительно есть — иначе отчёт
оценки мерил бы отсутствующие данные. День 23 добавляет сюда прогон реранкера на
том же корпусе: баллы кросс-энкодера пересортировывают настоящую выдачу поиска.

Модель и реранкер подменены заглушками, эмбеддер — фейковый: тест проверяет сборку
и связку слоёв, а не качество ранжирования настоящей модели (оно видно в отчёте
прогона).
"""
from collections import defaultdict

import pytest

from backend.domain import rag_corpus_spec, rag_filter, rag_mode
from backend.domain.document_sources import source_slug
from backend.domain.rag_eval import RAG_QUESTIONS
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.services.rag_service import AGENT_ID, RAGService
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import RagStubClient, RagStubReranker

pytestmark = pytest.mark.slow

#: Ровно те поля, которые служба показывает интерфейсу: текст фрагмента не уходит.
SOURCE_KEYS = {"source", "title", "section", "chunk_id", "score", "vector_score",
               "lexical_score", "rerank_score"}


@pytest.fixture
def corpus_service(tmp_path, chunk_store, fake_embedder, session_factory):
    """Служба RAG на настоящем корпусе: временные папки, фейковый эмбеддер, заглушки."""
    loader = RagCorpusLoader(documents_dir=tmp_path / "rag_corpus")
    index_service = IndexService(embedder=fake_embedder, store=chunk_store,
                                index_dir=tmp_path / "index")
    stub = RagStubClient()
    client = LLMClient(agent_id=AGENT_ID, client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    reranker = RagStubReranker()
    service = RAGService(index_service=index_service, loader=loader,
                         store=chunk_store, llm_client=client,
                         rerank_service=reranker, sleep=lambda _seconds: None)
    service.stub = stub
    service.reranker = reranker
    return service


def test_prepare_corpus_builds_both_indexes_from_repository(corpus_service, chunk_store):
    """Сборка корпуса: 36 источников, страницы и чанки не ниже минимумов."""
    assert rag_corpus_spec.validate_sources() == []

    result = corpus_service.prepare_corpus()

    assert result["corpus"]["documents"] == len(rag_corpus_spec.RAG_CORPUS_SOURCES)
    assert result["corpus"]["pages"] >= rag_corpus_spec.RAG_CORPUS_MIN_PAGES
    for strategy in rag_mode.RAG_STRATEGIES:
        assert result["chunks"][strategy] >= rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS
        assert chunk_store.count(strategy) == result["chunks"][strategy]
        assert corpus_service.index_service.path_for(strategy).exists()

    config = corpus_service.config()
    assert config["ready"] is True
    assert config["chunks_total"] == sum(item["chunks"] for item in config["indexes"])


def test_search_and_answer_use_corpus_sources(corpus_service):
    """Поиск отдаёт попадания по убыванию оценки, ответ — с использованными чанками."""
    corpus_service.prepare_corpus()
    question = RAG_QUESTIONS[0]

    hits = corpus_service.retrieve(question.question, top_k=rag_mode.RAG_MAX_TOP_K)
    assert len(hits) == rag_mode.RAG_MAX_TOP_K
    assert set(hits[0]) == SOURCE_KEYS
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(hit["source"] and hit["chunk_id"] for hit in hits)

    record = corpus_service.rag_query(question.question)
    assert record["mode"] == "rag" and record["answer"]
    assert record["chunks_used"] >= 1
    assert len(record["sources"]) == record["chunks_used"]
    assert set(record["sources"][0]) == SOURCE_KEYS
    assert record["fallback"] is False
    assert record["context_tokens"] > 0
    assert record["tokens"]["prompt_tokens"] > 0
    assert corpus_service.stub.calls[-1]["messages"][1]["content"]


def test_every_control_question_is_answerable_from_corpus(corpus_service, chunk_store):
    """Эталонные факты всех десяти вопросов есть в чанках названных источников."""
    corpus_service.prepare_corpus()
    by_source = defaultdict(list)
    for row in chunk_store.chunks(rag_mode.RAG_DEFAULT_STRATEGY):
        by_source[row["source"]].append(row["content"])

    for number, question in enumerate(RAG_QUESTIONS, 1):
        slug = source_slug(question.expected_sources[0])
        text = "\n".join(by_source[slug]).lower()
        assert text, f"вопрос {number}: источник {slug} не попал в индекс"
        missing = [fact for fact in question.key_facts if fact.lower() not in text]
        assert not missing, f"вопрос {number}: в {slug} нет фактов {missing}"


def test_rerank_reorders_real_corpus_candidates(corpus_service):
    """Реранкер на настоящем корпусе: баллы по парам, порядок — по баллу реранкера."""
    corpus_service.prepare_corpus()
    question = RAG_QUESTIONS[0]

    baseline = corpus_service.retrieve(question.question, top_k=rag_mode.RAG_MAX_TOP_K)
    reranked = corpus_service.retrieve(question.question, top_k=rag_mode.RAG_MAX_TOP_K,
                                       mode=rag_filter.RAG_MODE_RERANK)

    assert len(reranked) == len(baseline)
    scores = [hit["rerank_score"] for hit in reranked]
    assert all(score is not None for score in scores)
    assert scores == sorted(scores, reverse=True)
    assert len(corpus_service.reranker.calls) == 1
    assert len(corpus_service.reranker.calls[0]["texts"]) >= len(reranked)
    # Вторая ступень видна: заглушка ранжирует по словам вопроса, и её порядок
    # отличается от гибридного — иначе реранкер в отчёте мерил бы сам себя.
    assert [hit["chunk_id"] for hit in reranked] != [hit["chunk_id"] for hit in baseline]
    # Обрезка до top-K идёт ПОСЛЕ реранка, поэтому меняется и сам состав контекста.
    assert {hit["chunk_id"] for hit in reranked} != {hit["chunk_id"] for hit in baseline}

    filtered = corpus_service.retrieve(question.question, top_k=rag_mode.RAG_MAX_TOP_K,
                                       mode=rag_filter.RAG_MODE_RERANK_FILTER)
    assert filtered, "на контрольном вопросе порог не должен обнулять контекст"
    assert 0 < len(filtered) <= len(reranked)
    assert all(hit["rerank_score"] >= rag_filter.RAG_FILTER_MIN_SCORE for hit in filtered)
