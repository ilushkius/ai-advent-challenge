"""Блок найденных фрагментов индекса в системном промпте (день 21).

Когда ход агента нашёл фрагменты в индексе документов, они уходят модели отдельным
системным блоком — рядом с блоками памяти, состояния задачи, данных MCP, результата
пайплайна и оркестрации. Блок короткий: источник, секция, оценка близости и выдержка.
Смысл — «вот подтверждение из документов проекта, отвечай по нему и не выдумывай
того, чего в этих фрагментах нет».

Пустой список попаданий блока не даёт: сообщать модели нечего, и «данных нет» в
промпте только запутало бы ответ.

Модуль чистый: только стандартная библиотека (эталон — ``pipeline_prompt.py``).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["INDEX_BLOCK_FOOTER", "INDEX_BLOCK_HEADER", "render_index_block"]

INDEX_BLOCK_HEADER = "## Контекст из индекса документов"
INDEX_BLOCK_FOOTER = (
    "Используй эти фрагменты как источник правды и не выдумывай того, чего в них нет."
)

#: Длина выдержки из чанка в блоке промпта (полный текст чанка в промпт не идёт).
EXCERPT_CHARS = 300


def render_index_block(hits: Sequence[Mapping[str, Any]]) -> str:
    """Системный блок с найденными фрагментами (``""`` — попаданий нет)."""
    lines = [_hit_line(hit) for hit in hits]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "\n".join([INDEX_BLOCK_HEADER, *lines, INDEX_BLOCK_FOOTER])


def _hit_line(hit: Mapping[str, Any]) -> str:
    """Строка одного попадания: источник, секция, оценка и выдержка.

    Поля читаются устойчиво: у попадания может не быть секции (стратегия ``fixed``)
    или оценки, и строка обязана остаться читаемой — иначе блок промпта падал бы на
    самом слабом попадании.
    """
    source = str(hit.get("source") or "—")
    section = str(hit.get("section") or "").strip()
    head = f"- [{source}]" + (f" «{section}»" if section else "")
    score = hit.get("score")
    if isinstance(score, (int, float)):
        head += f" (score {float(score):.2f})"
    excerpt = _excerpt(str(hit.get("content") or hit.get("preview") or ""))
    return f"{head}: {excerpt}" if excerpt else head


def _excerpt(text: str) -> str:
    """Выдержка из чанка: первая строка до ``EXCERPT_CHARS`` символов."""
    compact = " ".join(text.split())
    if len(compact) <= EXCERPT_CHARS:
        return compact
    return compact[:EXCERPT_CHARS].rstrip() + "…"
