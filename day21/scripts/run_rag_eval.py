"""Оценка режимов отбора RAG дня 23: четыре режима отбора и ответ без корпуса.

Прогон отвечает на каждый контрольный вопрос пятью способами: без RAG (эталон),
затем режимами ``baseline``, ``rewrite``, ``rerank`` и ``rerank_filter``. Ответы
сравниваются по эталонным фактам: доля найденных в тексте фактов даёт вердикт
«лучше/хуже/равно» — сначала против ответа без корпуса, затем против ``baseline``
(то есть против отбора дня 22). Эталонные факты — литералы из файлов корпуса
(числа, имена, заголовки сообщений), которых нет в общих знаниях модели: так видно,
что ответ опирался на документы, а не на память модели.

Кросс-энкодер прогоняется один раз на вопрос: режимы ``rerank`` и ``rerank_filter``
идут по одному пулу кандидатов и одному запросу, поэтому второй проход вернул бы те
же баллы, и их отдаёт кэш (``CachedReranker``). Свип порога считается офлайн из
сохранённых баллов реранкера — вызовов модели на сетку порогов нет.

Каждая неудача вызова LLM превращается в откат (ответ без RAG) и помечается в
отчёте; сбой необязательной ступени (реранкер, порог) стоит только предупреждения и
не отменяет ответ. Отчёт пишется в ``docs/reports/rag_modes.md``; код возврата 1 —
если был откат или сбой.

Запуск из папки day21/ (нужен DEEPSEEK_API_KEY в .env; первый прогон скачает веса
кросс-энкодера в ``index/models``)::

    uv run python scripts/run_rag_eval.py --sweep
    uv run python scripts/run_rag_eval.py --top-k 3 --threshold 0.5
    uv run python scripts/run_rag_eval.py --limit 2 --report docs/reports/rag_modes.md
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

import rag_eval_report as report  # noqa: E402

from backend.domain import rag_eval, rag_filter, rag_mode  # noqa: E402
from backend.services.rag_errors import RAGError  # noqa: E402
from backend.services.rag_retrieval import RAGRetrieval  # noqa: E402
from backend.services.rag_service import RAGService  # noqa: E402
from backend.services.rerank_service import get_rerank_service  # noqa: E402

#: Отчёт по умолчанию — рядом с отчётами дней 21 и 22.
DEFAULT_REPORT = "docs/reports/rag_modes.md"

#: Режимы, которые считаются службой и попадают в таблицу.
MODE_NAMES = tuple(rag_filter.RAG_MODES)


class CachedReranker:
    """Реранкер с кэшем пар «запрос + фрагменты»: один прогон кросс-энкодера на вопрос.

    Баллы зависят только от текста запроса и текста фрагментов, а пул кандидатов у
    режимов ``rerank`` и ``rerank_filter`` одинаков — повторный проход вернул бы те же
    числа, поэтому второй запрос берётся из кэша. Кэш живёт один прогон: ключ включает
    полный список текстов, так что подмена вопроса или пула считается заново.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self._cache: dict = {}
        self.calls = 0

    @property
    def model_name(self) -> str:
        """Имя модели внутреннего реранкера (для логов и отчёта)."""
        return self._inner.model_name

    @property
    def loaded(self) -> bool:
        """Загружены ли веса внутреннего реранкера."""
        return self._inner.loaded

    def score(self, query: str, texts) -> list:
        """Баллы фрагментов: считаются один раз на пару «запрос + список текстов»."""
        key = (str(query), tuple(str(text) for text in texts))
        if key not in self._cache:
            self._cache[key] = self._inner.score(query, texts)
            self.calls += 1
        return list(self._cache[key])

    def warmup(self) -> bool:
        """Прогрев внутреннего реранкера (веса грузятся здесь)."""
        return self._inner.warmup()

    def reset(self) -> None:
        """Сброс кэша и весов внутреннего реранкера."""
        self._cache.clear()
        self._inner.reset()


