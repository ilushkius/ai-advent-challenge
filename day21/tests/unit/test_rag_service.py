"""Служба режима RAG: поиск, промпт, ответы с контекстом и без, отказы.

Проверяется контракт ``RAGService``: поиск отдаёт интерфейсу восемь полей на
источник (три балла отбора плюс балл реранкера), промпт собирается как «системное
сообщение → блок контекста → вопрос», пустой вопрос и незнакомая стратегия
отвергаются кодом причины, сбойный вызов повторяется и откатывается на ответ без
контекста, а полный сбой даёт ``RAGUpstreamError``. Режимы дня 23 — переформулировка
вопроса, реранк кросс-энкодером, порог отсечения и сравнение режимов — живут в
``tests/unit/test_rag_modes.py`` (лимит 400 строк на файл). Сеть и модели подменены
(``tests/rag_fakes.py``), корпус — два документа, индекс — фейковый эмбеддер.
"""
import pytest

from backend.core import config
from backend.domain import rag_mode
from backend.domain.document_sources import KIND_CODE, DocumentSource
from backend.domain.rag_mode import (
    GROUNDED_VERDICT,
    LOW_CONFIDENCE_VERDICT,
    RAG_DEFAULT_STRATEGY,
    RAG_HEADER,
    RAG_LLM_ATTEMPTS,
    RAG_STRATEGIES,
    RAG_STRATEGY_STRUCTURAL,
    RAG_SYSTEM_PROMPT,
    REASON_RAG_BAD_STRATEGY,
    REASON_RAG_EMPTY_QUERY,
    REASON_RAG_INDEX_EMPTY,
)
from backend.services import llm_factory, rag_llm, rag_service as rag_service_module
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.services.rag_errors import RAGError, RAGRejected, RAGUpstreamError
from backend.services.rag_service import RAGService

from rag_fakes import GROUNDED_REPLY, UNGROUNDED_REPLY

#: Ровно те поля, которые служба показывает интерфейсу: текст фрагмента не уходит.
SOURCE_KEYS = {"source", "title", "section", "chunk_id", "score", "vector_score",
               "lexical_score", "rerank_score"}

QUESTION = "Чему равен CHARS_PER_PAGE?"


def test_retrieve_returns_top_k_with_metadata(rag_service, chunk_store):
    """Поиск даёт top-k источников с пятью полями и по убыванию оценки."""
    total = chunk_store.count(RAG_STRATEGY_STRUCTURAL)
    assert total >= 2, "тестовый корпус должен давать хотя бы два фрагмента"

    hits = rag_service.retrieve("CHARS_PER_PAGE", top_k=2)

    assert len(hits) == 2
    assert set(hits[0]) == SOURCE_KEYS
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    # Литерал есть только в одном документе — он и должен быть первым.
    assert hits[0]["source"] == "rules.md"


def test_retrieve_clamps_top_k(rag_service, chunk_store, monkeypatch):
    """top_k обрезается границами домена: больше максимума не запрашивается."""
    total = chunk_store.count(RAG_STRATEGY_STRUCTURAL)
    monkeypatch.setattr(rag_mode, "RAG_MAX_TOP_K", 1)

    assert len(rag_service.retrieve("корпус", top_k=999)) == min(1, total)
    assert len(rag_service.retrieve("корпус")) == min(
        rag_mode.RAG_DEFAULT_TOP_K, total)


