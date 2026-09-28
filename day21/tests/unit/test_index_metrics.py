"""Метрики сравнения стратегий: размеры, бакеты, покрытие, качество поиска (день 21).

Метрики — то, ради чего день существует, поэтому проверяются их границы и особые
случаи: покрытие НЕ удваивается на перекрытии окон (иначе фиксированная стратегия
выглядела бы полнее, чем есть), precision считается по фактическому числу попаданий,
а запрос без релевантных чанков в индексе в среднее recall не входит.
"""
import pytest

from backend.domain.index_metrics import (
    ascii_histogram,
    comparison_rows,
    coverage_ratio,
    histogram,
    precision_recall,
    size_stats,
    structure_ratio,
)


# ---------- размеры ----------
def test_size_stats_empty():
    """Пустой список чанков — нули без исключения."""
    assert size_stats([]) == {"count": 0, "avg": 0.0, "median": 0.0, "std": 0.0,
                              "min": 0, "max": 0}


def test_size_stats_values():
    """Среднее, медиана, разброс и границы размеров считаются по всем чанкам."""
    stats = size_stats([10, 20, 30])
    assert stats["count"] == 3
    assert stats["avg"] == 20.0
    assert stats["median"] == 20.0
    assert stats["min"] == 10 and stats["max"] == 30
    assert stats["std"] > 0


def test_size_stats_single_chunk_has_no_spread():
    """Один чанк — σ равна нулю (выборочное отклонение здесь не определено)."""
    assert size_stats([42])["std"] == 0.0


@pytest.mark.parametrize("value,expected", [
    (0, "0-128"), (128, "0-128"), (129, "129-256"), (256, "129-256"),
    (257, "257-384"), (384, "257-384"), (385, "385-512"), (512, "385-512"),
    (513, "513+"), (5000, "513+"),
])
def test_histogram_bucket_boundaries(value, expected):
    """Верхняя граница бакета входит в него самого: бакеты не перекрываются."""
    counts = histogram([value])
    assert counts[expected] == 1
    assert sum(counts.values()) == 1


def test_histogram_counts_all_chunks():
    """Гистограмма считает каждый чанк ровно один раз."""
    counts = histogram([10, 200, 300, 400, 1000])
    assert sum(counts.values()) == 5
    assert counts["0-128"] == 1 and counts["129-256"] == 1
    assert counts["513+"] == 1


def test_histogram_of_empty_list_is_zeroed():
    """Пустой список даёт нулевые бакеты (а не отсутствие ключей)."""
    counts = histogram([])
    assert set(counts) == {"0-128", "129-256", "257-384", "385-512", "513+"}
    assert all(value == 0 for value in counts.values())


# ---------- покрытие ----------
def test_coverage_ratio_counts_union_not_sum():
    """Перекрывающиеся интервалы считаются один раз: перекрытие не удваивает покрытие."""
    intervals = {"doc.md": [(0, 100), (50, 150)]}
    assert coverage_ratio(intervals, {"doc.md": 200}) == 0.75


def test_coverage_ratio_full_and_empty():
    """Полное покрытие — 1.0, отсутствие данных — 0.0."""
    assert coverage_ratio({"a.md": [(0, 10)]}, {"a.md": 10}) == 1.0
    assert coverage_ratio({}, {}) == 0.0
    assert coverage_ratio({}, {"a.md": 10}) == 0.0


def test_coverage_ratio_counts_documents_without_chunks():
    """Документ без чанков входит в знаменатель: покрытие падает, а не растёт."""
    intervals = {"a.md": [(0, 5)]}
    assert coverage_ratio(intervals, {"a.md": 5, "b.md": 5}) == 0.5


def test_coverage_ratio_ignores_empty_intervals():
    """Пустые и перевёрнутые интервалы не дают отрицательного вклада."""
    assert coverage_ratio({"a.md": [(5, 5), (7, 2)]}, {"a.md": 10}) == 0.0


# ---------- структура ----------
def test_structure_ratio_counts_sections():
    """Доля чанков с непустой секцией — это метрика сохранения структуры."""
    chunks = [{"section": "Раздел A"}, {"section": ""}, {"section": "  "},
              {"section": "Раздел B"}]
    assert structure_ratio(chunks) == 0.5


def test_structure_ratio_of_empty_list():
    """Пустой список чанков — 0.0 (а не ошибка деления)."""
    assert structure_ratio([]) == 0.0


