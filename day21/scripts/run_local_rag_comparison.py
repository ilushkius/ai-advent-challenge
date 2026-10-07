"""Отчёт дня 28: один и тот же вопрос — на локальной модели Ollama и на облаке.

Скрипт ходит в бэкенд по HTTP (``POST /rag/compare_providers``) — тем же путём, что и
кнопка «🚀 Прогнать сравнение» в интерфейсе: отчёт подтверждает то, что видно в UI, а не
отдельную копию прогона. Сначала отвечает локальная модель, потом облако, а поиск по
корпусу у обеих сторон один и тот же и всегда локальный (FAISS-индекс дня 22 и
sentence-transformers).

Отчёт пишется один раз: разделы «Выводы» и «Ручная оценка» дописывает человек по факту
прогона, поэтому повторный прогон перезаписывает файл (для черновика —
``--report docs/reports/local_rag_comparison.draft.md``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

DAY_ROOT = Path(__file__).resolve().parents[1]

#: Адрес бэкенда: переопределяется ``--backend`` или переменной окружения.
BACKEND_URL = os.environ.get("DAY21_BACKEND_URL", "http://127.0.0.1:8000")

#: Предел ожидания прогона: десять вопросов × два провайдера в одном запросе.
REPORT_TIMEOUT = 3600.0

#: Предел ожидания справки о прогоне (``/rag/config``, ``/llm/provider``).
CONFIG_TIMEOUT = 30.0

#: Отчёт по умолчанию — рядом с отчётами предыдущих дней.
DEFAULT_REPORT = "docs/reports/local_rag_comparison.md"

#: Вопросы берутся из того же файла, что отдаёт ``GET /rag/demo-questions``.
QUESTIONS_PATH = DAY_ROOT / "backend" / "data" / "demo_questions.json"

#: Обрезка ответа в таблице (полные ответы — в приложении отчёта).
TABLE_CHARS = 300

#: Подпись пустой ячейки.
DASH = "—"

#: Режимы, ответ которых в таблицу не выносится: ответа по корпусу в них нет.
EMPTY_MODES = ("dont_know", "error")


def main(argv=None) -> int:
    """Прогоняет вопросы через эндпоинт, пишет отчёт и печатает сводку."""
    args = _parse_args(argv)
    texts = _questions(args.limit)
    if not texts:
        print(f"вопросы не загрузились: проверьте {QUESTIONS_PATH}")
        return 1
    backend = str(args.backend).rstrip("/")
    try:
        config = requests.get(f"{backend}/rag/config", timeout=CONFIG_TIMEOUT).json()
        provider = requests.get(f"{backend}/llm/provider",
                                timeout=CONFIG_TIMEOUT).json()
    except requests.RequestException as exc:
        return _offline(backend, exc)
    started = time.perf_counter()
    try:
        response = requests.post(
            f"{backend}/rag/compare_providers",
            json={"questions": texts, "top_k": int(args.top_k),
                  "strategy": args.strategy},
            timeout=REPORT_TIMEOUT)
    except requests.RequestException as exc:
        return _offline(backend, exc)
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        print(f"бэкенд ответил {response.status_code}: {response.text}")
        return 1
    result = response.json()
    text = render_report(result, config=config, provider=provider,
                         strategy=args.strategy, elapsed=elapsed)
    target = _target(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    _print_run(result, target, elapsed)
    return 1 if _failed_rows(result) else 0


def render_report(result: dict, *, config: dict, provider: dict,
                  strategy=None, elapsed: float = 0.0) -> str:
    """Markdown-отчёт: шапка с настройками, правило вердикта, таблица, приложение, итог."""
    rows = list(result.get("rows") or [])
    lines = _header(config, provider, strategy, rows, elapsed)
    lines += [""] + _verdict_rule()
    lines += ["", "## Таблица сравнения", ""]
    lines += _table(rows)
    lines += ["", "## Приложение: полные ответы", ""]
    lines += _appendix(rows)
    lines += ["", "## Итог", ""]
    lines += _totals(result.get("summary") or {}, rows)
    return "\n".join(lines) + "\n"


def _header(config: dict, provider: dict, strategy, rows: list, elapsed: float) -> list:
    """Шапка отчёта: фактическая модель, корпус, стратегия, лимиты и время прогона."""
    corpus = config.get("corpus") or {}
    indexes = " · ".join(f"{item.get('strategy')}: {int(item.get('chunks') or 0)}"
                         for item in (config.get("indexes") or [])) or DASH
    chosen = strategy or config.get("default_strategy") or DASH
    return [
        "# Локальный RAG: сравнение локальной и облачной модели (день 28)",
        "",
        f"* дата прогона: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"* локальная модель: {provider.get('local_model') or DASH} "
        f"({provider.get('local_url') or DASH}, предел ожидания "
        f"{provider.get('local_timeout') or DASH} с)",
        f"* провайдер по умолчанию: {provider.get('provider') or DASH}",
        f"* стратегия поиска: {chosen}, top_k: {config.get('top_k_default') or DASH} "
        "фрагментов в контексте каждой стороне",
        f"* корпус: документов {corpus.get('documents') or 0}, "
        f"страниц {corpus.get('pages') or 0}, символов {corpus.get('chars') or 0}",
        f"* чанки по стратегиям: {indexes} (всего {config.get('chunks_total') or 0})",
        f"* порог релевантности: {float(config.get('relevance_threshold') or 0.0):g} "
        "— ниже него строки приходят в режиме «не знаю» без вызова модели",
        f"* вопросов: {len(rows)}, время прогона: {elapsed:.1f} с",
        "",
        "Воспроизведение (нужны запущенный бэкенд, Ollama и `DEEPSEEK_API_KEY` в "
        "`day21/.env`):",
        "",
        "```",
        "uv run python scripts/run_local_rag_comparison.py",
        "```",
    ]


def _verdict_rule() -> list:
    """Раздел «Как считался вердикт»: правило домена и что именно сравнивается."""
    return [
        "## Как считался вердикт",
        "",
        "Строка считается так (`backend/domain/rag_compare.py`):",
        "",
        "1. ответил ли провайдер по корпусу — режим `rag` и не `fallback` "
        "(режимы `dont_know` и `error` проигрывают любому ответу по корпусу);",
        "2. среди ответивших — подтверждённые цитаты (`quotes_verified`), затем "
        "уверенность (`confidence`), затем число источников.",
        "",
        "Источники в обеих колонках получены **одним и тем же локальным отбором** "
        "(FAISS-индекс дня 22 и sentence-transformers), поэтому колонка «Источники» "
        "сравнивает не retrieval, а то, воспользовалась ли модель контекстом: числа "
        "источников совпадают, различается ответ.",
    ]


def _table(rows: list) -> list:
    """Таблица сравнения: обе стороны построчно плюс вердикт."""
    lines = ["| № | Вопрос | Ответ local | Ответ cloud | Источники (local / cloud) | "
             "Время local, с | Время cloud, с | Режим (local / cloud) | Вердикт |",
             "|---|---|---|---|---|---|---|---|---|"]
    for number, row in enumerate(rows, 1):
        local, cloud = _side(row, "local"), _side(row, "cloud")
        lines.append("| " + " | ".join([
            str(number),
            _cell(row.get("question")),
            _answer_cell(local),
            _answer_cell(cloud),
            f"{len(local.get('sources') or [])} / {len(cloud.get('sources') or [])}",
            f"{_seconds(local):.2f}",
            f"{_seconds(cloud):.2f}",
            f"{local.get('mode') or DASH} / {cloud.get('mode') or DASH}",
            _cell(row.get("verdict")),
        ]) + " |")
    return lines


def _appendix(rows: list) -> list:
    """Приложение: полный ответ каждой стороны, её источники и предупреждения."""
    lines: list = []
    for number, row in enumerate(rows, 1):
        lines += [f"### {number}. {_cell(row.get('question'), limit=0)}", ""]
        for title, name in (("Локальная модель (Ollama · local)", "local"),
                            ("Облако (DeepSeek · deepseek)", "cloud")):
            record = _side(row, name)
            lines += [f"**{title}** — режим `{record.get('mode') or DASH}` · "
                      f"{_seconds(record):.2f} с · провайдер "
                      f"`{record.get('provider') or DASH}`", "", _quote(record), ""]
            lines += [f"источники: {_sources(record)}", ""]
            warning = str(record.get("warning") or "").strip()
            if warning:
                lines += [f"предупреждение: {_escape(warning)}", ""]
    return lines


def _totals(summary: dict, rows: list) -> list:
    """Итог прогона: средние времена, режимы, источники, вердикты."""
    local_ms, cloud_ms = int(summary.get("local_avg_ms") or 0), \
        int(summary.get("cloud_avg_ms") or 0)
    lines = [
        f"* всего вопросов: {summary.get('total') or 0}",
        f"* среднее время: локальная {local_ms / 1000:.2f} с, облачная "
        f"{cloud_ms / 1000:.2f} с — {_ratio(local_ms, cloud_ms)}",
        f"* ответов с источниками: local {summary.get('local_with_sources') or 0}, "
        f"cloud {summary.get('cloud_with_sources') or 0} "
        "(источники приходят из одного и того же локального отбора)",
        f"* режим `rag`: local {summary.get('local_rag') or 0}, "
        f"cloud {summary.get('cloud_rag') or 0}",
        f"* `dont_know`: local {summary.get('local_dont_know') or 0}, "
        f"cloud {summary.get('cloud_dont_know') or 0}",
        f"* подтверждённых цитат: local {summary.get('local_verified') or 0}, "
        f"cloud {summary.get('cloud_verified') or 0}",
        f"* вердикты строк: локально лучше {summary.get('better_local') or 0}, "
        f"облако лучше {summary.get('better_cloud') or 0}, "
        f"равно {summary.get('equal') or 0}",
        f"* общий вердикт прогона: {summary.get('verdict') or DASH}",
        f"* строк с режимом `error`: {len(_failed_rows({'rows': rows}))}",
    ]
    return lines


def _print_run(result: dict, target: Path, elapsed: float) -> None:
    """Печать строк прогона, сводки и пути отчёта."""
    rows = list(result.get("rows") or [])
    for number, row in enumerate(rows, 1):
        local, cloud = _side(row, "local"), _side(row, "cloud")
        print(f"{number:2d}. {_one_line(row.get('question'), 60)} — "
              f"local {local.get('mode') or DASH} {_seconds(local):.1f} с, "
              f"cloud {cloud.get('mode') or DASH} {_seconds(cloud):.1f} с, "
              f"вердикт: {row.get('verdict') or DASH}")
    summary = result.get("summary") or {}
    print(f"итог: {summary.get('total') or 0} вопросов, "
          f"среднее время local {int(summary.get('local_avg_ms') or 0) / 1000:.2f} с / "
          f"cloud {int(summary.get('cloud_avg_ms') or 0) / 1000:.2f} с, "
          f"вердикт прогона: {summary.get('verdict') or DASH}")
    print(f"ошибок в строках: {len(_failed_rows(result))}, время прогона: "
          f"{elapsed:.1f} с")
    print(f"отчёт: {target}")


def _offline(backend: str, exc: Exception) -> int:
    """Бэкенд недоступен: подсказки по запуску и код возврата 1."""
    print(f"бэкенд недоступен ({backend}): {exc}")
    print("что нужно для прогона (из папки day21/):")
    print("  1) uv run uvicorn backend.api.main:app --port 8000")
    print("  2) ollama serve  (и модель: ollama list)")
    print("  3) DEEPSEEK_API_KEY в day21/.env — без него облачных ответов не будет")
    print(f"  другой адрес: --backend http://127.0.0.1:<port>")
    return 1


def _failed_rows(result: dict) -> list:
    """Строки с режимом ``error`` у любой из сторон: код возврата 1."""
    return [number for number, row in enumerate(result.get("rows") or [], 1)
            if any(_side(row, side).get("mode") == "error"
                   for side in ("local", "cloud"))]


def _questions(limit: int = 0) -> list:
    """Тексты контрольных вопросов демо; ``--limit`` оставляет первые N."""
    try:
        payload = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"набор вопросов не прочитан ({QUESTIONS_PATH}): {exc}")
        return []
    texts = [str(item.get("question") or "").strip()
             for item in (payload.get("questions") or [])]
    texts = [text for text in texts if text]
    return texts[:max(1, int(limit))] if limit else texts


def _parse_args(argv):
    """Аргументы прогона: отчёт, адрес бэкенда, top_k, стратегия, ограничение набора."""
    parser = argparse.ArgumentParser(
        description="Сравнение локальной и облачной модели RAG на вопросах корпуса.")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help="путь к markdown-отчёту (по умолчанию %(default)s)")
    parser.add_argument("--backend", default=BACKEND_URL,
                        help="адрес бэкенда (по умолчанию %(default)s)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="сколько фрагментов корпуса идёт в контекст (по умолчанию "
                             "%(default)s)")
    parser.add_argument("--strategy", default=None,
                        help="стратегия поиска (по умолчанию — стратегия бэкенда)")
    parser.add_argument("--limit", type=int, default=0,
                        help="сколько первых вопросов брать (0 — все)")
    return parser.parse_args(argv)


# ---------- значения для markdown ----------
def _side(row: dict, name: str) -> dict:
    """Запись стороны строки (``local``/``cloud``); отсутствующая — пустая."""
    return row.get(name) or {}


def _seconds(record: dict) -> float:
    """Время ответа стороны в секундах."""
    return int(record.get("duration_ms") or 0) / 1000


def _ratio(local_ms: int, cloud_ms: int) -> str:
    """Во сколько раз облако быстрее (или медленнее) локальной модели."""
    if not local_ms or not cloud_ms:
        return "сравнить не с чем"
    if local_ms >= cloud_ms:
        return f"облако быстрее в {local_ms / cloud_ms:.1f} раза"
    return f"локальная быстрее в {cloud_ms / local_ms:.1f} раза"


def _sources(record: dict) -> str:
    """Источники стороны: ``источник · раздел · балл``; пусто — прочерк."""
    sources = record.get("sources") or []
    if not sources:
        return DASH
    return "; ".join(f"{item.get('source') or DASH} · {item.get('section') or DASH} · "
                     f"{item.get('score') if item.get('score') is not None else DASH}"
                     for item in sources)


def _answer_cell(record: dict) -> str:
    """Ответ стороны для таблицы: режимы «не знаю» и «ошибка» печатаются прочерком."""
    if record.get("mode") in EMPTY_MODES:
        return DASH
    return _cell(record.get("answer"))


def _quote(record: dict) -> str:
    """Полный ответ стороны цитатой; пусто — прочерк."""
    value = str(record.get("answer") or "").strip()
    if not value:
        return f"> {DASH}"
    return "\n".join(f"> {_escape(line)}" for line in value.splitlines())


def _escape(value) -> str:
    """Вертикальная черта внутри ячейки таблицы не должна её разрывать."""
    return str(value or "").replace("|", "\\|")


def _cell(value, limit: int = TABLE_CHARS) -> str:
    """Ячейка markdown: одна строка, без вертикальных черт, с обрезкой и прочерком."""
    text = _escape(" ".join(str(value or "").split()))
    if not text:
        return DASH
    return text if not limit or len(text) <= limit else f"{text[:limit].rstrip()}…"


def _one_line(value, limit: int) -> str:
    """Обрезка текста для строки консоли."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


def _target(value: str) -> Path:
    """Путь отчёта: относительный считается от корня дня."""
    path = Path(value)
    return path if path.is_absolute() else DAY_ROOT / path


if __name__ == "__main__":
    sys.exit(main())
