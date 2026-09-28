"""Чанкинг документов: две стратегии, один интерфейс (день 21).

Стратегия — это правило «как из документа получить чанки», и сравнивать их нужно
на одном и том же входе, поэтому обе стратегии:

- режут документ на БЛОКИ домена (``domain/chunking.py``) и работают только с ними;
- считают токены общим счётчиком (``shared.token_counter.count_tokens``), а не
  оценкой «символы / 4»: «средний размер чанка» в отчёте — измеренное число;
- держат ``start_char``/``end_char`` точными: ``content`` каждого чанка — срез
  исходного текста, поэтому видно, откуда он взялся.

Стратегия **fixed** («фиксированный размер») набирает окно из блоков, пока суммарный
размер не упрётся в ``size_tokens`` (512), а следующее окно начинает с «хвоста»
предыдущего не длиннее ``overlap_tokens`` (50): перекрытие нужно, чтобы факт на
границе окон не терялся. Блок, который сам длиннее окна, режется внутри себя.

Стратегия **structural** («структурный») делает чанк из секции: заголовок раздела
markdown, определение в коде, абзац plain text. Секция короче
``min_section_tokens`` не становится чанком (заголовок без тела) — она
присоединяется к следующей, а если она последняя — к предыдущей. Секция длиннее
окна режется, но заголовок и уровень остаются у всех её частей.

Разница стратегий и есть содержание демонстрации: fixed даёт ровные чанки без
метаданных о структуре, structural — чанки разного размера с заголовком раздела.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Sequence, Tuple

from shared.token_counter import count_tokens

from ..core import config
from ..domain.chunking import Block, ChunkStrategy, detect_kind, iter_blocks
from ..domain.document_sources import Document

__all__ = [
    "Chunk",
    "FixedSizeChunker",
    "StructuralChunker",
    "chunk_document",
    "get_chunker",
]


@dataclass(frozen=True)
class Chunk:
    """Чанк документа: текст, его границы и метаданные для индекса."""

    chunk_id: str
    strategy: str
    source: str
    title: str
    section: str
    section_level: int
    content: str
    start_char: int
    end_char: int
    token_count: int

    def to_dict(self) -> dict:
        """Словарь чанка — форма, которую принимает ``ChunkStore.add_chunks``."""
        return {
            "chunk_id": self.chunk_id,
            "strategy": self.strategy,
            "source": self.source,
            "title": self.title,
            "section": self.section,
            "section_level": self.section_level,
            "content": self.content,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "token_count": self.token_count,
        }


@dataclass(frozen=True)
class _Piece:
    """Атомарная единица окна: срез текста, который дальше не делится."""

    start: int
    end: int
    tokens: int


def get_chunker(strategy: ChunkStrategy) -> "FixedSizeChunker | StructuralChunker":
    """Чанкер по стратегии (единственное место, знающее обе реализации)."""
    if strategy is ChunkStrategy.STRUCTURAL:
        return StructuralChunker()
    return FixedSizeChunker()


def chunk_document(document: Document, strategy: ChunkStrategy) -> List[Chunk]:
    """Чанки документа одной стратегией (точка входа для сервисов и тестов)."""
    return get_chunker(strategy).chunk(document)


class _BaseChunker:
    """Общее для стратегий: счётчик токенов и параметры окна."""

    strategy: ChunkStrategy
    size_tokens: int

    def __init__(self, size_tokens: int = config.CHUNK_SIZE_TOKENS,
                 counter: Callable[[str], int] = count_tokens) -> None:
        self.size_tokens = max(1, int(size_tokens))
        self.counter = counter

    def _blocks(self, document: Document) -> List[Block]:
        """Блоки документа по виду его файла."""
        return iter_blocks(document.text, detect_kind(document.source))

    def _chunk(self, document: Document, index: int, content: str,
               start_char: int, end_char: int, section: str,
               section_level: int) -> Chunk:
        """Чанк с измеренным числом токенов и собранным ``chunk_id``."""
        return Chunk(
            chunk_id=f"{self.strategy.value}:{document.source}:{index:04d}",
            strategy=self.strategy.value,
            source=document.source,
            title=document.title,
            section=section,
            section_level=int(section_level),
            content=content,
            start_char=int(start_char),
            end_char=int(end_char),
            token_count=self.counter(content),
        )


class FixedSizeChunker(_BaseChunker):
    """Фиксированное окно по токенам с перекрытием соседних окон."""

    strategy = ChunkStrategy.FIXED

    def __init__(self, size_tokens: int = config.CHUNK_SIZE_TOKENS,
                 overlap_tokens: int = config.CHUNK_OVERLAP_TOKENS,
                 counter: Callable[[str], int] = count_tokens) -> None:
        super().__init__(size_tokens=size_tokens, counter=counter)
        self.overlap_tokens = max(0, int(overlap_tokens))

    def chunk(self, document: Document) -> List[Chunk]:
        """Чанки фиксированного размера (пустой текст → пустой список)."""
        text = document.text
        pieces = self._pieces(document)
        chunks: list[Chunk] = []
        position = 0
        index = 0
        while position < len(pieces):
            start_char = pieces[position].start
            end_char = pieces[position].end
            next_piece = position + 1
            while (next_piece < len(pieces)
                   and self.counter(text[start_char:pieces[next_piece].end])
                   <= self.size_tokens):
                end_char = pieces[next_piece].end
                next_piece += 1
            chunks.append(self._chunk(document, index, text[start_char:end_char],
                                     start_char, end_char, "", 0))
            index += 1
            if next_piece >= len(pieces):
                break
            overlap_start = self._overlap_start(pieces, position, next_piece)
            position = max(overlap_start, position + 1)
        return chunks

    def _pieces(self, document: Document) -> List[_Piece]:
        """Атомарные срезы документа: блоки, слишком длинные — порезанные по окну."""
        pieces: list[_Piece] = []
        for block in self._blocks(document):
            if self.counter(block.text) <= self.size_tokens:
                if block.text.strip():
                    pieces.append(_Piece(block.start_char, block.end_char,
                                         self.counter(block.text)))
                continue
            for start, end, tokens in _window_text(document.text, block.start_char,
                                                   block.end_char, self.size_tokens,
                                                   self.counter):
                pieces.append(_Piece(start, end, tokens))
        return pieces

    def _overlap_start(self, pieces: Sequence[_Piece], start: int, end: int) -> int:
        """Начало перекрытия: сколько хвостовых блоков окна уложится в ``overlap_tokens``.

        Хвост собирается по блокам, а не по символам: перекрытие из половины
        абзаца дало бы чанк, начинающийся на середине предложения. Если даже
        последний блок окна длиннее перекрытия, перекрытием становится он один.
        """
        if end - start <= 1:
            return end
        position = end - 1
        total = pieces[position].tokens
        while position > start and total + pieces[position - 1].tokens <= self.overlap_tokens:
            position -= 1
            total += pieces[position].tokens
        return position


@dataclass(frozen=True)
class _Section:
    """Секция документа: границы в тексте, заголовок и его уровень."""

    start: int
    end: int
    title: str
    level: int


class StructuralChunker(_BaseChunker):
    """Чанк по секции документа: заголовок, определение кода или абзац."""

    strategy = ChunkStrategy.STRUCTURAL

    def __init__(self, size_tokens: int = config.CHUNK_SIZE_TOKENS,
                 min_section_tokens: int = config.CHUNK_MIN_SECTION_TOKENS,
                 counter: Callable[[str], int] = count_tokens) -> None:
        super().__init__(size_tokens=size_tokens, counter=counter)
        self.min_section_tokens = max(1, int(min_section_tokens))

    def chunk(self, document: Document) -> List[Chunk]:
        """Чанки по секциям: мелкие секции слиты, длинные — порезаны."""
        text = document.text
        chunks: list[Chunk] = []
        index = 0
        for section in self._sections(document):
            for start, end, _tokens in _window_text(text, section.start, section.end,
                                                    self.size_tokens, self.counter):
                chunks.append(self._chunk(document, index, text[start:end], start, end,
                                          section.title, section.level))
                index += 1
        return chunks

    def _sections(self, document: Document) -> List[_Section]:
        """Секции документа: секция короче минимума присоединяется к соседней.

        Заголовок без тела («## Раздел», за которым сразу следующий заголовок) не
        должен становиться чанком из одной строки: он приклеивается к следующей
        секции. Если он оказался последним, приклеивать не к чему — тогда к
        предыдущей, а если секция в документе одна, она остаётся как есть.
        """
        text = document.text
        sections = [_Section(block.start_char, block.end_char, block.title, block.level)
                    for block in self._blocks(document)
                    if block.text.strip() and self.counter(block.text) > 0]
        if not sections:
            return []
        merged: list[_Section] = []
        pending: _Section | None = None
        for section in sections:
            current = _merge_sections(pending, section)
            if self.counter(text[current.start:current.end]) < self.min_section_tokens:
                pending = current
                continue
            merged.append(current)
            pending = None
        if pending is not None:
            if merged:
                merged[-1] = _merge_sections(merged[-1], pending)
            else:
                merged.append(pending)
        return merged


def _merge_sections(first: _Section | None, second: _Section) -> _Section:
    """Склеивает две секции: границы — крайние, заголовок — от первой с текстом."""
    if first is None:
        return second
    title = first.title or second.title
    level = first.level if first.title else (second.level or first.level)
    return _Section(start=first.start, end=second.end, title=title, level=level)


def _window_text(text: str, start_char: int, end_char: int, size_tokens: int,
                 counter: Callable[[str], int]) -> List[Tuple[int, int, int]]:
    """Режет диапазон ``[start_char, end_char)`` на окна не длиннее ``size_tokens``.

    Границу окна ищет двоичный поиск по длине: ``count_tokens`` монотонен по длине
    префикса, поэтому «сколько символов помещается в окно» решается точно (оценка
    «по средней доле токенов» ошибалась бы на концах окон, а окно длиннее лимита
    ломало бы сравнение стратегий). Возвращает ``(start, end, tokens)``.
    """
    windows: list[tuple[int, int, int]] = []
    position = max(0, int(start_char))
    limit = max(position, int(end_char))
    while position < limit:
        end = _fit_end(text, position, limit, size_tokens, counter)
        windows.append((position, end, counter(text[position:end])))
        position = end
    return windows


def _fit_end(text: str, start: int, limit: int, size_tokens: int,
             counter: Callable[[str], int]) -> int:
    """Максимальный конец окна из ``start``, укладывающийся в ``size_tokens``."""
    if counter(text[start:limit]) <= size_tokens:
        return limit
    low, high = start + 1, limit
    while low < high:
        middle = (low + high + 1) // 2
        if counter(text[start:middle]) <= size_tokens:
            low = middle
        else:
            high = middle - 1
    return max(start + 1, low)
