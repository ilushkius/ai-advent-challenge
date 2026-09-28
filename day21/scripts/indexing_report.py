"""Сборка отчёта о прогоне индексации (``docs/reports/indexing_demo.md``).

Отчёт собирается ИЗ ДАННЫХ прогона: метрики берутся из строки запуска, документы —
из ``metrics["documents"]``, таблица сравнения — из ``metrics["comparison"]``,
примеры чанков — из таблицы ``document_chunks``, результаты запросов — из
``metrics["queries"]``, выводы сценариев — из ``ScenarioResult``. Поэтому «забыть
обновить отчёт» нельзя: чего нет в данных, того нет и в отчёте (там стоит «—»).

Текстовые (ASCII) гистограммы обязательны: отчёт должен собираться и без браузера,
поэтому PNG — дополнение к таблице распределения, а не единственная её форма.

Числа форматируются как в интерфейсе: размеры — целые, доли — два знака,
проценты — один знак. Отчёт — доказательство дня, а не дамп словаря.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Подписи стратегий в отчёте.
STRATEGY_LABELS = {"fixed": "fixed (окно по токенам)",
                   "structural": "structural (по секциям)"}

#: Сколько попаданий запроса показывать в отчёте (в интерфейсе — столько же).
TOP_HITS = 3

#: Подпись «данных нет»: пустая ячейка в доказательстве дня хуже явной строки.
NO_DATA = "—"


def write_report(path, run_data: Mapping[str, Any], *, stats: Mapping[str, Any],
                 chunk_samples: Mapping[str, Sequence[Mapping[str, Any]]],
                 queries: Sequence[Mapping[str, Any]],
                 scenarios: Sequence[Any], ascii_charts: Mapping[str, str],
                 screenshot: str = "") -> Path:
    """Пишет markdown-отчёт и возвращает его путь (родительские папки создаются)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# День 21 — индексация документов: две стратегии чанкинга и сравнение",
        "",
        (
            "Отчёт собран прогоном ``scripts/indexing_demo.py``: документы "
            "собираются из источников репозитория, режутся на чанки двумя "
            "стратегиями, эмбеддинги кладутся в FAISS, метаданные чанков — в "
            "SQLite (``document_chunks``), журнал прогонов — в ``index_runs``. "
            "Все числа ниже взяты из данных прогона."
        ),
        "",
        f"* дата прогона: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"* модель эмбеддингов: {_embedding_model(run_data)}",
        f"* запуск: №{_run(run_data).get('id', NO_DATA)} · статус "
        f"{_run(run_data).get('status', NO_DATA)} · длительность "
        f"{_run(run_data).get('duration_ms', 0)} мс "
        f"(эмбеддинги {_run(run_data).get('embed_duration_ms', 0)} мс, "
        f"индекс {_run(run_data).get('index_duration_ms', 0)} мс)",
        f"* чанки: fixed {_chunks(stats, 'fixed')}, structural "
        f"{_chunks(stats, 'structural')}",
        "",
    ]
    lines += _documents_section(run_data)
    lines += _comparison_section(run_data)
    lines += _distribution_section(stats, ascii_charts)
    lines += _samples_section(chunk_samples)
    lines += _queries_section(queries)
    lines += _scenarios_section(scenarios)
    lines += _artifacts_section(stats, screenshot)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _documents_section(run_data: Mapping[str, Any]) -> list[str]:
    """Раздел «Документы»: файл, вид, язык, заголовок и размер."""
    documents = _metrics(run_data).get("documents") or []
    lines = ["## Документы", ""]
    if not documents:
        lines += ["Данных о документах нет: прогон не дошёл до индексации.", ""]
        return lines
    lines += [
        f"Собрано документов: **{len(documents)}**, символов: "
        f"**{_metrics(run_data).get('documents_total_chars', 0)}**.",
        "",
        "| файл | вид | язык | усечён | символов | заголовок |",
        "|---|---|---|---|---|---|",
    ]
    for item in documents:
        lines.append(
            f"| {item.get('source', NO_DATA)} | {item.get('kind', NO_DATA)} "
            f"| {item.get('language', NO_DATA)} "
            f"| {'да' if item.get('truncated') else 'нет'} "
            f"| {item.get('chars', 0)} | {_escape(item.get('title'))} |"
        )
    lines.append("")
    return lines


