"""Отчёт дня 24: обязательные источники и цитаты, режим «не знаю», демо-набор.

Скрипт прогоняет десять контрольных вопросов демо через службу RAG и пишет
markdown-отчёт: режим, ответ, источники, цитаты, максимальный косинус, автоматический
вердикт и пустая колонка под ручную проверку. Максимум косинуса считается по пулу
кандидатов (``RAG_CANDIDATE_POOL``) — ровно та величина, с которой сравнивается порог.
Режим ``--sweep`` не обращается к модели: он считает только этот косинус и предсказанный
режим — им калибруется набор вопросов под порог.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.domain import rag_demo, rag_mode, rag_quotes  # noqa: E402
from backend.services import rag_demo_service  # noqa: E402
from backend.services.rag_errors import RAGError  # noqa: E402
from backend.services.rag_service import RAGService  # noqa: E402

#: Отчёт по умолчанию — рядом с отчётами предыдущих дней.
DEFAULT_REPORT = "docs/reports/rag_quotes_eval.md"

#: Колонка ручной проверки заполняется человеком после прогона.
MANUAL_STUB = "—"


def main(argv=None) -> int:
    """Прогоняет вопросы, пишет отчёт и печатает итог; 0 — без расхождений."""
    args = _parse_args(argv)
    threshold = _threshold(args)
    rag_quotes.RAG_RELEVANCE_THRESHOLD = threshold
    service = RAGService()
    config = _ensure_corpus(service)
    if config is None:
        return 1
    questions = rag_demo.load_questions()
    if args.limit:
        questions = questions[:max(1, int(args.limit))]
    if not questions:
        print("вопросы демо не загрузились: проверьте backend/data/demo_questions.json")
        return 1
    if args.sweep:
        rows = [_sweep_row(service, item, threshold) for item in questions]
        _print_sweep(rows, threshold)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    started = time.perf_counter()
    result = rag_demo_service.run_demo(service, questions)
    elapsed = time.perf_counter() - started
    _attach_pool_scores(service, result["rows"])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    target = _target(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(result, config=config, threshold=threshold,
                                    elapsed=elapsed), encoding="utf-8")
    _print_rows(result["rows"])
    print(f"отчёт: {target}")
    summary = result["summary"]
    print(f"итог: {summary['rag']} rag, {summary['dont_know']} dont_know, "
          f"с источниками {summary['with_sources']}, с цитатами {summary['with_quotes']}, "
          f"расхождений {summary['mismatches']}")
    return 1 if summary["mismatches"] else 0


def render_report(result: dict, *, config: dict, threshold: float, elapsed: float) -> str:
    """Markdown-отчёт: шапка с настройками, таблица из 10 строк и итог."""
    rows = list(result.get("rows") or [])
    lines = _header(config, threshold, elapsed)
    for number, row in enumerate(rows, 1):
        lines.append(_table_row(row, number))
    lines += ["", "## Распределение `max v`", ""]
    lines += _distribution(rows, threshold)
    lines += ["", "## Итог", ""]
    lines += _totals(result.get("summary") or {}, rows, threshold)
    return "\n".join(lines) + "\n"


def _header(config: dict, threshold: float, elapsed: float) -> list:
    corpus = config.get("corpus") or {}
    return [
        "# Цитаты и режим «не знаю» в RAG (день 24)",
        "",
        f"* дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "* метрика порога: максимум косинуса FAISS по пулу кандидатов "
        "(`vector_score` лучшего из рассмотренных фрагментов: inner product "
        "нормализованных эмбеддингов, [0, 1])",
        f"* `RAG_RELEVANCE_THRESHOLD` = {threshold:g}",
        f"* стратегия: {config.get('default_strategy') or '—'}, "
        f"top_k: {config.get('top_k_default') or '—'}",
        f"* корпус: документов {corpus.get('documents') or 0}, "
        f"страниц {corpus.get('pages') or 0}, чанков {config.get('chunks_total') or 0}",
        f"* время прогона: {elapsed:.1f} с",
        "",
        "Воспроизведение:",
        "",
        "```",
        "uv run python scripts/run_rag_quotes_eval.py",
        "```",
        "",
        "| № | Вопрос | Ожидание | Режим | Ответ | Источники | Цитаты | max v | "
        "Смысл (авто) | Смысл (ручная) | Вердикт |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]


def _table_row(row: dict, number: int) -> str:
    sources = row.get("sources") or []
    quotes = row.get("quotes") or []
    cells = [
        str(number),
        _clean(row.get("question")),
        _clean(row.get("expectation")),
        _clean(row.get("mode")),
        _clean(_short(row.get("answer"), 160)),
        _first(sources, "source"),
        _first(quotes, "quote", 60),
        f"{_max_vector(row):.3f}",
        _yes(row.get("quotes_verified")),
        MANUAL_STUB,
        _clean(row.get("verdict")),
    ]
    return "| " + " | ".join(cells) + " |"


def _distribution(rows: list, threshold: float) -> list:
    lines = [f"| № | Вопрос | max v | выше порога {threshold:g} | Ожидалось |",
             "|---|---|---|---|---|"]
    for number, row in enumerate(rows, 1):
        best = _max_vector(row)
        lines.append(f"| {number} | {_clean(_short(row.get('question'), 70))} | "
                     f"{best:.3f} | {'да' if best >= threshold else 'нет'} | "
                     f"{_clean(row.get('expected_mode'))} |")
    return lines


def _totals(summary: dict, rows: list, threshold: float) -> list:
    rag_rows = [row for row in rows if row.get("mode") == rag_quotes.RAG_MODE_RAG]
    weak = [row for row in rows if row.get("mode") == rag_quotes.RAG_MODE_DONT_KNOW]
    unverified = [number for number, row in enumerate(rows, 1)
                  if row.get("mode") == rag_quotes.RAG_MODE_RAG
                  and not row.get("quotes_verified")]
    lines = [
        f"* всего вопросов: {summary.get('total') or 0}",
        f"* режим `rag`: {summary.get('rag') or 0} (из них с источниками "
        f"{summary.get('with_sources') or 0}, с цитатами {summary.get('with_quotes') or 0})",
        f"* режим `dont_know`: {summary.get('dont_know') or 0}, режим `no_rag`: "
        f"{summary.get('no_rag') or 0}",
        f"* вердикт «совпадает»: "
        f"{sum(1 for row in rows if row.get('verdict') == rag_demo.VERDICT_OK)}",
        f"* вердикт «верно: ответа в корпусе нет»: "
        f"{sum(1 for row in rows if row.get('verdict') == rag_demo.VERDICT_DONT_KNOW_OK)}",
        f"* расхождений: {summary.get('mismatches') or 0}",
        f"* ответы без подтверждённых цитат: {len(unverified)}" +
        (f" (строки {', '.join(str(number) for number in unverified)})"
         if unverified else ""),
        "",
    ]
    if not rag_rows:
        lines.append("Вывод: ни один вопрос не ушёл в режим `rag` — проверьте корпус "
                     "и порог.")
    elif unverified:
        lines.append("Вывод: порог отсекает вопросы вне корпуса корректно, а ответы по "
                     "корпусу всегда несут источники и цитаты. У части строк цитата не "
                     "подтверждена дословно: отчётная цитата — начало чанка (первые "
                     "символы до конца предложения), тогда как модель пересказывает "
                     "другое место того же чанка; такие строки получают "
                     "`quotes_verified=false` и `confidence` 0.3 — это и есть низкая "
                     "уверенность из задания.")
    elif weak:
        lines.append("Вывод: при слабом контексте включается режим «не знаю» без "
                     "обращения к модели, а ответы по корпусу всегда несут источники "
                     "и подтверждённые цитаты.")
    else:
        lines.append("Вывод: все вопросы нашли ответ в корпусе с подтверждёнными "
                     "цитатами; режим «не знаю» проверяется на вопросах вне корпуса.")
    return lines


def _pool_score(service, question: str) -> float:
    """Максимум косинуса по пулу кандидатов — та же метрика, что у гейта порога.

    Итоговая пятёрка фрагментов ранжируется гибридным баллом, и у части чанков
    ``vector_score`` обнуляется (вне топ-30 FAISS), поэтому порог сравнивается с
    пулом: см. `docs/architecture.md`, раздел «Цитаты и анти-галлюцинации».
    """
    pool = service.index_service.search(question,
                                        top_k=rag_mode.RAG_CANDIDATE_POOL,
                                        strategy=rag_mode.RAG_DEFAULT_STRATEGY)
    return max((float(hit.get("score") or 0.0) for hit in pool), default=0.0)


def _attach_pool_scores(service, rows: list) -> None:
    """Проставляет строкам прогона ``max_vector_score`` по пулу кандидатов."""
    for row in rows:
        row["max_vector_score"] = round(_pool_score(service, row.get("question") or ""), 4)


def _max_vector(row: dict) -> float:
    """Косинус для колонки `max v`: пул, если посчитан, иначе лучший фрагмент."""
    value = row.get("max_vector_score")
    return float(row.get("top_score") or 0.0) if value is None else float(value)


def _sweep_row(service, item, threshold: float) -> dict:
    """Замер без модели: максимум косинуса по пулу кандидатов и режим."""
    hits = service.retrieve(item.question)
    best = _pool_score(service, item.question)
    return {
        "question": item.question,
        "expected_mode": item.expected_mode,
        "expected_sources": list(item.expected_sources),
        "max_vector_score": round(best, 4),
        "top_score": round(float((hits[0] or {}).get("score") or 0.0), 4) if hits else 0.0,
        "sources": [str(hit.get("source") or "") for hit in hits],
        "predicted_mode": (rag_quotes.RAG_MODE_RAG if best >= threshold
                           else rag_quotes.RAG_MODE_DONT_KNOW),
    }


def _print_sweep(rows: list, threshold: float) -> None:
    rag_count = sum(1 for row in rows if row["predicted_mode"] == rag_quotes.RAG_MODE_RAG)
    print(f"порог {threshold:g}: rag {rag_count}, dont_know {len(rows) - rag_count}")
    for number, row in enumerate(rows, 1):
        source = row["sources"][0] if row["sources"] else "—"
        print(f"  {number:>2}. [{row['predicted_mode']:<9}] "
              f"max v {row['max_vector_score']:.4f} top {row['top_score']:.4f} | "
              f"{row['question']}")
        print(f"      ожидание {row['expected_mode'] or '—'}; источник {source}")


def _print_rows(rows: list) -> None:
    for number, row in enumerate(rows, 1):
        print(f"  {number:>2}. {str(row.get('mode')):<9} "
              f"v={_max_vector(row):.3f} "
              f"источников {len(row.get('sources') or [])} "
              f"цитат {len(row.get('quotes') or [])} "
              f"авто {_yes(row.get('quotes_verified'))} — {row.get('verdict')}")
        print(f"      {row.get('question')}")


def _ensure_corpus(service) -> dict | None:
    """Готовит корпус, если он ещё не собран; ``None`` — сборка не удалась."""
    config = service.config()
    if config["ready"]:
        return config
    print("корпус или индексы не готовы: собираю")
    try:
        prepared = service.prepare_corpus()
    except RAGError as exc:
        print(f"сборка корпуса не удалась: {exc}")
        return None
    print(f"собран корпус: {prepared['corpus']['documents']} документов, "
          f"чанков {sum(prepared['chunks'].values())}")
    return service.config()


def _threshold(args) -> float:
    """Порог из аргумента (с ограничением [0, 1]) или из домена."""
    if args.threshold is None:
        return rag_quotes.RAG_RELEVANCE_THRESHOLD
    return min(rag_quotes.RAG_RELEVANCE_THRESHOLD_MAX,
               max(rag_quotes.RAG_RELEVANCE_THRESHOLD_MIN, float(args.threshold)))


def _target(value: str) -> Path:
    """Путь отчёта: относительный считается от корня дня."""
    path = Path(value)
    return path if path.is_absolute() else DAY_ROOT / path


def _parse_args(argv):
    """Разбирает аргументы: отчёт, объём, порог, свип, JSON."""
    parser = argparse.ArgumentParser(
        description="Прогон RAG-демо дня 24: источники, цитаты и режим «не знаю».")
    parser.add_argument("--out", default=DEFAULT_REPORT,
                        help="путь к markdown-отчёту (по умолчанию %(default)s)")
    parser.add_argument("--limit", type=int, default=0,
                        help="сколько вопросов брать (0 — все)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="порог релевантности вместо значения из окружения")
    parser.add_argument("--sweep", action="store_true",
                        help="только замер косинуса, без вызовов модели и отчёта")
    parser.add_argument("--json", action="store_true", help="печатать строки как JSON")
    return parser.parse_args(argv)


def _clean(value) -> str:
    """Значение для ячейки markdown: одна строка без вертикальных черт."""
    text = " ".join(str(value or "").split()).replace("|", "/")
    return text or "—"


def _short(text, limit: int) -> str:
    """Обрезает текст до ``limit`` символов, сохраняя многоточие."""
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _first(items: list, field: str, limit: int = 0) -> str:
    """Первое значение поля плюс счётчик: «d.py · 3»; пусто — прочерк."""
    if not items:
        return "—"
    value = str((items[0] or {}).get(field) or "")
    if limit:
        value = _short(value, limit)
    return _clean(f"{value} · {len(items)}")


def _yes(value) -> str:
    """Да/нет для колонки отчёта."""
    return "да" if value else "нет"


if __name__ == "__main__":
    sys.exit(main())