def main(argv=None) -> int:
    """Прогоняет вопросы, пишет отчёт и печатает итог; 0 — без откатов и сбоев."""
    args = _parse_args(argv)
    strategy = rag_mode.resolve_rag_strategy(args.strategy)
    if strategy is None:
        print(f"неизвестная стратегия: {args.strategy!r}; "
              f"доступны: {', '.join(rag_mode.RAG_STRATEGIES)}")
        return 1
    threshold = min(1.0, max(0.0, float(args.threshold)))
    service = RAGService(rerank_service=CachedReranker(get_rerank_service()))
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
    retrieval = RAGRetrieval(index_service=service.index_service, store=service.store,
                             rerank_service=service.rerank_service)
    questions = list(rag_eval.RAG_QUESTIONS)
    if args.limit:
        questions = questions[:max(1, int(args.limit))]
    started = time.perf_counter()
    entries = []
    for number, question in enumerate(questions, 1):
        print(f"[{number}/{len(questions)}] {question.question}")
        entry = _evaluate(service, retrieval, question, top_k=args.top_k,
                          strategy=strategy, threshold=threshold)
        entries.append(entry)
        _print_entry(entry)
    elapsed = time.perf_counter() - started
    sweep = _sweep(entries, rag_filter.RAG_THRESHOLD_GRID) if args.sweep else None
    text = report.render_report(entries, top_k=args.top_k, strategy=strategy,
                                mode_names=MODE_NAMES, threshold=threshold, sweep=sweep,
                                config=config, elapsed=elapsed)
    target = Path(args.report)
    if not target.is_absolute():
        target = DAY_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    fallbacks = _fallbacks(entries)
    failures = _failures(entries)
    print("")
    for line in report.summary_lines(entries, MODE_NAMES):
        print(line.strip("`").replace("`", ""))
    if sweep is not None:
        chosen = report.choose_threshold(sweep)
        mark = "совпадает с порогом прогона" if abs(chosen - threshold) < 1e-9 \
            else f"впишите в RAG_FILTER_MIN_SCORE (в прогоне {threshold:.2f})"
        print(f"свип порога: выбран {chosen:.2f} — {mark}")
    print(f"откатов {fallbacks}, сбоев {failures}; вызовов кросс-энкодера "
          f"{service.rerank_service.calls}; {elapsed:.0f} с")
    print(f"отчёт: {target}")
    return 1 if fallbacks or failures else 0


