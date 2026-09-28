"""Структура документа: разбиение текста на блоки (день 21).

Чанкер работает не с сырым текстом, а с БЛОКАМИ — осмысленными единицами
документа. Отсюда и точность решения задачи «сравнить стратегии»: фиксированная
стратегия набирает окна ИЗ блоков, поэтому её чанки никогда не начинаются на
середине абзаца; структурная режет по блокам-секциям, поэтому знает заголовок
раздела; и у обоих чанков ``start_char``/``end_char`` — настоящие позиции в
исходном тексте, а не пересобранные строки.

Три вида блоков — по виду документа; в каждом виде блоки делят текст БЕЗ пропусков
и перекрытий (чанк — это срез текста, а не склейка кусков):

- ``MARKDOWN`` — секция от заголовка ATX (``#``…``######``) до следующего заголовка
  любого уровня; текст до первого заголовка — преамбула. Иерархия не разворачивается
  в перекрывающиеся секции: уровень заголовка уезжает в ``level`` (и дальше в
  ``section_level`` чанка), а текст секции остаётся уникальным;
- ``CODE`` — top-level ``def``/``async def``/``class`` вместе с декораторами,
  найденные через ``ast``; секция тянется до начала следующей, последняя — до конца
  файла; текст до первого определения (импорты, докстринг модуля) — блок ``module``;
- ``PLAIN`` — абзацы, разделённые пустой строкой.

Модуль чистый: ``ast``, ``enum``, ``re`` и ``dataclasses``.
"""
from __future__ import annotations

import ast
import enum
import re
from dataclasses import dataclass

__all__ = [
    "Block",
    "BlockKind",
    "ChunkStrategy",
    "detect_kind",
    "iter_blocks",
    "resolve_strategy",
    "strategy_values",
]


class ChunkStrategy(enum.Enum):
    """Стратегия чанкинга; значения — строки для БД, API и отчёта без маппинга."""

    FIXED = "fixed"
    STRUCTURAL = "structural"


def strategy_values() -> tuple[str, ...]:
    """Значения стратегий в порядке объявления (для схем, UI и валидации)."""
    return tuple(strategy.value for strategy in ChunkStrategy)


def resolve_strategy(value) -> ChunkStrategy | None:
    """Стратегия по строке; ``None`` — значение не стратегия (решает вызывающий)."""
    try:
        return ChunkStrategy(str(value).strip().lower())
    except ValueError:
        return None


class BlockKind(enum.Enum):
    """Вид документа: от него зависит, как текст режется на блоки."""

    MARKDOWN = "markdown"
    CODE = "code"
    PLAIN = "plain"


def detect_kind(path_or_source: str) -> BlockKind:
    """Вид документа по расширению файла (``.md`` → markdown, ``.py`` → code)."""
    lowered = str(path_or_source).strip().lower()
    if lowered.endswith(".md"):
        return BlockKind.MARKDOWN
    if lowered.endswith(".py"):
        return BlockKind.CODE
    return BlockKind.PLAIN


@dataclass(frozen=True)
class Block:
    """Осмысленная единица документа: заголовок, уровень и границы в тексте."""

    title: str
    level: int
    start_char: int
    end_char: int
    text: str


#: Заголовок markdown: от одного до шести ``#`` и текст после них.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
#: Абзац plain text отделяется пустой строкой.
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
#: Запасные признаки начала секции кода, когда ``ast`` не справился.
_CODE_LINE_RE = re.compile(r"^(def |class |async def |@)")


def iter_blocks(text: str, kind: BlockKind) -> list[Block]:
    """Блоки документа по его виду (пустой текст → пустой список)."""
    if not text:
        return []
    if kind is BlockKind.MARKDOWN:
        return _markdown_blocks(text)
    if kind is BlockKind.CODE:
        return _code_blocks(text)
    return _plain_blocks(text)


def line_offsets(text: str) -> list[int]:
    """Позиция начала каждой строки плюс позиция конца текста.

    Смещения считаются один раз: блоки задаются строками, а чанки — символами,
    и пересчёт «строка → символ» на каждый блок был бы лишней работой.
    """
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    if offsets[-1] != len(text):
        offsets[-1] = len(text)
    return offsets


