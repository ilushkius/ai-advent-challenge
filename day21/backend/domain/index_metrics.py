"""Метрики сравнения стратегий чанкинга (день 21).

Вся арифметика сравнения — здесь, отдельно от прогона: прогон (``indexing_service``)
собирает числа, а этот модуль считает из них метрики и складывает их в строки
таблицы отчёта. Разделение то же, что у «поведение состояний FSM» и «чистая логика
решения» в дне 9: арифметику можно проверить таблицей тестов без БД, FAISS и модели.

Что именно меряется и зачем:

- **размер чанка** (``size_stats``, ``histogram``) — фиксированное окно должно
  давать ровные чанки, структурный — неровные: разброс σ и гистограмма это и
  показывают;
- **покрытие** (``coverage_ratio``) — доля символов документа, попавшая в чанки.
  Считается объединение интервалов, поэтому перекрытие соседних окон НЕ удваивает
  покрытие: иначе стратегия с ``overlap`` выглядела бы полнее, чем есть;
- **структура** (``structure_ratio``) — доля чанков с непустой секцией: у
  структурной стратегии она про то, что заголовок раздела доехал до метаданных;
- **качество поиска** (``precision_recall``) — попадания пяти тестовых запросов
  против ожидаемых источников (ground truth — имя файла-документа).

Модуль чистый: ``math``, ``statistics`` и стандартная библиотека.
"""
from __future__ import annotations

import statistics
from math import ceil
from typing import Any, Mapping, Sequence

__all__ = [
    "ascii_histogram",
    "comparison_rows",
    "coverage_ratio",
    "histogram",
    "precision_recall",
    "size_stats",
    "structure_ratio",
]

#: Границы бакетов гистограммы (в токенах): последний бакет — «513+».
DEFAULT_BINS: tuple[int, ...] = (128, 256, 384, 512)

#: Ширина текстовой гистограммы в символах (пропорциональная шкала).
CHART_WIDTH = 40

#: Подпись «данных нет»: пустая гистограмма в отчёте не должна выглядеть нулём.
NO_DATA = "нет данных"