def _comparison_section(run_data: Mapping[str, Any]) -> list[str]:
    """Раздел «Сравнение стратегий»: таблица метрик прогона."""
    rows = _metrics(run_data).get("comparison") or []
    lines = ["## Сравнение стратегий", ""]
    if not rows:
        lines += ["Таблицы сравнения нет: её считает демо-прогон обеих стратегий.", ""]
        return lines
    lines += ["| " + " | ".join(str(cell) for cell in rows[0]) + " |",
              "|---|---|---|---|"]
    for row in rows[1:]:
        cells = [str(cell) for cell in row]
        lines.append("| " + " | ".join(cells[:4]) + " |")
    lines += [
        "",
        (
            "Как читать: **чанков** и **средний размер** показывают, что окно даёт "
            "ровные чанки, а секции — разные; **σ** и **максимальный чанк** — "
            "разброс размеров; **покрытие** — долю символов документов, попавшую в "
            "чанки (объединение интервалов, поэтому перекрытие окон не удваивается); "
            "**структура** — долю чанков с заголовком секции; **precision@k** и "
            "**recall@k** — качество поиска по пяти тестовым запросам и ожидаемым "
            "источникам (ground truth из домена)."
        ),
        "",
    ]
    return lines


def _distribution_section(stats: Mapping[str, Any],
                          ascii_charts: Mapping[str, str]) -> list[str]:
    """Раздел «Распределение размеров чанков»: ASCII-гистограммы и таблица бакетов."""
    lines = ["## Распределение размеров чанков", ""]
    buckets: list[str] = []
    for strategy in ("fixed", "structural"):
        histogram = (stats.get(strategy) or {}).get("histogram") or {}
        for bucket in histogram:
            if bucket not in buckets:
                buckets.append(bucket)
    for strategy in ("fixed", "structural"):
        title = STRATEGY_LABELS.get(strategy, strategy)
        lines += [f"### {title}", "", "```", ascii_charts.get(strategy, "нет данных"),
                  "```", ""]
    if not buckets:
        lines += ["Гистограмма пуста: чанков нет.", ""]
        return lines
    header = "| бакет | fixed | structural |"
    lines += [header, "|---|---|---|"]
    for bucket in buckets:
        lines.append(
            f"| {bucket} "
            f"| {(stats.get('fixed') or {}).get('histogram', {}).get(bucket, 0)} "
            f"| {(stats.get('structural') or {}).get('histogram', {}).get(bucket, 0)} |"
        )
    lines.append("")
    return lines