def _parse_args(argv):
    """Разбирает аргументы: объём поиска, стратегия, отчёт, порог, свип."""
    parser = argparse.ArgumentParser(
        description="Оценка режимов отбора RAG дня 23: реранкер, порог, rewrite",
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
    parser.add_argument("--threshold", type=float, default=rag_filter.RAG_FILTER_MIN_SCORE,
                        help=f"порог отсечения режима rerank_filter "
                             f"(по умолчанию {rag_filter.RAG_FILTER_MIN_SCORE})")
    parser.add_argument("--sweep", action="store_true",
                        help="добавить в отчёт свип порога по сохранённым баллам")
    return parser.parse_args(argv)


def _evaluate(service: RAGService, retrieval: RAGRetrieval, question, *, top_k: int,
              strategy: str, threshold: float) -> dict:
    """Пять ответов на один вопрос: без RAG, четыре режима, факты, вердикты, пул."""
    entry = {
        "question": question,
        "error": "",
        "no_rag": None,
        "records": {},
        "mode_errors": {},
        "scores": {},
        "verdicts": {},
        "vs_baseline": {},
        "found": {},
        "pool": 0,
        "dropped": 0,
        "pool_scores": [],
    }
    try:
        entry["no_rag"] = service.no_rag_query(question.question)
    except RAGError as exc:
        entry["error"] = str(exc)
        return entry
    for name in MODE_NAMES:
        min_score = threshold if name == rag_filter.RAG_MODE_RERANK_FILTER else None
        try:
            entry["records"][name] = service.rag_query(
                question.question, top_k=top_k, strategy=strategy, mode=name,
                min_score=min_score)
        except RAGError as exc:
            entry["mode_errors"][name] = str(exc)
    stages = _pool(retrieval, question.question, top_k=top_k, strategy=strategy)
    if stages is not None and stages.reranked:
        entry["pool_scores"] = [
            (round(float(hit.get("rerank_score") or 0.0), 4), str(hit.get("source") or ""))
            for hit in stages.candidates
        ]
        entry["pool"] = len(entry["pool_scores"])
        entry["dropped"] = sum(1 for score, _ in entry["pool_scores"] if score < threshold)
    _score(entry, question)
    return entry


def _score(entry: dict, question) -> None:
    """Считает доли фактов и вердикты режимов: против «без RAG» и против baseline."""
    entry["scores"]["no_rag"] = rag_eval.fact_score(entry["no_rag"]["answer"], question)
    baseline = entry["records"].get(rag_filter.RAG_MODE_BASELINE)
    baseline_score = rag_eval.fact_score(baseline["answer"], question) if baseline else 0.0
    for name in MODE_NAMES:
        record = entry["records"].get(name)
        if record is None:
            continue
        score = rag_eval.fact_score(record["answer"], question)
        entry["scores"][name] = score
        entry["verdicts"][name] = rag_eval.verdict(score, entry["scores"]["no_rag"])
        entry["vs_baseline"][name] = rag_eval.verdict(score, baseline_score)
        entry["found"][name] = rag_eval.expected_found(
            [source["source"] for source in record["sources"]], question)


def _pool(retrieval: RAGRetrieval, question: str, *, top_k: int, strategy: str):
    """Кандидаты режима ``rerank`` с баллами: источник данных для свипа порога."""
    try:
        return retrieval.run(question, top_k=top_k, strategy=strategy,
                             mode=rag_filter.RAG_MODE_RERANK)
    except RAGError:
        return None


def _sweep(entries: list, grid) -> list:
    """Свип порога офлайн: сколько вопросов сохраняет фрагменты и ожидаемый источник."""
    rows = []
    for threshold in grid:
        total = kept_any = kept_expected = 0
        for entry in entries:
            if not entry["pool_scores"]:
                continue
            total += 1
            kept = [source for score, source in entry["pool_scores"] if score >= threshold]
            if kept:
                kept_any += 1
            if rag_eval.expected_found(kept, entry["question"]):
                kept_expected += 1
        rows.append({"threshold": float(threshold), "total": total, "kept_any": kept_any,
                     "kept_expected": kept_expected})
    return rows


def _print_entry(entry: dict) -> None:
    """Печатает по одному вопросу: факты, вердикты и метрики всех режимов."""
    if entry["error"]:
        print(f"    сбой: {entry['error']}")
        return
    print(f"    без RAG: факты {entry['scores']['no_rag']:.2f}, "
          f"{report.metrics_line(entry['no_rag'])}")
    for name in MODE_NAMES:
        record = entry["records"].get(name)
        if record is None:
            print(f"    {name}: сбой: {entry['mode_errors'].get(name, '')}")
            continue
        marker = "" if entry["found"].get(name) else "  [источник не найден]"
        print(f"    {name}: факты {entry['scores'][name]:.2f} → "
              f"{entry['verdicts'][name]} vs без RAG, "
              f"{entry['vs_baseline'][name]} vs baseline; "
              f"{report.metrics_line(record)}{marker}")
        for key in ("rewrite_warning", "rerank_warning", "filter_warning"):
            if record.get(key):
                print(f"      ⚠ {key}: {record[key]}")


def _fallbacks(entries: list) -> int:
    """Сколько ответов режимов получено откатом на вызов без контекста."""
    return sum(1 for entry in entries for name in MODE_NAMES
               if (entry["records"].get(name) or {}).get("fallback"))


def _failures(entries: list) -> int:
    """Сколько запросов сорвалось: вопросы без «без RAG» или без режима."""
    return sum((1 if entry["error"] else 0) + len(entry["mode_errors"])
               for entry in entries)


if __name__ == "__main__":
    sys.exit(main())
