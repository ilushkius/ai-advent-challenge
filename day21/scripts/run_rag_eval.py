"""Оценка режима RAG дня 22: десять контрольных вопросов с корпусом и без него.

Каждый вопрос задаётся модели дважды — без RAG и с RAG, — и ответы сравниваются по
эталонным фактам: доля найденных в тексте ответа фактов даёт вердикт
«лучше/хуже/равно». Эталонные факты — литералы из файлов корпуса (числа, имена,
заголовки сообщений), которых нет в общих знаниях модели: так видно, что ответ с RAG
опирался на документы, а не на память модели.

Каждая неудача вызова LLM превращается в откат (ответ без RAG) и помечается в
отчёте: строка не выдаётся за обычный ответ с корпусом. Отчёт пишется в
``docs/reports/rag_eval.md``; код возврата 1 — если был откат или сбой вопроса.

Запуск из папки day21/ (нужен DEEPSEEK_API_KEY в .env)::

    uv run python scripts/run_rag_eval.py
    uv run python scripts/run_rag_eval.py --top-k 3 --strategy rag_corpus_fixed
    uv run python scripts/run_rag_eval.py --limit 2 --report docs/reports/rag_eval.md
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import rag_eval, rag_mode  # noqa: E402
from backend.services.rag_service import RAGError, RAGService  # noqa: E402

#: Длина ячейки markdown-таблицы: полные ответы всё равно идут в приложении.
REPORT_CELL_CHARS = 700

#: Отчёт по умолчанию — рядом с отчётом индексации дня 21.
DEFAULT_REPORT = "docs/reports/rag_eval.md"


def main(argv=None) -> int:
    """Прогоняет вопросы, пишет отчёт и печатает итог; 0 — без откатов и сбоев."""
    args = _parse_args(argv)
    strategy = rag_mode.resolve_rag_strategy(args.strategy)
    if strategy is None:
        print(f"неизвестная стратегия: {args.strategy!r}; "
              f"доступны: {', '.join(rag_mode.RAG_STRATEGIES)}")
        return 1
    service = RAGService()
    config = service.config()
    if not config["ready"]:
        print("корпус или индексы не готовы: собираю (scripts/index_rag_corpus.py)")
        try:
            prepared = service.prepare_corpus()
        except RAGError as exc:
            print(f"сборка корпуса не удалась: {exc}")
            return 1
        print(f"собран корпус: {prepared['corpus']['documents']} документов, "
              f"чанков {sum(prepared['chunks'].values())}")
        config = service.config()
    questions = list(rag_eval.RAG_QUESTIONS)
    if args.limit:
        questions = questions[:max(1, int(args.limit))]
    started = time.perf_counter()
    entries = []
    for number, question in enumerate(questions, 1):
        print(f"[{number}/{len(questions)}] {question.question}")
        entry = _evaluate(service, question, args.top_k, strategy)
        entries.append(entry)
        _print_entry(entry)
    elapsed = time.perf_counter() - started
    report = _render_report(entries, top_k=args.top_k, strategy=strategy,
                            config=config, elapsed=elapsed)
    target = Path(args.report)
    if not target.is_absolute():
        target = DAY_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    better = sum(1 for entry in entries if entry["verdict"] == rag_eval.VERDICT_BETTER)
    worse = sum(1 for entry in entries if entry["verdict"] == rag_eval.VERDICT_WORSE)
    same = sum(1 for entry in entries if entry["verdict"] == rag_eval.VERDICT_SAME)
    fallbacks = sum(1 for entry in entries if _is_fallback(entry))
    failures = sum(1 for entry in entries if entry["error"])
    print("")
    print(f"итог: лучше с RAG — {better}, хуже — {worse}, равно — {same} "
          f"(из {len(entries)}); откатов {fallbacks}, сбоев {failures}; "
          f"{elapsed:.0f} с")
    print(f"отчёт: {target}")
    return 1 if fallbacks or failures else 0


def _parse_args(argv):
    """Разбирает аргументы: объём поиска, стратегия, файл отчёта, число вопросов."""
    parser = argparse.ArgumentParser(
        description="Оценка RAG дня 22: ответы с корпусом и без него по 10 вопросам",
    )
    parser.add_argument("--top-k", type=int, default=rag_mode.RAG_DEFAULT_TOP_K,
                        help=f"сколько фрагментов брать в контекст "
                             f"(по умолчанию {rag_mode.RAG_DEFAULT_TOP_K})")
    parser.add_argument("--strategy", default=rag_mode.RAG_DEFAULT_STRATEGY,
                        help=f"стратегия поиска (по умолчанию "
                             f"{rag_mode.RAG_DEFAULT_STRATEGY})")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help=f"файл отчёта (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--limit", type=int, default=0,
                        help="сколько вопросов взять (0 — все)")
    return parser.parse_args(argv)


def _evaluate(service: RAGService, question, top_k: int, strategy: str) -> dict:
    """Два ответа на один вопрос: факты, вердикт и найденный ожидаемый источник."""
    try:
        record = service.compare(question.question, top_k=top_k, strategy=strategy)
    except RAGError as exc:
        return {"question": question, "error": str(exc), "no_rag": None, "rag": None,
                "without_score": 0.0, "with_score": 0.0, "verdict": "", "found": False}
    without, with_rag = record["no_rag"], record["rag"]
    without_score = rag_eval.fact_score(without["answer"], question)
    with_score = rag_eval.fact_score(with_rag["answer"], question)
    return {
        "question": question,
        "error": "",
        "no_rag": without,
        "rag": with_rag,
        "without_score": without_score,
        "with_score": with_score,
        "verdict": rag_eval.verdict(with_score, without_score),
        "found": rag_eval.expected_found(
            [source["source"] for source in with_rag["sources"]], question),
    }


def _print_entry(entry: dict) -> None:
    """Печатает метрики одного вопроса: факты, вердикт и найденный источник."""
    if entry["error"]:
        print(f"    сбой: {entry['error']}")
        return
    marker = "" if entry["found"] else "  (ожидаемый источник не найден)"
    print(f"    факты: без RAG {entry['without_score']:.2f}, "
          f"с RAG {entry['with_score']:.2f} → {entry['verdict']}{marker}")
    print(f"    {_metrics_line(entry)}")


def _metrics_line(entry: dict) -> str:
    """Метрики обоих ответов одной строкой: время, токены, фрагменты, кэш."""
    parts = []
    for label, key in (("без RAG", "no_rag"), ("с RAG", "rag")):
        record = entry[key]
        if record is None:
            continue
        detail = [f"{record['duration_ms']} мс"]
        tokens = _token_total(record)
        if tokens:
            detail.append(f"{tokens} токенов")
        if key == "rag":
            detail.append(f"{record['chunks_used']} чанков")
            detail.append(f"контекст {record['context_tokens']} токенов")
            cache = (record.get("tokens") or {}).get("cache_hit_percent")
            if cache:
                detail.append(f"кэш {cache:.1f} %")
        parts.append(f"{label} — " + ", ".join(detail))
    return "; ".join(parts) or "вызовов не было"


def _is_fallback(entry: dict) -> bool:
    """Был ли откат: ответ с RAG получен без контекста из-за сбоя вызова."""
    return bool(entry["rag"] and entry["rag"].get("fallback"))


def _render_report(entries: list, *, top_k: int, strategy: str,
                   config: dict, elapsed: float) -> str:
    """Markdown-отчёт: шапка, правило вердикта, таблица, итог и приложение."""
    corpus = config["corpus"]
    lines = [
        "# День 22 — RAG: сравнение ответов с корпусом и без него",
        "",
        f"Отчёт собран прогоном `scripts/run_rag_eval.py`: топ-K = {top_k}, "
        f"стратегия = {strategy},",
        f"корпус — {corpus['documents']} документов / {corpus['chars']} символов "
        f"(~{corpus['pages']} страниц), индекс — {config['chunks_total']} чанков, "
        f"время прогона {elapsed:.0f} с.",
        "",
        "## Как считался вердикт",
        "Ключевые факты вопроса ищутся в тексте ответа (вхождение без учёта регистра); "
        "доля найденных",
        "фактов сравнивается у ответа с RAG и без RAG: «лучше» — доля выше, «хуже» — ниже, "
        "«равно» —",
        "доли совпали. Вопросы намеренно про значения из файлов корпуса: их нельзя "
        "воспроизвести по памяти.",
        "",
        "## Таблица сравнения",
        "",
        "| Вопрос | Ожидание (ключевые факты) | Источники (файл · раздел · score) "
        "| Ответ без RAG | Ответ с RAG | Вердикт |",
        "|---|---|---|---|---|---|",
    ]
    for entry in entries:
        question = entry["question"]
        lines.append("| " + " | ".join([
            _cell(question.question),
            _cell(_expectation(question)),
            _cell(_sources_cell(entry)),
            _cell(_answer_cell(entry, "no_rag")),
            _cell(_answer_cell(entry, "rag")),
            entry["verdict"] or "—",
        ]) + " |")
    lines += ["", "## Итог", ""]
    lines += [f"- {line}" for line in _summary(entries)]
    lines += ["", "## Приложение: полные ответы", ""]
    for number, entry in enumerate(entries, 1):
        lines += _appendix(number, entry)
    return "\n".join(lines) + "\n"


def _expectation(question) -> str:
    """Эталон строки таблицы: формулировка факта и сами литералы."""
    return f"{question.note} Факты: {', '.join(question.key_facts)}"


def _sources_cell(entry: dict) -> str:
    """Колонка источников: использованные чанки и пометка о промахе поиска."""
    if entry["error"]:
        return f"сбой: {entry['error']}"
    sources = list(entry["rag"]["sources"])
    if not sources:
        return "поиск не дал источников"
    cell = "<br>".join(f"{source['source']} · {source['section'] or '—'} · {source['score']}"
                       for source in sources)
    if not entry["found"]:
        expected = ", ".join(entry["question"].expected_sources)
        cell += f"<br>⚠ ожидались: {expected}"
    return cell


def _answer_cell(entry: dict, key: str) -> str:
    """Колонка ответа: текст или пометка сбоя (полный ответ — в приложении)."""
    record = entry[key]
    if record is None:
        return "—"
    prefix = "⚠ откат на ответ без RAG: " if _is_fallback(entry) and key == "rag" else ""
    return prefix + str(record["answer"])


def _summary(entries: list) -> list:
    """Строки раздела «Итог»: счёт вердиктов, промахи поиска и откаты."""
    total = len(entries)
    better = sum(1 for entry in entries if entry["verdict"] == rag_eval.VERDICT_BETTER)
    worse = sum(1 for entry in entries if entry["verdict"] == rag_eval.VERDICT_WORSE)
    same = sum(1 for entry in entries if entry["verdict"] == rag_eval.VERDICT_SAME)
    misses = sum(1 for entry in entries if not entry["found"] and not entry["error"])
    fallbacks = [entry for entry in entries if _is_fallback(entry)]
    failures = [entry for entry in entries if entry["error"]]
    lines = [f"Лучше с RAG: {better}; хуже: {worse}; равно: {same} (из {total})."]
    if failures:
        lines.append(f"Сбоев запроса: {len(failures)} — вопросы без ответов, "
                     "прогон стоит повторить.")
    if misses:
        lines.append(f"Поиск не нашёл ожидаемый источник в {misses} из {total} вопросов: "
                     "там ответ с RAG опирался на соседние фрагменты корпуса.")
    else:
        lines.append(f"Поиск нашёл ожидаемый источник во всех {total} вопросах.")
    if fallbacks:
        lines.append(f"Откатов на ответ без RAG: {len(fallbacks)} — строки помечены "
                     "предупреждением.")
    else:
        lines.append("Откатов на ответ без RAG не было: модель ответила на каждый запрос.")
    return lines


def _appendix(number: int, entry: dict) -> list:
    """Приложение по одному вопросу: эталон, оба ответа, чанки и метрики."""
    question = entry["question"]
    lines = [
        f"### {number}. {question.question}",
        "",
        f"- **Ожидание:** {question.note}",
        f"- **Ключевые факты:** {', '.join(question.key_facts)}",
        f"- **Ожидаемые источники:** {', '.join(question.expected_sources)}",
    ]
    if entry["error"]:
        lines += [f"- **Сбой:** {entry['error']}", ""]
        return lines
    for label, key in (("без RAG", "no_rag"), ("с RAG", "rag")):
        lines.append(f"- **Ответ {label}:** {entry[key]['answer']}")
    warning = entry["rag"].get("warning")
    if warning:
        lines.append(f"- **Предупреждение:** {warning}")
    lines.append("- **Использованные чанки:**")
    sources = list(entry["rag"]["sources"])
    if not sources:
        lines.append("  - поиск не дал источников")
    for source in sources:
        lines.append(f"  - `{source['source']} · {source['title']} · "
                     f"{source['section'] or '—'} · {source['chunk_id']} · "
                     f"{source['score']}`")
    lines += [f"- **Метрики:** {_metrics_line(entry)}", ""]
    return lines


def _token_total(record: dict) -> int:
    """Токены ответа целиком: запрос плюс ответ, 0 — если счётчика нет."""
    tokens = record.get("tokens") or {}
    return int(tokens.get("prompt_tokens") or 0) + int(tokens.get("completion_tokens") or 0)


def _cell(value: str) -> str:
    """Ячейка markdown-таблицы: без переводов строк, с экранированной чертой."""
    text = " ".join(str(value or "").split())
    if len(text) > REPORT_CELL_CHARS:
        text = text[:REPORT_CELL_CHARS - 1].rstrip() + "…"
    return text.replace("|", "\\|")


if __name__ == "__main__":
    sys.exit(main())
