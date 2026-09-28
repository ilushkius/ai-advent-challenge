"""Сквозной прогон дня 21: пять сценариев индексации и отчёт.

Что проверяется — пять сценариев из задания: полный демо-прогон обеих стратегий,
одиночная стратегия, поиск по индексу, качество поиска на обеих стратегиях и
перезапуск без переиндексации — описано в ``scripts/indexing_scenarios.py``. Здесь
только оркестрация: поднять стенд (документы дня, БД дня и рабочие файлы
``index/*.index``), прогнать сценарии, собрать данные и записать отчёт
``docs/reports/indexing_demo.md``.

По умолчанию используется НАСТОЯЩАЯ модель эмбеддингов
(``paraphrase-multilingual-MiniLM-L12-v2``): первый запуск скачивает веса в
``index/models`` (~470 МБ) и считает векторы на CPU — это занимает минуты.
Флаг ``--stub-embedder`` подменяет модель детерминированным хеш-эмбеддером: прогон
и отчёт собираются офлайн, но качество поиска тогда НЕ показательно (это печатается
в выводе и попадает в отчёт).

Запуск из папки day21/::

    uv run python scripts/indexing_demo.py --stub-embedder
    uv run python scripts/indexing_demo.py --report docs/reports/indexing_demo.md
    uv run python scripts/indexing_demo.py --skip-scenarios
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня
# и в корне репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain.index_metrics import ascii_histogram  # noqa: E402
from backend.services.embedding_service import EmbeddingService  # noqa: E402
from indexing_report import write_report  # noqa: E402
from indexing_scenarios import (  # noqa: E402
    STUB_MODEL_NAME,
    DemoStand,
    HashEmbedder,
    print_summary,
    run_all,
)

#: Путь отчёта и снимка интерфейса по умолчанию (оба — в docs/reports/).
DEFAULT_REPORT = "docs/reports/indexing_demo.md"
DEFAULT_SCREENSHOT = "docs/reports/indexing_ui.png"

#: Сколько примеров чанков каждой стратегии попадает в отчёт.
SAMPLE_CHUNKS = 5


def main(argv=None) -> int:
    """Прогоняет сценарии, собирает данные и пишет отчёт; код 1 при провале."""
    args = _parse_args(argv)
    stub = bool(args.stub_embedder)
    echo = print
    echo("День 21: прогон индексации документов")
    echo(f"эмбеддер: {'ЗАГЛУШКА — ' + STUB_MODEL_NAME if stub else 'настоящая модель'}"
         + ("" if stub else " (первый запуск скачивает веса в index/models)"))
    stand = DemoStand(embedder=HashEmbedder() if stub else EmbeddingService())
    results = [] if args.skip_scenarios else run_all(stand, echo=echo)
    if results:
        print_summary(results, echo=echo)
    run_id = _demo_run_id(results)
    report_path = _write(stand, run_id, Path(args.report), Path(args.screenshot),
                         results, echo=echo)
    echo("")
    echo(f"отчёт: {report_path}")
    if stub:
        echo("ВНИМАНИЕ: прогон был с заглушкой — качество поиска не показательно.")
    failed = [result for result in results if not result.ok]
    return 1 if failed else 0


def _parse_args(argv):
    """Разбирает аргументы командной строки прогона."""
    parser = argparse.ArgumentParser(
        description="Сценарии индексации дня 21: две стратегии чанкинга, FAISS и отчёт",
    )
    parser.add_argument("--stub-embedder", action="store_true",
                        help="подменить модель детерминированным хеш-эмбеддером "
                             "(офлайн-прогон, качество поиска не показательно)")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--screenshot", default=DEFAULT_SCREENSHOT,
                        help="путь к снимку интерфейса; если файла нет, отчёт "
                             "собирается без картинки")
    parser.add_argument("--skip-scenarios", action="store_true",
                        help="собрать отчёт по уже построенным индексам без прогона")
    return parser.parse_args(argv)


def _demo_run_id(results) -> int | None:
    """Номер демо-запуска из сценария 1 (``None`` — сценарий не выполнялся)."""
    for result in results:
        if result.name.startswith("1."):
            return (result.data.get("report") or {}).get("run_id")
    return None


def _write(stand: DemoStand, run_id, report_path: Path, screenshot_path: Path,
           results, *, echo=print) -> Path:
    """Собирает данные прогона и пишет markdown-отчёт."""
    run_data = stand.indexing_service.run(run_id) if run_id else {"metrics": {}}
    stats = stand.index_service.stats()
    samples = {strategy: stand.index_service.sample_chunks(strategy, SAMPLE_CHUNKS)
               for strategy in ("fixed", "structural")}
    charts = {strategy: ascii_histogram((stats.get(strategy) or {}).get("histogram"))
              for strategy in ("fixed", "structural")}
    queries = (run_data.get("metrics") or {}).get("queries") or []
    screenshot = str(screenshot_path) if screenshot_path.exists() else ""
    if not screenshot:
        echo(f"снимок интерфейса не найден ({screenshot_path}) — отчёт без картинки")
    return write_report(report_path, run_data, stats=stats, chunk_samples=samples,
                        queries=queries, scenarios=results, ascii_charts=charts,
                        screenshot=screenshot)


if __name__ == "__main__":
    sys.exit(main())
