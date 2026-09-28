"""Служба индексов: запись чанков, поиск, файлы индекса и очистка (день 21).

Проверяется связка «FAISS + SQLite»: id вектора равен id строки чанка, порядок
попаданий — по убыванию близости, а индекс и метаданные переживают перезапись в файл
и чтение новым сервисом (``save_index`` → ``load_index``). Отдельно проверяется
отказ: поиск по непроведённому индексу — ``IndexNotBuiltError``, а не пустой список,
который выглядел бы как «ничего не нашлось».
"""
import pytest

from backend.domain.chunking import ChunkStrategy
from backend.services.chunker import FixedSizeChunker, StructuralChunker
from backend.services.index_service import IndexNotBuiltError

#: Чанкер по стратегии — тем же значением, что уходит в БД и API.
CHUNKERS = {ChunkStrategy.FIXED: FixedSizeChunker,
            ChunkStrategy.STRUCTURAL: StructuralChunker}


def _chunks(documents, strategy=ChunkStrategy.STRUCTURAL, **kwargs):
    """Чанки тестовых документов одной стратегией (параметры окна — по надобности)."""
    chunker = CHUNKERS[strategy](**kwargs)
    return [chunk for document in documents for chunk in chunker.chunk(document)]


@pytest.fixture
def indexed(index_service, documents):
    """Индекс со структурными чанками трёх тестовых документов."""
    chunks = _chunks(documents)
    report = index_service.index_chunks(chunks, "structural")
    return index_service, chunks, report


@pytest.mark.slow
def test_index_chunks_reports_counts_and_dimension(indexed):
    """Отчёт индексации: число чанков, эмбеддингов, размерность и время."""
    service, chunks, report = indexed
    assert report["indexed"] == len(chunks)
    assert report["embeddings"] == len(chunks)
    assert report["dimension"] == service.embedder.dimension
    assert report["embed_ms"] >= 0 and report["index_ms"] >= 0
    assert report["saved_to"].endswith("structural.index")


def test_chunk_rows_get_embedding_id(indexed):
    """``embedding_id`` строки равен её ``id``: вектора FAISS кладутся под этими id."""
    service, _chunks_list, _report = indexed
    rows = service.store.chunks("structural")
    assert rows
    assert all(row["embedding_id"] == row["id"] for row in rows)


def test_search_returns_hits_in_score_order(indexed):
    """Поиск возвращает попадания с метаданными чанка по убыванию оценки."""
    service, _chunks_list, _report = indexed
    hits = service.search("структурный чанкинг секции markdown", top_k=3,
                          strategy="structural")
    assert hits
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert [hit["rank"] for hit in hits] == list(range(1, len(hits) + 1))
    for hit in hits:
        assert hit["chunk_id"] and hit["source"] and hit["content"]
        assert hit["preview"]
        assert hit["strategy"] == "structural"
        assert isinstance(hit["token_count"], int)


def test_search_respects_top_k(indexed):
    """``top_k`` ограничивает число попаданий."""
    service, _chunks_list, _report = indexed
    assert len(service.search("раздел", top_k=1, strategy="structural")) == 1


def test_search_classifies_empty_index_as_error(index_service):
    """Поиск по непроведённому индексу — ``IndexNotBuiltError``, а не пустой список."""
    with pytest.raises(IndexNotBuiltError):
        index_service.search("что угодно", strategy="fixed")


def test_index_round_trip_through_file(indexed):
    """Индекс, записанный в файл, читается новым сервисом и даёт те же попадания."""
    service, _chunks_list, _report = indexed
    before = [hit["chunk_id"] for hit in service.search("раздел", top_k=3,
                                                       strategy="structural")]
    fresh = type(service)(embedder=service.embedder, store=service.store,
                         index_dir=service.path_for("structural").parent)
    loaded = fresh.load_index("structural")
    assert loaded["loaded"] is True and loaded["vectors"] > 0
    after = [hit["chunk_id"] for hit in fresh.search("раздел", top_k=3,
                                                     strategy="structural")]
    assert after == before


def test_load_index_without_file_is_not_an_error(index_service):
    """Отсутствующий файл индекса — не ошибка: прогонов ещё не было."""
    result = index_service.load_index("fixed")
    assert result["loaded"] is False
    assert result["vectors"] == 0
    assert result["path"].endswith("fixed.index")


