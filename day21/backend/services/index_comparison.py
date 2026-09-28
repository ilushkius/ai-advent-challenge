"""Сборка метрик сравнения стратегий (день 21).

Прогон индексации (``index_runner.py``) собирает ЧИСЛА: сколько чанков дала каждая
стратегия, какие попадания принесли тестовые запросы, сколько времени заняли
эмбеддинги. Этот модуль складывает из них метрики прогона — ту структуру, которая
уходит в колонку ``index_runs.metrics``, в интерфейс и в отчёт.

Формы метрик и отчёта описаны здесь же, потому что они — один контракт:
``metrics[strategy]`` = ``{"stats", "coverage", "structure", "search", "timing"}``
— ровно то, что читает ``index_metrics.comparison_rows`` для таблицы сравнения.

Модуль без БД и без сети: только домен и структуры данных.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from ..core import config
from ..domain.chunking import strategy_values
from ..domain.document_sources import Document
from ..domain.index_metrics import (
    comparison_rows,
    coverage_ratio,
    precision_recall,
    structure_ratio,
)
from ..domain.index_scenarios import DEMO_QUERIES

__all__ = ["build_metrics", "documents_meta", "queries_metrics", "stats_of", "summary"]

#: Поля статистики, которые в метриках прогона дублировали бы отчёт, а не дополняли.
_HEAVY_STAT_FIELDS = ("sources", "histogram", "index_file")


def build_metrics(*, documents: Sequence[Document], chunks: Mapping[str, Sequence[Any]],
                  results: Mapping[str, Mapping[str, Any]],
                  searches: Mapping[str, Sequence[Mapping[str, Any]]],
                  stats: Mapping[str, Mapping[str, Any]],
                  embedding_model: str) -> dict:
    """Метрики прогона: документы, запросы, по стратегии — объёмы, покрытие, поиск.

    Покрытие считается по объединению интервалов чанков каждого документа, поэтому
    перекрытие окон фиксированной стратегии не удваивает покрытие; знаменатель —
    полная длина документа, включая куски, не попавшие ни в один чанк.
    """
    chars_by_source = {document.source: document.chars for document in documents}
    metrics: Dict[str, Any] = {
        "documents": documents_meta(documents),
        "embedding_model": embedding_model,
        "documents_total_chars": sum(chars_by_source.values()),
        "queries": queries_metrics(searches),
    }
    for strategy in strategy_values():
        if strategy not in chunks:
            # Стратегию не прогоняли (одиночная индексация) — и в метриках её нет:
            # строка «0 чанков» описывала бы не результат, а отсутствие прогона.
            continue
        items = list(chunks.get(strategy, []))
        intervals = {
            document.source: [
                (chunk.start_char, chunk.end_char)
                for chunk in items if chunk.source == document.source
            ]
            for document in documents
        }
        metrics[strategy] = {
            "stats": stats_of(stats.get(strategy, {})),
            "coverage": coverage_ratio(intervals, chars_by_source),
            "structure": structure_ratio([chunk.to_dict() for chunk in items]),
            "search": precision_recall(list(searches.get(strategy, [])),
                                       config.INDEX_DEFAULT_TOP_K),
            "timing": _timing_of(results.get(strategy, {})),
        }
    if len(metrics.get("fixed", {})) and len(metrics.get("structural", {})):
        metrics["comparison"] = comparison_rows(metrics["fixed"], metrics["structural"])
    return metrics


def documents_meta(documents: Sequence[Document]) -> List[dict]:
    """Метаданные документов для метрик прогона и отчёта."""
    return [
        {
            "source": document.source,
            "kind": document.kind,
            "language": document.language,
            "title": document.title,
            "chars": document.chars,
            "truncated": document.truncated,
        }
        for document in documents
    ]


def stats_of(stats: Mapping[str, Any]) -> dict:
    """Статистика стратегии без источников, гистограммы и пути к файлу.

    Эти три поля живут в отчёте отдельными разделами (гистограмма — графиком), а в
    метриках прогона они дублировали бы сами себя: список из 25 источников и пять
    бакетов на каждой стратегии.
    """
    return {key: value for key, value in stats.items()
            if key not in _HEAVY_STAT_FIELDS}


def _timing_of(result: Mapping[str, Any]) -> dict:
    """Время стратегии с полем ``duration_ms`` — полным временем её прогона.

    Отчёт ``IndexService.index_chunks`` сообщает время эмбеддингов и записи индекса
    по отдельности; строка таблицы сравнения «индексация, мс» читает именно
    ``duration_ms``, и без этого поля в отчёте стоял бы прочерк вместо суммы.
    """
    timing = dict(result)
    timing.setdefault("duration_ms", int(timing.get("embed_ms") or 0)
                      + int(timing.get("index_ms") or 0))
    return timing


def queries_metrics(searches: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[dict]:
    """Сводит результаты поиска по стратегиям в одну запись на запрос.

    Форма «один запрос — обе стратегии рядом» нужна интерфейсу и отчёту: рядом видно,
    что нашла каждая стратегия по одному и тому же вопросу.
    """
    metrics: list[dict] = []
    for position, query in enumerate(DEMO_QUERIES):
        entry: Dict[str, Any] = {
            "query": query.query,
            "note": query.note,
            "expected_sources": list(query.expected_sources),
        }
        for strategy, entries in searches.items():
            item = entries[position] if position < len(entries) else {}
            entry[strategy] = {
                "hits": list(item.get("hits") or []),
                "relevant_total": int(item.get("relevant_total") or 0),
            }
        metrics.append(entry)
    return metrics


def summary(metrics: Mapping[str, Any]) -> str:
    """Короткая сводка для лога: чанки и качество поиска по стратегиям."""
    parts: list[str] = []
    for strategy in strategy_values():
        entry = metrics.get(strategy)
        if not isinstance(entry, Mapping):
            continue
        search = entry.get("search") or {}
        stats = entry.get("stats") or {}
        parts.append(f"{strategy}: {stats.get('chunks', 0)} чанков, "
                     f"precision@k {search.get('precision_at_k', 0)}")
    return "; ".join(parts) if parts else "метрик нет"