# ---------- качество поиска ----------
def _query(hits, expected, relevant_total=10, query="запрос"):
    """Запись результата поиска для проверки precision/recall."""
    return {"query": query, "expected_sources": expected,
            "hits": [{"source": source} for source in hits],
            "relevant_total": relevant_total}


def test_precision_recall_counts_relevant_hits():
    """Precision — доля релевантных попаданий, recall — доля от всех релевантных."""
    metrics = precision_recall([_query(["a.md", "b.md", "x.md"], ["a.md", "b.md"],
                                       relevant_total=4)], k=3)
    assert metrics["precision_at_k"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["recall_at_k"] == 0.5
    assert metrics["k"] == 3


def test_precision_uses_actual_hit_count():
    """Если попаданий меньше k, precision делится на фактическое число попаданий."""
    metrics = precision_recall([_query(["a.md"], ["a.md"], relevant_total=4)], k=5)
    assert metrics["precision_at_k"] == 1.0


def test_query_without_relevant_chunks_is_skipped():
    """Запрос без релевантных чанков в индексе в среднее recall не входит."""
    metrics = precision_recall([_query(["a.md"], ["a.md"], relevant_total=0)], k=3)
    assert metrics["recall_at_k"] == 0.0
    assert metrics["precision_at_k"] == 1.0


def test_precision_recall_averages_queries():
    """Средние считаются по всем запросам с попаданиями."""
    metrics = precision_recall([
        _query(["a.md"], ["a.md"], query="первый"),
        _query(["x.md"], ["a.md"], query="второй"),
    ], k=1)
    assert metrics["precision_at_k"] == 0.5
    assert [item["query"] for item in metrics["queries"]] == ["первый", "второй"]


def test_precision_recall_without_hits():
    """Запрос без попаданий даёт нули и не ломает усреднение."""
    metrics = precision_recall([_query([], ["a.md"])], k=3)
    assert metrics["precision_at_k"] == 0.0
    assert metrics["recall_at_k"] == 0.0


# ---------- вывод ----------
def test_ascii_histogram_draws_bars():
    """Текстовая гистограмма рисует полосы пропорционально максимуму."""
    chart = ascii_histogram({"0-128": 4, "129-256": 2})
    lines = chart.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("0-128 |")
    assert lines[0].count("█") == 40 and lines[0].endswith(" 4")
    assert lines[1].count("█") == 20 and lines[1].endswith(" 2")


def test_ascii_histogram_without_data():
    """Пустая гистограмма — явное «нет данных», а не пустая строка."""
    assert ascii_histogram({}) == "нет данных"
    assert ascii_histogram({"0-128": 0}) == "нет данных"


def test_comparison_rows_have_both_strategies():
    """Таблица сравнения — по строке на метрику с обеими стратегиями и комментарием."""
    fixed = {"stats": {"chunks": 10, "tokens_avg": 500.0, "tokens_std": 10.0,
                       "tokens_max": 512},
             "coverage": 1.0, "structure": 0.0,
             "search": {"precision_at_k": 0.6, "recall_at_k": 0.3},
             "timing": {"duration_ms": 1200, "embed_ms": 900}}
    structural = {"stats": {"chunks": 25, "tokens_avg": 180.0, "tokens_std": 90.0,
                            "tokens_max": 480},
                  "coverage": 0.94, "structure": 0.8,
                  "search": {"precision_at_k": 0.8, "recall_at_k": 0.45},
                  "timing": {"duration_ms": 1500, "embed_ms": 1100}}
    rows = comparison_rows(fixed, structural)
    assert rows[0] == ["метрика", "fixed", "structural", "комментарий"]
    table = {row[0]: row for row in rows[1:]}
    assert table["чанков"][1] == "10" and table["чанков"][2] == "25"
    assert table["покрытие, %"][1] == "100.0" and table["покрытие, %"][2] == "94.0"
    assert table["precision@k"][1] == "0.60" and table["precision@k"][2] == "0.80"
    assert table["структура, %"][2] == "80.0"
    assert all(len(row) == 4 for row in rows)


def test_comparison_rows_tolerate_missing_metrics():
    """Отсутствующая метрика печатается прочерком, а не падением."""
    rows = comparison_rows({}, {})
    assert all(row[1] == "—" and row[2] == "—" for row in rows[1:])