def test_rag_query_builds_prompt_with_context_and_question(rag_service, rag_stub):
    """Промпт режима RAG: системное сообщение, блок контекста и вопрос в конце."""
    record = rag_service.rag_query(QUESTION, top_k=5)

    messages = rag_stub.calls[-1]["messages"]
    assert messages[0] == {"role": "system", "content": RAG_SYSTEM_PROMPT}
    assert RAG_HEADER in messages[1]["content"]
    assert "CHARS_PER_PAGE" in messages[1]["content"]
    assert messages[1]["content"].endswith(QUESTION)

    assert record["mode"] == "rag"
    assert record["answer"] == GROUNDED_REPLY
    assert record["chunks_used"] >= 1
    assert len(record["sources"]) == record["chunks_used"]
    assert set(record["sources"][0]) == SOURCE_KEYS
    assert record["context_tokens"] > 0
    assert record["grounding"] == GROUNDED_VERDICT
    assert record["fallback"] is False and record["warning"] == ""
    assert record["duration_ms"] >= 0
    # Учёт расхода — тот же, что у дня 21: 900 попаданий из 1200 токенов промпта.
    assert record["tokens"]["cache_hit_percent"] == pytest.approx(75.0)


def test_no_rag_query_sends_only_question(rag_service, rag_stub):
    """Режим без RAG: тот же системный промпт, но сообщение — только вопрос."""
    record = rag_service.no_rag_query(QUESTION)

    messages = rag_stub.calls[-1]["messages"]
    assert messages[0]["content"] == RAG_SYSTEM_PROMPT
    assert messages[1]["content"] == QUESTION

    assert record["mode"] == "no_rag"
    assert record["answer"] == GROUNDED_REPLY
    assert record["sources"] == [] and record["chunks_used"] == 0
    assert record["context_tokens"] == 0 and record["grounding"] == ""
    assert record["tokens"]["model"]


def test_empty_question_rejected(rag_service, rag_stub):
    """Пустой вопрос отвергается в обоих режимах: к модели запрос не уходит."""
    for call in (rag_service.retrieve, rag_service.rag_query,
                 rag_service.no_rag_query):
        with pytest.raises(RAGRejected) as exc:
            call("   ")
        assert exc.value.reason_code == REASON_RAG_EMPTY_QUERY
    assert rag_stub.calls == []


def test_unknown_strategy_rejected(rag_service):
    """Незнакомая стратегия — отказ ввода, а не поиск по стратегии по умолчанию."""
    with pytest.raises(RAGRejected) as exc:
        rag_service.retrieve("корпус", strategy="fixed")

    assert exc.value.reason_code == REASON_RAG_BAD_STRATEGY
    assert "fixed" in exc.value.message


def test_empty_index_rejected(rag_loader, empty_index_service, chunk_store, rag_client):
    """Индекс стратегии пуст — отказ с подсказкой, как его построить."""
    service = RAGService(index_service=empty_index_service, loader=rag_loader,
                         store=chunk_store, llm_client=rag_client,
                         sleep=lambda _seconds: None)

    with pytest.raises(RAGRejected) as exc:
        service.retrieve("корпус")

    assert exc.value.reason_code == REASON_RAG_INDEX_EMPTY
    assert "scripts/prepare_rag_corpus.py" in exc.value.message


def test_llm_failure_retries_and_falls_back(rag_service, rag_stub):
    """Сбойный вызов с контекстом: три попытки, затем ответ без RAG под вопросом."""
    rag_stub.error = RuntimeError("boom")
    rag_stub.error_times = RAG_LLM_ATTEMPTS

    record = rag_service.rag_query(QUESTION)

    # Три неудачные попытки с контекстом и один успешный вызов отката: откат
    # идёт тем же путём к модели, но без блока контекста.
    assert len(rag_stub.calls) == RAG_LLM_ATTEMPTS + 1
    assert RAG_HEADER not in rag_stub.calls[-1]["messages"][1]["content"]
    assert record["fallback"] is True
    assert "boom" in record["warning"]
    assert record["mode"] == "rag"
    assert record["answer"] == GROUNDED_REPLY
    assert record["sources"] == [] and record["chunks_used"] == 0
    assert record["context_tokens"] == 0 and record["grounding"] == ""


