"""Стратегия structural: секции, заголовки, слияние мелких и разрез длинных (день 21).

Проверяется контракт структурного чанкинга: чанк — это секция документа вместе с её
заголовком и уровнем; заголовок без тела не становится отдельным чанком; длинная
секция режется, но её заголовок достаётся ВСЕМ частям — иначе найти фрагмент по
секции было бы нельзя.
"""
from backend.domain.chunking import ChunkStrategy
from backend.domain.document_sources import Document
from backend.services.chunker import StructuralChunker, chunk_document, get_chunker
from indexing_fakes import CODE_TEXT, MARKDOWN_TEXT, PLAIN_TEXT, make_documents


def _document(source: str, text: str, title: str = "Документ", kind: str = "docs"):
    """Документ с заданным текстом — вход чанкера без сборки из репозитория."""
    return Document(source=source, path=None, title=title, kind=kind, language="ru",
                    text=text, chars=len(text), truncated=False)


def test_empty_text_gives_no_chunks():
    """Пустой документ не даёт чанков."""
    assert StructuralChunker().chunk(_document("empty.txt", "")) == []


def test_markdown_sections_become_chunks_with_titles():
    """Секции markdown дают чанки с заголовком и уровнем заголовка."""
    chunks = StructuralChunker(size_tokens=400, min_section_tokens=5).chunk(
        _document("rules.md", MARKDOWN_TEXT))
    sections = [(chunk.section, chunk.section_level) for chunk in chunks]
    assert ("Раздел A", 2) in sections
    assert ("Раздел B", 2) in sections
    assert ("Вложенный подраздел A.1", 3) in sections
    assert all(chunk.strategy == "structural" for chunk in chunks)


def test_code_sections_named_after_definitions():
    """Секции кода называются по определениям: модуль, класс, функции."""
    chunks = StructuralChunker(size_tokens=400, min_section_tokens=5).chunk(
        _document("sample.py", CODE_TEXT, kind="code"))
    assert [chunk.section for chunk in chunks] == ["module", "State", "helper", "decorated"]


def test_plain_text_has_no_sections():
    """У абзацев plain text секции нет: заголовков в них не бывает."""
    chunks = StructuralChunker(size_tokens=200, min_section_tokens=5).chunk(
        _document("notes.txt", PLAIN_TEXT))
    assert chunks
    assert all(chunk.section == "" and chunk.section_level == 0 for chunk in chunks)


def test_small_section_merges_with_next():
    """Заголовок без тела не становится чанком — он приклеивается к следующей секции."""
    text = "# Документ\n\n## Пустой\n\n## Настоящий раздел\n\n" + "слово " * 40 + "\n"
    chunker = StructuralChunker(size_tokens=400, min_section_tokens=20)
    chunks = chunker.chunk(_document("doc.md", text))
    assert len(chunks) == 1, "три мелкие части должны были слиться в одну секцию"
    merged = chunks[0]
    assert "## Пустой" in merged.content
    assert "## Настоящий раздел" in merged.content
    assert merged.section == "Документ", "подпись склеенной секции — первый заголовок"
    assert merged.token_count >= 20


def test_tiny_middle_section_merges_with_next():
    """Мелкая секция в середине не становится чанком и не теряется."""
    text = ("## A\n\n" + "слово " * 30 + "\n\n## B\n\nмало\n\n## C\n\n"
            + "слово " * 30 + "\n")
    chunker = StructuralChunker(size_tokens=400, min_section_tokens=20)
    chunks = chunker.chunk(_document("doc.md", text))
    assert len(chunks) == 2, "секции A и B+C: чанка из одной строки быть не должно"
    assert all(chunk.token_count >= 20 for chunk in chunks)
    assert "мало" in chunks[1].content and "## C" in chunks[1].content


def test_tiny_last_section_merges_with_previous():
    """Последняя мелкая секция приклеивается к предыдущей: чанк из строки — не чанк."""
    text = "## Большой\n\n" + "слово " * 60 + "\n\n## Хвост\n\nмало\n"
    chunker = StructuralChunker(size_tokens=400, min_section_tokens=20)
    chunks = chunker.chunk(_document("doc.md", text))
    assert len(chunks) == 1
    assert chunks[0].content.rstrip().endswith("мало")


def test_long_section_is_split_with_same_section():
    """Длинная секция режется, но заголовок остаётся у всех её частей."""
    text = "## Длинный раздел\n\n" + " ".join(f"слово{index}" for index in range(400))
    chunker = StructuralChunker(size_tokens=40, min_section_tokens=5)
    chunks = chunker.chunk(_document("doc.md", text))
    assert len(chunks) > 1
    assert all(chunk.section == "Длинный раздел" for chunk in chunks)
    assert all(chunk.section_level == 2 for chunk in chunks)
    assert all(chunk.token_count <= 40 for chunk in chunks)


def test_chunk_ids_unique_and_ordered():
    """``chunk_id`` уникален, чанки идут по возрастанию начала, границы точные."""
    chunker = StructuralChunker(size_tokens=40, min_section_tokens=5)
    text = MARKDOWN_TEXT + "\n\n" + PLAIN_TEXT
    chunks = chunker.chunk(_document("mixed.md", text))
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(set(ids)) == len(ids)
    assert ids[0].startswith("structural:mixed.md:")
    starts = [chunk.start_char for chunk in chunks]
    assert starts == sorted(starts)
    for chunk in chunks:
        assert text[chunk.start_char:chunk.end_char] == chunk.content


def test_single_section_document_stays_one_chunk():
    """Документ из одной секции остаётся одним чанком: сливать не с чем."""
    text = "# Только заголовок и тело\n\n" + "слово " * 60 + "\n"
    chunks = StructuralChunker(size_tokens=400, min_section_tokens=20).chunk(
        _document("doc.md", text))
    assert len(chunks) == 1
    assert chunks[0].section == "Только заголовок и тело"


def test_get_chunker_and_chunk_document_agree():
    """``chunk_document`` и фабрика дают один и тот же результат."""
    document = _document("rules.md", MARKDOWN_TEXT)
    direct = chunk_document(document, ChunkStrategy.STRUCTURAL)
    by_factory = get_chunker(ChunkStrategy.STRUCTURAL).chunk(document)
    assert [chunk.chunk_id for chunk in direct] == [chunk.chunk_id for chunk in by_factory]


def test_chunks_from_many_documents_are_distinguishable(tmp_path):
    """Чанки разных документов различаются идентификатором."""
    chunker = StructuralChunker(size_tokens=100, min_section_tokens=5)
    ids = [chunk.chunk_id for document in make_documents(tmp_path / "documents")
           for chunk in chunker.chunk(document)]
    assert len(set(ids)) == len(ids)
