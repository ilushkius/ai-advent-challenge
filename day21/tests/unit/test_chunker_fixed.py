"""Стратегия fixed: бюджет окна, перекрытие, точные границы и размеры (день 21).

Проверяется контракт фиксированного чанкинга: ни один чанк не длиннее
``size_tokens`` (иначе «окно» ничего не ограничивает), границы чанка — срез
исходного текста, а перекрытие реально соединяет соседние окна (иначе факт на
границе окон терялся бы при поиске).
"""
import pytest

from backend.domain.document_sources import Document
from backend.domain.index_metrics import coverage_ratio
from backend.services.chunker import FixedSizeChunker, get_chunker
from backend.domain.chunking import ChunkStrategy
from indexing_fakes import CODE_TEXT, MARKDOWN_TEXT, PLAIN_TEXT, make_documents


def _document(source: str, text: str, title: str = "Документ", kind: str = "docs"):
    """Документ с заданным текстом — вход чанкера без сборки из репозитория."""
    return Document(source=source, path=None, title=title, kind=kind, language="ru",
                    text=text, chars=len(text), truncated=False)


def _many_paragraphs(count: int = 12) -> str:
    """Plain-текст из коротких абзацев: окон в нём заведомо больше одного."""
    return "\n\n".join(f"Абзац номер {index}: слово раз два три." for index in range(count))


def test_empty_text_gives_no_chunks():
    """Пустой документ не даёт чанков."""
    chunker = FixedSizeChunker(size_tokens=50)
    assert chunker.chunk(_document("empty.txt", "")) == []


def test_chunk_budget_is_respected():
    """Ни один чанк не длиннее окна (в токенах) — ни на коротком, ни на длинном."""
    texts = {
        "rules.md": MARKDOWN_TEXT,
        "notes.txt": PLAIN_TEXT,
        "sample.py": CODE_TEXT,
        "long.txt": _many_paragraphs(30),
    }
    chunker = FixedSizeChunker(size_tokens=40, overlap_tokens=8)
    for source, text in texts.items():
        chunks = chunker.chunk(_document(source, text))
        assert chunks, f"{source}: чанков нет"
        for chunk in chunks:
            assert chunk.token_count <= 40, f"{source}: чанк длиннее окна"


def test_offsets_are_exact_slices_of_text():
    """``content`` каждого чанка — срез исходного текста по его же границам."""
    chunker = FixedSizeChunker(size_tokens=40, overlap_tokens=8)
    text = _many_paragraphs(20)
    for chunk in chunker.chunk(_document("long.txt", text)):
        assert text[chunk.start_char:chunk.end_char] == chunk.content
        assert chunk.start_char < chunk.end_char


def test_neighbouring_windows_overlap():
    """Перекрытие соединяет соседние окна: следующее начинается внутри предыдущего."""
    chunker = FixedSizeChunker(size_tokens=40, overlap_tokens=10)
    chunks = chunker.chunk(_document("long.txt", _many_paragraphs(12)))
    assert len(chunks) > 1, "нужно несколько окон, иначе перекрытие не проверить"
    assert all(len(chunk.content) > 0 for chunk in chunks)
    assert any(chunks[index + 1].start_char < chunks[index].end_char
               for index in range(len(chunks) - 1)), [
        (chunk.start_char, chunk.end_char) for chunk in chunks]


def test_full_coverage_of_document():
    """Интервалы чанков покрывают документ целиком (перекрытие не удваивает)."""
    chunker = FixedSizeChunker(size_tokens=40, overlap_tokens=10)
    text = _many_paragraphs(15)
    chunks = chunker.chunk(_document("long.txt", text))
    intervals = {"long.txt": [(chunk.start_char, chunk.end_char) for chunk in chunks]}
    assert coverage_ratio(intervals, {"long.txt": len(text)}) == 1.0


def test_huge_paragraph_is_split_inside():
    """Блок длиннее окна режется внутри себя: чанков больше одного."""
    text = " ".join(f"слово{index}" for index in range(200))
    chunker = FixedSizeChunker(size_tokens=20)
    chunks = chunker.chunk(_document("huge.txt", text))
    assert len(chunks) > 1
    assert all(chunk.token_count <= 20 for chunk in chunks)
    assert chunks[0].start_char == 0
    assert chunks[-1].end_char == len(text)


def test_fixed_chunks_have_no_section_metadata():
    """У фиксированного чанка секция пуста и уровень нулевой: структуру он не знает."""
    chunker = FixedSizeChunker(size_tokens=60)
    for chunk in chunker.chunk(_document("rules.md", MARKDOWN_TEXT)):
        assert chunk.section == ""
        assert chunk.section_level == 0
        assert chunk.strategy == "fixed"
        assert chunk.title == "Документ"


def test_chunk_ids_are_unique_and_ordered():
    """``chunk_id`` уникален, чанки идут по возрастанию начала."""
    chunker = FixedSizeChunker(size_tokens=30, overlap_tokens=10)
    chunks = chunker.chunk(_document("long.txt", _many_paragraphs(15)))
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(set(ids)) == len(ids)
    assert ids[0].startswith("fixed:long.txt:")
    starts = [chunk.start_char for chunk in chunks]
    assert starts == sorted(starts)


def test_get_chunker_returns_fixed_for_fixed_strategy():
    """Фабрика чанкеров отдаёт фиксированную стратегию по её значению."""
    assert isinstance(get_chunker(ChunkStrategy.FIXED), FixedSizeChunker)


def test_many_documents_do_not_share_chunk_ids(tmp_path):
    """Чанки разных документов различаются идентификатором (он содержит источник)."""
    chunker = FixedSizeChunker(size_tokens=40)
    documents = make_documents(tmp_path / "documents")
    ids = [chunk.chunk_id for document in documents
           for chunk in chunker.chunk(document)]
    assert len(set(ids)) == len(ids)