def test_llm_failure_everywhere_raises_upstream(rag_service, rag_stub):
    """Откат тоже сломан — наружу уходит ``RAGUpstreamError`` (в HTTP это 502)."""
    rag_stub.error = RuntimeError("boom")
    rag_stub.error_times = None

    with pytest.raises(RAGUpstreamError):
        rag_service.rag_query(QUESTION)
    assert len(rag_stub.calls) == RAG_LLM_ATTEMPTS * 2

    rag_stub.calls.clear()
    with pytest.raises(RAGUpstreamError):
        rag_service.no_rag_query(QUESTION)
    assert len(rag_stub.calls) == RAG_LLM_ATTEMPTS


def test_context_budget_drops_tail(rag_service, chunk_store, monkeypatch):
    """Малый бюджет контекста оставляет первый фрагмент: хвост выдачи отброшен."""
    total = chunk_store.count(RAG_STRATEGY_STRUCTURAL)
    monkeypatch.setattr(rag_mode, "RAG_CONTEXT_MAX_TOKENS", 5)

    record = rag_service.rag_query(QUESTION, top_k=5)

    assert len(record["sources"]) == min(5, total)
    assert record["chunks_used"] == 1


def test_grounding_flags_low_confidence(rag_service, rag_stub):
    """Ответ без слов контекста помечается низкой уверенностью."""
    rag_stub.reply = UNGROUNDED_REPLY

    record = rag_service.rag_query(QUESTION)

    assert record["grounding"] == LOW_CONFIDENCE_VERDICT
    assert record["chunks_used"] >= 1


def test_compare_calls_both_modes(rag_service, rag_stub):
    """Сравнение: сначала ответ без RAG, затем ответ с контекстом."""
    body = rag_service.compare(QUESTION, top_k=3)

    assert len(rag_stub.calls) == 2
    assert rag_stub.calls[0]["messages"][1]["content"] == QUESTION
    assert RAG_HEADER not in rag_stub.calls[0]["messages"][1]["content"]
    assert RAG_HEADER in rag_stub.calls[1]["messages"][1]["content"]

    assert body["question"] == QUESTION
    assert body["no_rag"]["mode"] == "no_rag" and body["rag"]["mode"] == "rag"
    assert body["no_rag"]["sources"] == []
    assert body["rag"]["sources"] and len(body["rag"]["sources"]) <= 3


def test_prepare_corpus_builds_both_indexes(rag_loader, empty_index_service,
                                            chunk_store):
    """Сборка корпуса строит оба индекса; повторный прогон не дописывает чанки."""
    service = RAGService(index_service=empty_index_service, loader=rag_loader,
                         store=chunk_store)

    result = service.prepare_corpus()

    assert set(result["chunks"]) == set(RAG_STRATEGIES)
    assert result["corpus"]["documents"] == 2
    for strategy in RAG_STRATEGIES:
        assert result["chunks"][strategy] >= 1
        assert result["indexes"][strategy]["indexed"] == result["chunks"][strategy]
        assert chunk_store.count(strategy) == result["chunks"][strategy]
        assert empty_index_service.path_for(strategy).exists()

    again = service.prepare_corpus()
    assert again["chunks"] == result["chunks"]


def test_prepare_corpus_rejects_broken_sources(tmp_path, rag_index_service):
    """Пропавший источник корпуса — ошибка сборки, а не пустой индекс."""
    loader = RagCorpusLoader(
        documents_dir=tmp_path / "corpus",
        sources=(DocumentSource(path="day21/нет-такого.py", kind=KIND_CODE,
                                max_chars=100),),
    )
    service = RAGService(index_service=rag_index_service, loader=loader)

    with pytest.raises(RAGError) as exc:
        service.prepare_corpus()

    assert "нет-такого.py" in str(exc.value)


