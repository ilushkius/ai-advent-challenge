"""Блоки документов: markdown-секции, ``ast``-секции кода и абзацы (день 21).

Проверяется главное свойство блоков: они ДЕЛЯТ текст — без пропусков и перекрытий.
Именно на этом свойстве держится и точность ``start_char``/``end_char`` чанков, и
метрика покрытия: если бы секция первого уровня забирала свои подсекции, один и тот
же текст попал бы в индекс дважды, а если бы блоки задавались только ``node.end_lineno``
узлов — часть файла выпала бы совсем.
"""
import pytest

from backend.domain.chunking import (
    Block,
    BlockKind,
    ChunkStrategy,
    detect_kind,
    iter_blocks,
    resolve_strategy,
    strategy_values,
)
from backend.domain.document_sources import Document
from indexing_fakes import CODE_TEXT, MARKDOWN_TEXT, PLAIN_TEXT


def test_detect_kind_by_extension():
    """Вид документа определяется расширением файла."""
    assert detect_kind("day20-readme.md") is BlockKind.MARKDOWN
    assert detect_kind("day9-backend-context_fsm.py") is BlockKind.CODE
    assert detect_kind("notes.txt") is BlockKind.PLAIN
    assert detect_kind("AGENTS.md") is BlockKind.MARKDOWN


def test_strategy_values_and_resolution():
    """Значения стратегий и разбор строки (``None`` — значение не стратегия)."""
    assert strategy_values() == ("fixed", "structural")
    assert resolve_strategy("FIXED") is ChunkStrategy.FIXED
    assert resolve_strategy(" structural ") is ChunkStrategy.STRUCTURAL
    assert resolve_strategy("окно") is None
    assert resolve_strategy(None) is None


def test_empty_text_has_no_blocks():
    """Пустой текст не даёт ни одного блока."""
    for kind in BlockKind:
        assert iter_blocks("", kind) == []


# ---------- markdown ----------
def _markdown_blocks(text=MARKDOWN_TEXT):
    return iter_blocks(text, BlockKind.MARKDOWN)


def test_markdown_sections_and_levels():
    """Секции markdown идут по заголовкам, уровень берётся из числа ``#``."""
    blocks = _markdown_blocks()
    titles = [(block.title, block.level) for block in blocks]
    assert titles == [
        ("Правила дня", 1),
        ("Раздел A", 2),
        ("Вложенный подраздел A.1", 3),
        ("Раздел B", 2),
    ]


def test_markdown_blocks_partition_text():
    """Секции markdown делят текст: без пропусков и без перекрытий."""
    blocks = _markdown_blocks()
    assert blocks[0].start_char == 0
    assert blocks[-1].end_char == len(MARKDOWN_TEXT)
    for block in blocks:
        assert MARKDOWN_TEXT[block.start_char:block.end_char] == block.text
    for previous, following in zip(blocks, blocks[1:]):
        assert previous.end_char == following.start_char


def test_markdown_preamble_before_first_heading():
    """Текст до первого заголовка — преамбула с пустым заголовком."""
    blocks = _markdown_blocks("вступление без заголовка\n\n# Первый\n\nтело\n")
    assert blocks[0].title == ""
    assert blocks[0].level == 0
    assert blocks[0].text.startswith("вступление")
    assert blocks[1].title == "Первый"


def test_markdown_without_headings_is_single_block():
    """Текст без заголовков — один блок: резать его структурно нечем."""
    blocks = _markdown_blocks("просто текст\nбез заголовков\n")
    assert len(blocks) == 1
    assert blocks[0].title == ""
    assert blocks[0].text == "просто текст\nбез заголовков\n"


# ---------- код ----------
def test_code_sections_by_ast():
    """Секции кода: модульная преамбула, класс и функции (с декоратором)."""
    blocks = iter_blocks(CODE_TEXT, BlockKind.CODE)
    assert [block.title for block in blocks] == ["module", "State", "helper", "decorated"]
    assert [block.level for block in blocks] == [0, 1, 1, 1]
    assert blocks[1].text.startswith("class State")
    # Секция функции с декоратором начинается со строки декоратора.
    assert blocks[3].text.startswith("@staticmethod")


def test_code_blocks_partition_text():
    """Секции кода делят файл целиком: модульные переменные не выпадают."""
    blocks = iter_blocks(CODE_TEXT, BlockKind.CODE)
    assert blocks[0].start_char == 0
    assert blocks[-1].end_char == len(CODE_TEXT)
    covered = "".join(block.text for block in blocks)
    assert covered == CODE_TEXT


def test_code_without_definitions_is_single_block():
    """Python без top-level определений — один блок: резать нечего."""
    text = "import os\n\nLIMIT = 3\n"
    blocks = iter_blocks(text, BlockKind.CODE)
    assert len(blocks) == 1
    assert blocks[0].title == "module"
    assert blocks[0].text == text


def test_broken_python_falls_back_to_line_matching():
    """Битый Python: ``ast`` падает, секции ищутся по строкам-шаблонам."""
    text = "def broken(\n    остаток модуля\n"
    blocks = iter_blocks(text, BlockKind.CODE)
    assert [block.title for block in blocks] == ["broken"]
    assert blocks[0].text == text


def test_text_without_code_markers_is_single_block():
    """Не-Python текст без признаков секций — один блок во всю ширину."""
    text = "просто заметка\nи ещё строка\n"
    blocks = iter_blocks(text, BlockKind.CODE)
    assert len(blocks) == 1
    assert blocks[0].title == "module"
    assert blocks[0].text == text


def test_block_text_matches_offsets_for_code():
    """``text[start:end] == block.text`` — блок это срез исходника, а не склейка."""
    for block in iter_blocks(CODE_TEXT, BlockKind.CODE):
        assert CODE_TEXT[block.start_char:block.end_char] == block.text


# ---------- plain text ----------
def test_plain_blocks_are_paragraphs():
    """Абзацы plain text разделяются пустой строкой."""
    blocks = iter_blocks(PLAIN_TEXT, BlockKind.PLAIN)
    assert len(blocks) == 3
    assert all(block.title == "" and block.level == 0 for block in blocks)
    assert blocks[0].text.startswith("Первый абзац")
    assert blocks[2].text.startswith("Третий абзац")
    for block in blocks:
        assert PLAIN_TEXT[block.start_char:block.end_char] == block.text


def test_plain_text_without_blank_lines_is_single_block():
    """Текст без пустых строк — один блок."""
    blocks = iter_blocks("одна строка\nвторая строка\n", BlockKind.PLAIN)
    assert len(blocks) == 1
    assert blocks[0].text == "одна строка\nвторая строка\n"


def test_whitespace_only_text_has_no_plain_blocks():
    """Текст из одних пробелов и переводов строк не даёт блоков."""
    assert iter_blocks("   \n\n  \n", BlockKind.PLAIN) == []


@pytest.mark.parametrize("kind", list(BlockKind))
def test_block_is_immutable(kind):
    """Блок — неизменяемое значение: чанкер не правит структуру документа."""
    block = Block("title", 1, 0, 1, "x")
    with pytest.raises(Exception):
        block.title = "другое"


def test_document_kind_from_source_name():
    """Вид документа для чанкера берётся из имени файла документа."""
    document = Document(source="rules.md", path=None, title="t", kind="docs",
                        language="ru", text=MARKDOWN_TEXT,
                        chars=len(MARKDOWN_TEXT), truncated=False)
    assert detect_kind(document.source) is BlockKind.MARKDOWN