def test_clear_index_removes_vectors_file_and_rows(indexed):
    """Очистка убирает векторы, файл и строки таблицы; поиск после неё — ошибка."""
    service, _chunks_list, _report = indexed
    path = service.path_for("structural")
    assert path.exists()
    removed = service.clear_index("structural")
    assert removed["removed"]["structural"] > 0
    assert path.exists() is False
    assert service.store.count("structural") == 0
    assert service.index_size("structural") == 0
    with pytest.raises(IndexNotBuiltError):
        service.search("раздел", strategy="structural")


def test_index_chunks_appends_to_existing_index(index_service, documents):
    """Повторная индексация ДОПИСЫВАЕТ индекс, а не чистит его неявно."""
    chunks = _chunks(documents)
    first = index_service.index_chunks(chunks, "structural")
    second = index_service.index_chunks(chunks, "structural")
    assert first["indexed"] == second["indexed"]
    assert index_service.index_size("structural") == 2 * len(chunks)


def test_stats_describe_both_strategies(index_service, documents):
    """Статистика обеих стратегий есть всегда, даже когда индексов нет."""
    empty = index_service.stats()
    assert set(empty) == {"fixed", "structural"}
    assert empty["fixed"]["chunks"] == 0 and empty["fixed"]["index_file"] is None

    index_service.index_chunks(_chunks(documents, ChunkStrategy.STRUCTURAL),
                               "structural")
    stats = index_service.get_stats("structural")
    assert stats["chunks"] >= 3
    assert stats["documents"] == 3
    assert stats["tokens_total"] == sum(
        chunk["token_count"] for chunk in index_service.store.chunks("structural"))
    assert stats["with_section"] > 0
    assert sum(stats["histogram"].values()) == stats["chunks"]
    assert stats["index_bytes"] > 0
    # Векторов в FAISS столько же, сколько строк таблицы: расхождение означало бы,
    # что индекс и метаданные разошлись (например, их записал другой процесс).
    assert stats["index_vectors"] == stats["chunks"]
    assert empty["fixed"]["index_vectors"] == 0


def test_sample_chunks_returns_examples(index_service, documents):
    """Примеры чанков отдаются в порядке id и с ограничением."""
    index_service.index_chunks(_chunks(documents), "structural")
    samples = index_service.sample_chunks("structural", limit=2)
    assert len(samples) == 2
    assert samples[0]["id"] < samples[1]["id"]


def test_save_all_writes_both_indexes(index_service, documents):
    """``save_all`` пишет оба загруженных индекса и сообщает объём."""
    index_service.index_chunks(_chunks(documents, ChunkStrategy.FIXED), "fixed")
    index_service.index_chunks(_chunks(documents, ChunkStrategy.STRUCTURAL), "structural")
    written = index_service.save_all()
    assert set(written) == {"fixed", "structural"}
    assert all(item["written"] for item in written.values())
    assert all(item["vectors"] > 0 for item in written.values())


def test_load_all_reads_both_indexes(index_service, documents):
    """``load_all`` читает оба индекса с диска (это и есть путь перезапуска)."""
    index_service.index_chunks(_chunks(documents, ChunkStrategy.FIXED), "fixed")
    index_service.index_chunks(_chunks(documents, ChunkStrategy.STRUCTURAL), "structural")
    index_service.save_all()
    fresh = type(index_service)(embedder=index_service.embedder,
                               store=index_service.store,
                               index_dir=index_service.path_for("fixed").parent)
    loaded = fresh.load_all()
    assert set(loaded) == {"fixed", "structural"}
    assert all(item["loaded"] and item["vectors"] > 0 for item in loaded.values())


def test_chunks_are_chunked_with_fixed_strategy_too(index_service, documents):
    """Фиксированная стратегия индексируется тем же путём и ищется так же."""
    chunks = _chunks(documents, ChunkStrategy.FIXED, size_tokens=60)
    report = index_service.index_chunks(chunks, "fixed")
    assert report["indexed"] == len(chunks)
    hits = index_service.search("абзац про поиск", top_k=2, strategy="fixed")
    assert len(hits) == 2
    assert all(hit["section"] == "" for hit in hits)


def test_index_chunks_with_empty_list_writes_nothing(index_service):
    """Пустой список чанков не создаёт ни строк, ни файла индекса."""
    report = index_service.index_chunks([], "fixed")
    assert report["indexed"] == 0 and report["saved_to"] is None
    assert index_service.store.count("fixed") == 0


def test_document_chunk_content_is_slice_of_document(index_service, documents):
    """Чанк в индексе — срез документа: границы и текст согласованы."""
    index_service.index_chunks(_chunks(documents), "structural")
    by_source = {document.source: document for document in documents}
    for row in index_service.store.chunks("structural"):
        text = by_source[row["source"]].text
        assert text[row["start_char"]:row["end_char"]] == row["content"]