def test_config_reports_corpus_and_indexes(rag_service):
    """Конфигурация режима: объём корпуса, чанки обеих стратегий и лимиты."""
    cfg = rag_service.config()

    assert cfg["corpus"]["documents"] == 2
    assert cfg["chunks_total"] == sum(item["chunks"] for item in cfg["indexes"])
    assert cfg["chunks_total"] > 0
    assert [item["strategy"] for item in cfg["indexes"]] == list(RAG_STRATEGIES)
    assert cfg["strategies"] == list(RAG_STRATEGIES)
    assert cfg["default_strategy"] == RAG_DEFAULT_STRATEGY
    assert cfg["top_k_default"] == rag_mode.RAG_DEFAULT_TOP_K
    assert cfg["top_k_max"] == rag_mode.RAG_MAX_TOP_K
    assert cfg["context_max_tokens"] == rag_mode.RAG_CONTEXT_MAX_TOKENS
    assert cfg["chunk_max_chars"] == rag_mode.RAG_CHUNK_MAX_CHARS
    # Тестовый корпус меньше минимума страниц — готовности нет, чанки при этом есть.
    assert cfg["ready"] is False
    assert cfg["corpus"]["pages"] < cfg["corpus"]["min_pages"]


def test_make_rag_client_requires_api_key(monkeypatch):
    """Клиент RAG собирается на ключе: без ключа вызов модели невозможен."""
    monkeypatch.setattr(config, "resolve_api_key", lambda: "")
    with pytest.raises(RuntimeError):
        rag_llm.make_rag_client()

    monkeypatch.setattr(config, "resolve_api_key", lambda: "sk-test")
    assert rag_llm.make_rag_client() is not None


def test_lazy_dependencies_built_once(monkeypatch, rag_loader, rag_index_service,
                                      chunk_store, rag_client):
    """Зависимости процесса строятся лениво и только один раз."""
    calls = []
    monkeypatch.setattr(rag_service_module, "get_index_service",
                        lambda: calls.append("index") or rag_index_service)

    def build_loader():
        calls.append("loader")
        return rag_loader

    monkeypatch.setattr(rag_service_module, "get_rag_corpus_loader", build_loader)
    monkeypatch.setattr(rag_service_module, "ChunkStore", lambda: chunk_store)
    # Обёртку DeepSeek собирает фабрика провайдера (день 26) — подменяем там же.
    monkeypatch.setattr(llm_factory, "LLMClient", lambda **kwargs: rag_client)

    service = RAGService()

    assert service.index_service is rag_index_service
    assert service.index_service is rag_index_service
    assert service.loader is rag_loader
    assert service.store is chunk_store
    assert service.llm_client is rag_client
    assert calls == ["index", "loader"]


def test_get_rag_service_is_singleton(monkeypatch):
    """Точка подмены ``main.get_rag_service`` отдаёт одну службу на процесс."""
    monkeypatch.setattr(rag_service_module, "_service", None)

    first = rag_service_module.get_rag_service()

    assert isinstance(first, RAGService)
    assert rag_service_module.get_rag_service() is first


def test_query_weights_rare_word_outweighs_common_one():
    """Вес слова обратен его частоте: редкий идентификатор весит больше общего слова."""
    documents = ["CHARS_PER_PAGE равен 1800", "далее day21 и day21", "day21 ещё раз"]

    weights = rag_mode.query_weights("CHARS_PER_PAGE day21", documents)

    assert weights["chars_per_page"] == 1.0
    # «day21» встречается в двух фрагментах из трёх — вес вдвое меньше.
    assert weights["day21"] == pytest.approx(1 / 2)
    assert weights["chars_per_page"] > weights["day21"]
    assert rag_mode.query_weights("  и  ", documents) == {}


def test_lexical_score_is_share_of_query_word_weights():
    """Оценка — доля веса слов вопроса, найденных в тексте (0.0 — ни одного)."""
    weights = {"chars_per_page": 1.0, "day21": 1.0}

    assert rag_mode.lexical_score("Тут CHARS_PER_PAGE и day21", weights) == 1.0
    assert rag_mode.lexical_score("Тут только day21", weights) == 0.5
    assert rag_mode.lexical_score("Совсем другое", weights) == 0.0
    assert rag_mode.lexical_score("day21", {}) == 0.0