def size_stats(token_counts: Sequence[int]) -> dict[str, Any]:
    """Статистика размеров чанков: count, avg, median, std, min, max (1 знак).

    ``std`` — генеральное отклонение (совокупность — все чанки индекса, а не
    выборка из них), поэтому ``pstdev``: выборочное отклонение завышало бы разброс.
    """
    values = [int(value) for value in token_counts]
    if not values:
        return {"count": 0, "avg": 0.0, "median": 0.0, "std": 0.0, "min": 0, "max": 0}
    return {
        "count": len(values),
        "avg": round(statistics.fmean(values), 1),
        "median": round(statistics.median(values), 1),
        "std": round(statistics.pstdev(values), 1) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def histogram(token_counts: Sequence[int],
              bins: Sequence[int] = DEFAULT_BINS) -> dict[str, int]:
    """Распределение размеров чанков по бакетам ``"0-128"`` … ``"513+"``.

    Верхняя граница бакета включается в него самого (``128`` → ``"0-128"``), поэтому
    бакеты не перекрываются и покрывают все положительные размеры.
    """
    keys = _bucket_keys(bins)
    counts = {key: 0 for key in keys}
    for value in token_counts:
        size = max(0, int(value))
        placed = False
        for position, edge in enumerate(bins):
            if size <= int(edge):
                counts[keys[position]] += 1
                placed = True
                break
        if not placed:
            counts[keys[-1]] += 1
    return counts


def _bucket_keys(bins: Sequence[int]) -> list[str]:
    """Подписи бакетов гистограммы (последний — открытый справа)."""
    keys: list[str] = []
    low = 0
    for edge in bins:
        keys.append(f"{low}-{int(edge)}")
        low = int(edge) + 1
    keys.append(f"{low}+")
    return keys


def coverage_ratio(intervals_by_source: Mapping[str, Sequence[tuple[int, int]]],
                   chars_by_source: Mapping[str, int]) -> float:
    """Доля символов документов, попавшая в чанки (0.0…1.0).

    Интервалы одного документа объединяются перед суммированием: перекрытие окон
    фиксированной стратегии не должно считаться дважды. Документ без интервалов в
    знаменатель всё равно входит — иначе «покрытие» росло бы от того, что часть
    документов не проиндексирована вовсе.
    """
    total = sum(max(0, int(value)) for value in chars_by_source.values())
    if total <= 0:
        return 0.0
    covered = 0
    for source, intervals in intervals_by_source.items():
        covered += _union_length(intervals)
    return round(min(1.0, covered / total), 4)


def _union_length(intervals: Sequence[tuple[int, int]]) -> int:
    """Длина объединения полуоткрытых интервалов ``[start, end)``."""
    spans = sorted((max(0, int(start)), max(0, int(end)))
                   for start, end in intervals if int(end) > int(start))
    if not spans:
        return 0
    length = 0
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start > current_end:
            length += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    return length + (current_end - current_start)


def structure_ratio(chunks: Sequence[Mapping[str, Any]]) -> float:
    """Доля чанков с непустой секцией (0.0…1.0; пустой список → 0.0)."""
    if not chunks:
        return 0.0
    with_section = sum(1 for chunk in chunks if str(chunk.get("section") or "").strip())
    return round(with_section / len(chunks), 4)


def precision_recall(results_by_query: Sequence[Mapping[str, Any]], k: int) -> dict[str, Any]:
    """Средние precision@k и recall@k по тестовым запросам.

    ``results_by_query[i]`` = ``{"query", "expected_sources", "hits", "relevant_total"}``,
    где ``hits`` — попадания поиска в порядке убывания близости, а ``relevant_total`` —
    сколько релевантных чанков есть в индексе (знаменатель recall). Запрос без
    релевантных чанков в индексе в среднее не входит: делить его recall не на что,
    и нулём он обвинил бы стратегию в том, чего в индексе нет.

    Precision считается по фактическому числу возвращённых попаданий, если их меньше
    ``k`` (поиск по короткому индексу не должен выглядеть точнее, чем он есть).
    """
    limit = max(1, int(k))
    precisions: list[float] = []
    recalls: list[float] = []
    per_query: list[dict[str, Any]] = []
    for entry in results_by_query:
        expected = {str(source) for source in entry.get("expected_sources") or []}
        hits = list(entry.get("hits") or [])
        relevant_total = int(entry.get("relevant_total") or 0)
        top = hits[:limit]
        if not top:
            per_query.append({"query": entry.get("query", ""), "precision": 0.0,
                              "recall": 0.0, "relevant": 0})
            continue
        relevant = sum(1 for hit in top if str(hit.get("source") or "") in expected)
        precision = relevant / len(top)
        precisions.append(precision)
        recall = 0.0
        if relevant_total > 0:
            recall = min(1.0, relevant / relevant_total)
            recalls.append(recall)
        per_query.append({"query": entry.get("query", ""),
                          "precision": round(precision, 4),
                          "recall": round(recall, 4), "relevant": relevant})
    return {
        "precision_at_k": round(statistics.fmean(precisions), 4) if precisions else 0.0,
        "recall_at_k": round(statistics.fmean(recalls), 4) if recalls else 0.0,
        "k": limit,
        "queries": per_query,
    }


def ascii_histogram(counts: Mapping[str, int], width: int = CHART_WIDTH) -> str:
    """Текстовая гистограмма ``"0-128 |██████ 12"``; пусто → «нет данных».

    ASCII-вариант обязателен: отчёт собирается и без браузера, поэтому картинка —
    дополнение, а не единственная форма графика.
    """
    if not counts or not any(int(value or 0) for value in counts.values()):
        return NO_DATA
    peak = max(int(value or 0) for value in counts.values())
    lines: list[str] = []
    for label, value in counts.items():
        count = int(value or 0)
        filled = ceil(width * count / peak) if count and peak else 0
        lines.append(f"{label} |{'█' * filled} {count}")
    return "\n".join(lines)


def comparison_rows(fixed: Mapping[str, Any],
                    structural: Mapping[str, Any]) -> list[list[str]]:
    """Строки таблицы сравнения: метрика | fixed | structural | комментарий.

    Читаются метрики прогона: статистика чанков лежит во вложенном ``stats``
    (``chunks``, ``tokens_avg``, ``tokens_std``, ``tokens_max``), рядом — ``coverage``,
    ``structure`` и вложенные ``search``/``timing``. Отсутствующий ключ печатается
    как «—», а не падением: отчёт обязан собираться даже на частичном прогоне.
    """
    rows: list[list[str]] = [["метрика", "fixed", "structural", "комментарий"]]
    metrics: list[tuple[str, tuple[str, ...], str, str | None]] = [
        ("чанков", ("stats", "chunks"), "—", "фиксированное окно даёт меньше чанков, чем секции"),
        ("средний размер, токенов", ("stats", "tokens_avg"), "—", "близко к размеру окна (512)"),
        ("σ размера, токенов", ("stats", "tokens_std"), "—", "у structural выше: секции разной длины"),
        ("максимальный чанк, токенов", ("stats", "tokens_max"), "—", "выше окна быть не должен"),
        ("покрытие, %", ("coverage",), "percent", "доля символов документов в чанках"),
        ("структура, %", ("structure",), "percent", "доля чанков с заголовком секции"),
        ("precision@k", ("search", "precision_at_k"), "score", "доля релевантных среди топ-k"),
        ("recall@k", ("search", "recall_at_k"), "score", "доля найденных от всех релевантных"),
        ("индексация, мс", ("timing", "duration_ms"), "int", "полное время прогона стратегии"),
        ("эмбеддинги, мс", ("timing", "embed_ms"), "int", "время расчёта векторов"),
    ]
    for title, path, mode, comment in metrics:
        rows.append([
            title,
            _format(_dig(fixed, path), mode),
            _format(_dig(structural, path), mode),
            comment or "—",
        ])
    return rows


def _dig(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    """Значение по вложенному пути; ``None`` — ключа нет (печатается как «—»)."""
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _format(value: Any, mode: str | None) -> str:
    """Значение метрики для таблицы отчёта (``None`` → «—»)."""
    if value is None:
        return "—"
    if mode == "percent":
        return f"{float(value) * 100:.1f}"
    if mode == "score":
        return f"{float(value):.2f}"
    if mode == "int":
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)
