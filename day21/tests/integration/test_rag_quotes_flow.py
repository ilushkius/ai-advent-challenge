"""Сквозной прогон демо дня 24 на настоящем корпусе: режимы, источники, цитаты.

Проверяется связка, ради которой день заведён: десять контрольных вопросов из
``backend/data/demo_questions.json`` проходят через ``RAGService``, каждый ответ в
режиме ``rag`` несёт источник и цитату, а при недостижимом пороге релевантности все
вопросы приходят в режиме «не знаю» и модель не вызывается ни разу. Эмбеддер
фейковый, модель и реранкер — заглушки: тест закрепляет контракт ответа, а
распределение режимов по настоящим баллам видно в отчёте прогона
(``docs/reports/rag_quotes_eval.md``). Фейковый эмбеддер даёт завышенный косинус,
поэтому режим «не знаю» здесь проверяется подъёмом порога, а не боевым значением.
"""
import pytest

from backend.domain import rag_demo, rag_quotes
from backend.services import rag_demo_service
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.services.rag_service import AGENT_ID, RAGService
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import RagStubClient, RagStubReranker

from test_rag_flow import SOURCE_KEYS

pytestmark = pytest.mark.slow

#: Порог выше любого косинуса (единица — потолок для нормализованных векторов).
UNREACHABLE_THRESHOLD = 1.5


@pytest.fixture
def corpus_service(tmp_path, chunk_store, fake_embedder, session_factory):
    """Служба RAG на настоящем корпусе: временные папки, фейковый эмбеддер, заглушки."""
    loader = RagCorpusLoader(documents_dir=tmp_path / "rag_corpus")
    index_service = IndexService(embedder=fake_embedder, store=chunk_store,
                                index_dir=tmp_path / "index")
    stub = RagStubClient()
    client = LLMClient(agent_id=AGENT_ID, client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    service = RAGService(index_service=index_service, loader=loader,
                         store=chunk_store, llm_client=client,
                         rerank_service=RagStubReranker(), sleep=lambda _seconds: None)
    service.stub = stub
    return service


def test_demo_run_answers_every_question_with_sources_and_quotes(corpus_service):
    """Прогон демо: каждый вопрос размечен режимом, источники и цитаты идут вместе с ответом."""
    corpus_service.prepare_corpus()

    result = rag_demo_service.run_demo(corpus_service, rag_demo.load_questions())

    rows = result["rows"]
    summary = result["summary"]
    assert summary["total"] == len(rows) == 10
    for row in rows:
        assert row["mode"] in {rag_quotes.RAG_MODE_RAG, rag_quotes.RAG_MODE_NO_RAG,
                               rag_quotes.RAG_MODE_DONT_KNOW}
        if row["mode"] == rag_quotes.RAG_MODE_RAG:
            assert row["sources"], f"ответ без источников: {row['question']}"
            assert row["quotes"], f"ответ без цитат: {row['question']}"
            assert set(row["sources"][0]) == SOURCE_KEYS
            assert len(row["quotes"][0]["quote"]) <= rag_quotes.QUOTE_MAX_CHARS
            assert set(row["quotes"][0]) == set(rag_quotes.QUOTE_KEYS)
        if row["mode"] == rag_quotes.RAG_MODE_DONT_KNOW:
            assert row["sources"] == []
            assert row["quotes"] == []
            assert row["answer"] == rag_quotes.DONT_KNOW_ANSWER
    assert summary["rag"] + summary["no_rag"] + summary["dont_know"] == 10
    assert summary["no_rag"] == 0
    assert summary["with_sources"] == summary["rag"] == summary["with_quotes"]
    assert summary["with_sources"] >= 5
    for row in rows:
        if row["mode"] != rag_quotes.RAG_MODE_RAG:
            continue
        # Уверенность — это ровно результат проверки цитат: заглушка отвечает одним и
        # тем же текстом, поэтому подтверждение зависит от найденного фрагмента.
        verified = row["quotes_verified"]
        assert row["confidence"] == (rag_quotes.CONFIDENCE_HIGH if verified
                                    else rag_quotes.CONFIDENCE_LOW)


def test_unreachable_threshold_makes_every_question_dont_know(corpus_service, monkeypatch):
    """Порог выше любого косинуса: все десять вопросов — «не знаю», модель не вызвана."""
    monkeypatch.setattr(rag_quotes, "RAG_RELEVANCE_THRESHOLD", UNREACHABLE_THRESHOLD)
    corpus_service.prepare_corpus()
    questions = rag_demo.load_questions()

    result = rag_demo_service.run_demo(corpus_service, questions)

    rows = result["rows"]
    summary = result["summary"]
    without_answer = [item for item in questions
                      if item.expected_mode == rag_quotes.RAG_MODE_DONT_KNOW]
    verdicts = [row["verdict"] for row in rows]
    assert summary["total"] == 10
    assert summary["dont_know"] == 10
    assert summary["with_sources"] == 0 and summary["with_quotes"] == 0
    assert summary["rag"] == 0
    # Ни одного вызова модели: гейт порога стоит до вызова, и это главное требование дня.
    assert corpus_service.stub.calls == []
    # Совпали ровно вопросы, которые и не должны иметь ответа в корпусе; остальные —
    # расхождение по режиму, и это честный вердикт при недостижимом пороге.
    assert len(without_answer) == 2
    assert verdicts.count(rag_demo.VERDICT_DONT_KNOW_OK) == 2
    assert verdicts.count(rag_demo.VERDICT_MODE_MISMATCH) == 8
    for row in rows:
        assert row["mode"] == rag_quotes.RAG_MODE_DONT_KNOW
        assert row["sources"] == [] and row["quotes"] == []
        assert row["answer"] == rag_quotes.DONT_KNOW_ANSWER
        assert row["confidence"] == rag_quotes.CONFIDENCE_NONE