def _markdown_blocks(text: str) -> list[Block]:
    """Секции markdown: от заголовка до СЛЕДУЮЩЕГО заголовка любого уровня.

    Секции — разбиение, а не иерархия: «секция заголовка первого уровня вместе с
    подсекциями» перекрывала бы подсекции, и один и тот же текст попал бы в индекс
    дважды. Уровень заголовка при этом не теряется — он лежит в ``level`` и уезжает
    в метаданные чанка (``section_level``), поэтому видно, что секция была вложенной.
    """
    offsets = line_offsets(text)
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    if not headings:
        return [Block("", 0, 0, len(text), text)]
    blocks: list[Block] = []
    if headings[0][0] > 0:
        blocks.append(_block(text, offsets, 0, headings[0][0], "", 0))
    for position, (line_index, level, title) in enumerate(headings):
        next_heading = headings[position + 1][0] if position + 1 < len(headings) else None
        end_line = next_heading if next_heading is not None else len(lines)
        blocks.append(_block(text, offsets, line_index, end_line, title, level))
    return blocks


def _code_blocks(text: str) -> list[Block]:
    """Секции кода: top-level определения (``ast``), иначе — по строкам-шаблонам.

    Секция тянется от своего определения до начала следующего, а последняя — до
    конца файла: так блоки делят текст без пропусков, и ни модульная переменная
    между функциями, ни блок ``if __name__ == "__main__"`` в конце не теряются.
    Границу ``node.end_lineno`` для этого использовать нельзя — между узлами
    остались бы дыры, а чанк с дырой внутри перестал бы быть срезом текста.
    """
    offsets = line_offsets(text)
    spans = _ast_sections(text)
    if spans is None:
        spans = _regex_sections(text)
    if not spans:
        return [Block("module", 0, 0, len(text), text)]
    blocks: list[Block] = []
    first_line = spans[0][0]
    if first_line > 1:
        blocks.append(_block(text, offsets, 0, first_line - 1, "module", 0))
    for position, (start_line, title) in enumerate(spans):
        next_line = (spans[position + 1][0] - 1) if position + 1 < len(spans) else None
        end_line = next_line if next_line is not None else len(offsets) - 1
        blocks.append(_block(text, offsets, start_line - 1, end_line, title, 1))
    return blocks


def _ast_sections(text: str) -> list[tuple[int, str]] | None:
    """Секции по ``ast``: (строка начала, имя) или ``None`` при сбое разбора."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    sections: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno
        if node.decorator_list:
            start = min(decorator.lineno for decorator in node.decorator_list)
        sections.append((start, node.name))
    return sections


def _regex_sections(text: str) -> list[tuple[int, str]]:
    """Секции по строкам-шаблонам: то же, что ``ast``, но без разбора кода."""
    lines = text.splitlines()
    sections: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not _CODE_LINE_RE.match(line) or line.startswith((" ", "\t")):
            continue
        title = line.strip().rstrip(":").split("(")[0].replace("async ", "")
        title = title.replace("def ", "").replace("class ", "").strip() or "code"
        sections.append((index + 1, title))
    return sections


def _plain_blocks(text: str) -> list[Block]:
    """Абзацы plain text: блоки между пустыми строками.

    Разделитель (пустая строка) достаётся ПРЕДЫДУЩЕМУ абзацу, а пустой абзац — не
    блок вовсе: так блоки делят текст без дырок (покрытие чанков получается честным),
    и ни один чанк не состоит из одних переводов строк.
    """
    spans: list[tuple[int, int]] = []
    position = 0
    for match in _BLANK_LINE_RE.finditer(text):
        if match.start() > position:
            spans.append((position, match.end()))
        position = match.end()
    if text[position:].strip():
        spans.append((position, len(text)))
    if not spans:
        return []
    if spans[0][0] > 0:
        spans[0] = (0, spans[0][1])  # ведущие пустые строки — первому абзацу
    blocks: list[Block] = []
    for index, (start, _end) in enumerate(spans):
        end = spans[index + 1][0] if index + 1 < len(spans) else len(text)
        if not text[start:end].strip():
            if blocks:
                blocks[-1] = _span_block(text, blocks[-1].start_char, end)
            continue
        blocks.append(_span_block(text, start, end))
    return blocks


def _span_block(text: str, start: int, end: int) -> Block:
    """Блок plain text по границам символов (заголовка у абзаца нет)."""
    return Block("", 0, start, end, text[start:end])


def _block(text: str, offsets: list[int], start_line: int, end_line: int,
           title: str, level: int) -> Block:
    """Блок по границам строк: ``start_line`` — с нуля, ``end_line`` — исключая.

    У секции кода ``start_line`` — строка первого декоратора (или определения),
    ``end_line`` — строка за последней строкой узла; у секции markdown —
    строка заголовка и строка следующего заголовка того же или меньшего уровня.
    """
    total = len(offsets) - 1
    first = max(0, min(start_line, total))
    last = max(first, min(end_line, total))
    start_char = offsets[first]
    end_char = offsets[last]
    return Block(title, level, start_char, end_char, text[start_char:end_char])