def _samples_section(chunk_samples: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    """Раздел «Примеры чанков»: первые чанки каждой стратегии."""
    lines = ["## Примеры чанков", ""]
    for strategy in ("fixed", "structural"):
        items = list(chunk_samples.get(strategy) or [])
        lines += [f"### {STRATEGY_LABELS.get(strategy, strategy)}", ""]
        if not items:
            lines += ["Чанков нет.", ""]
            continue
        lines += ["| документ | секция | символов | токенов | начало текста |",
                  "|---|---|---|---|---|"]
        for chunk in items:
            size = int(chunk.get("end_char", 0)) - int(chunk.get("start_char", 0))
            preview = _one_line(chunk.get("content"), 120)
            lines.append(
                f"| {chunk.get('source', NO_DATA)} | {_escape(chunk.get('section'))} "
                f"| {size} | {chunk.get('token_count', 0)} | {preview} |"
            )
        lines.append("")
    return lines


def _queries_section(queries: Sequence[Mapping[str, Any]]) -> list[str]:
    """Раздел «Тестовые запросы»: топ-3 каждой стратегии и её precision@k."""
    lines = ["## Тестовые запросы", ""]
    if not queries:
        lines += ["Результатов запросов нет: демо-прогон не выполнялся.", ""]
        return lines
    for entry in queries:
        lines += [
            f"### ❓ {_escape(entry.get('query'))}",
            "",
            f"* ожидаемые источники: {', '.join(entry.get('expected_sources') or []) or NO_DATA}",
            f"* зачем запрос: {_escape(entry.get('note'))}",
            "",
        ]
        for strategy in ("fixed", "structural"):
            block = entry.get(strategy) or {}
            hits = list(block.get("hits") or [])[:TOP_HITS]
            lines += [
                f"**{strategy}** (релевантных чанков в индексе: "
                f"{block.get('relevant_total', 0)}):",
                "",
            ]
            if not hits:
                lines += ["попаданий нет", ""]
                continue
            lines += ["| ранг | оценка | документ | секция | токенов |",
                      "|---|---|---|---|---|"]
            for hit in hits:
                lines.append(
                    f"| {hit.get('rank', NO_DATA)} | {hit.get('score', NO_DATA)} "
                    f"| {hit.get('source', NO_DATA)} | {_escape(hit.get('section'))} "
                    f"| {hit.get('token_count', 0)} |"
                )
            lines.append("")
    return lines


def _scenarios_section(scenarios: Sequence[Any]) -> list[str]:
    """Раздел «Пять сценариев проверки»: что проверялось и чем кончилось."""
    lines = ["## Пять сценариев проверки", ""]
    if not scenarios:
        lines += ["Сценарии не запускались (``--skip-scenarios``).", ""]
        return lines
    lines += ["| сценарий | итог | вывод |", "|---|---|---|"]
    for result in scenarios:
        mark = "✅ OK" if result.ok else "❌ FAIL"
        lines.append(f"| {result.name} | {mark} | {_escape(result.details)} |")
    lines += ["", f"Пройдено проверок: "
                  f"**{sum(1 for item in scenarios if item.ok)}/{len(scenarios)}**.", ""]
    return lines


def _artifacts_section(stats: Mapping[str, Any], screenshot: str) -> list[str]:
    """Раздел «Артефакты»: файлы индексов, БД прогона и снимок интерфейса."""
    lines = ["## Артефакты", ""]
    for strategy in ("fixed", "structural"):
        entry = stats.get(strategy) or {}
        path = entry.get("index_file")
        lines.append(
            f"* индекс {strategy}: {path or NO_DATA} "
            f"({entry.get('index_bytes', 0)} байт, {entry.get('chunks', 0)} чанков)"
        )
    lines.append("* журнал запусков и метаданные чанков: `agents.db` "
                 "(`index_runs`, `document_chunks`)")
    if screenshot:
        lines += ["", f"### Интерфейс", "", f"![Раздел «📦 Индексация»]({screenshot})", ""]
    else:
        lines += ["* скриншот не сделан: браузер Playwright недоступен "
                  "(``uv run playwright install chromium``)", ""]
    return lines


def _metrics(run_data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Метрики прогона из отчёта о запуске (``{}`` — метрик нет)."""
    metrics = run_data.get("metrics")
    return metrics if isinstance(metrics, Mapping) else {}


def _run(run_data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Строка запуска из отчёта (``{}`` — её нет)."""
    run = run_data.get("run")
    return run if isinstance(run, Mapping) else {}


def _embedding_model(run_data: Mapping[str, Any]) -> str:
    """Имя модели эмбеддингов из метрик прогона."""
    return str(_metrics(run_data).get("embedding_model") or NO_DATA)


def _chunks(stats: Mapping[str, Any], strategy: str) -> int:
    """Сколько чанков у стратегии по её статистике."""
    return int((stats.get(strategy) or {}).get("chunks") or 0)


def _escape(value: Any) -> str:
    """Текст для ячейки таблицы: переносы строк и вертикальные черты безопасны."""
    if value in (None, ""):
        return NO_DATA
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _one_line(value: Any, limit: int) -> str:
    """Первая строка текста длиной до ``limit`` символов (для ячейки таблицы)."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return _escape(text)
    return _escape(text[:limit] + "…")