def test_rank_candidates_prefers_literal_match_over_vector_noise():
    """Фрагмент с редким словом вопроса обгоняет тематически близкий, но без слова."""
    vector_hits = [{"chunk_id": "v1", "source": "тема.md", "title": "Память",
                    "section": "обзор", "content": "Память и агенты", "score": 0.7}]
    chunks = [{"chunk_id": "c1", "source": "config.py", "title": "Константы",
               "section": "Константы", "content": "CHARS_PER_PAGE = 1800", "score": 0.0}]

    ranked = rag_mode.rank_candidates("Чему равен CHARS_PER_PAGE?", vector_hits,
                                      chunks, 2)

    assert [hit["chunk_id"] for hit in ranked] == ["c1", "v1"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_candidates_without_query_words_keeps_vector_order():
    """Без слов вопроса порядок задаёт векторная близость, а не порядок словаря."""
    vector_hits = [
        {"chunk_id": "v1", "source": "a.md", "title": "A", "section": "a",
         "content": "AAA BBB", "score": 0.4},
        {"chunk_id": "v2", "source": "b.md", "title": "B", "section": "b",
         "content": "AAA BBB", "score": 0.6},
    ]

    ranked = rag_mode.rank_candidates("и", vector_hits, [], 2)

    assert [hit["chunk_id"] for hit in ranked] == ["v2", "v1"]


def test_rank_candidates_keeps_store_chunk_without_vector_hit():
    """Кандидаты берутся и из хранилища: фрагмент без векторного попадания попадает в ответ."""
    chunks = [
        {"chunk_id": "c1", "source": "a.md", "title": "A", "section": "a",
         "content": "CHARS_PER_PAGE равен 1800", "score": 0.0},
        {"chunk_id": "c2", "source": "b.md", "title": "B", "section": "b",
         "content": "Совсем другой текст", "score": 0.0},
    ]

    ranked = rag_mode.rank_candidates("Где описан CHARS_PER_PAGE?", [], chunks, 5)

    assert [hit["chunk_id"] for hit in ranked] == ["c1"]


def test_rank_candidates_exposes_lexical_and_vector_scores():
    """Гибридный балл и балл слов отдаются наружу: видно, чем фрагмент обошёл соседа."""
    vector_hits = [
        {"chunk_id": "v1", "source": "a.md", "title": "A", "section": "a",
         "content": "CHARS_PER_PAGE равен 1800", "score": 0.1},
        {"chunk_id": "v2", "source": "b.md", "title": "B", "section": "b",
         "content": "Совсем другой текст", "score": 0.9},
    ]
    chunks = [{"chunk_id": "c1", "source": "a.md", "title": "A", "section": "a",
               "content": "CHARS_PER_PAGE равен 1800", "score": 0.0}]

    ranked = rag_mode.rank_candidates("CHARS_PER_PAGE", vector_hits, chunks, 3)

    weights = rag_mode.query_weights("CHARS_PER_PAGE", ["CHARS_PER_PAGE равен 1800"])
    by_id = {hit["chunk_id"]: hit for hit in ranked}
    assert {"score", "lexical_score"} <= set(by_id["v1"])
    # Балл слов — та же величина, что считает домен: не украшение, а число отбора.
    assert by_id["v1"]["lexical_score"] == rag_mode.lexical_score(
        "CHARS_PER_PAGE равен 1800 a A", weights)
    assert by_id["v2"]["lexical_score"] == 0.0
    # Гибридная формула дня 22 не изменилась: слова плюс 0.2 от близости.
    assert by_id["v1"]["score"] == round(
        by_id["v1"]["lexical_score"] + rag_mode.RAG_VECTOR_WEIGHT * 0.1, 4)

