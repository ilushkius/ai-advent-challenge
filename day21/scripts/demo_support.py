"""Прогон демо ассистента поддержки (день 33): пять сценариев клиента и отчёт.

Скрипт идёт ТЕМ ЖЕ путём, что раздел «🎧 Поддержка пользователей»: служба
``SupportService`` собирает контекст из трёх источников (фрагменты документации
поддержки из индекса корпуса, профиль клиента и его тикет из MCP-сервера
``support_server``, раздел продукта по словам вопроса), отвечает моделью провайдера
и возвращает источники, контекст клиента и записи вызовов инструментов. Индекс и
корпус берутся ЖИВЫЕ — те же файлы, что у бэкенда: скрипт ничего не пересобирает,
иначе отчёт описывал бы другой корпус.

Пять сценариев покрывают все ветки службы: вопрос с тикетом (профиль подтягивается
из тикета), вопрос с профилем без тикета, вопрос про оплату с чужим тикетом, общий
вопрос без контекста клиента и вопрос клиента с открытыми тикетами.

Запуск из папки day21/ (перед первым прогоном пересоберите индекс с документацией
поддержки)::

    uv run python scripts/reindex_with_support.py
    uv run python scripts/demo_support.py
    uv run python scripts/demo_support.py --provider local
    uv run python scripts/demo_support.py --no-report

Отчёт — ``docs/reports/support_demo.md``. Коды возврата: 0 — все строки
подтверждены источниками или контекстом клиента, 1 — есть строки с предупреждением
или отказом, 2 — индекс поддержки пуст или модель недоступна (отчёт не пишется:
прогон без индекса описал бы работу ассистента неверно).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня и в
# корне репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import llm_provider, rag_mode, support  # noqa: E402
from backend.services.rag_corpus_loader import RagCorpusLoader  # noqa: E402
from backend.services.support_service import SupportService  # noqa: E402
from backend.storage.chunk_store import ChunkStore  # noqa: E402

#: Отчёт прогона: тот же файл, на который ссылается README дня.
DEFAULT_REPORT = DAY_ROOT / "docs" / "reports" / "support_demo.md"

#: Сколько символов ответа печатать на экран и показывать в таблице отчёта.
PRINT_LIMIT = 300
ANSWER_LIMIT = 200
#: Признак того, что ответ пришёл по документации, а индекс пуст.
INDEX_WARNING = support.WARN_INDEX_EMPTY.split("{")[0]
#: Признак недоступного провайдера в вердикте строки.
PROVIDER_FAILED = "❌ провайдер недоступен"


def build_parser() -> argparse.ArgumentParser:
    """Аргументы прогона: провайдер, путь отчёта и его отключение."""
    parser = argparse.ArgumentParser(
        description="Прогнать пять сценариев демо через ассистента поддержки.",
    )
    parser.add_argument("--provider", choices=llm_provider.PICKER_PROVIDERS,
                        default=llm_provider.PROVIDER_DEEPSEEK,
                        help="провайдер ответа (по умолчанию deepseek)")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--no-report", action="store_true",
                        help="не писать отчёт: только печать строк прогона")
    return parser


def dataset_counts() -> dict:
    """Размеры базы поддержки: отчёт о состоянии датасета, а не путь службы.

    База читается напрямую (``json.loads``) только здесь: служба ходит в данные
    инструментами MCP, а отчёту нужно сказать, на каком датасете шёл прогон.
    """
    path = DAY_ROOT / support.DB_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"users": 0, "tickets": 0, "products": 0, "error": str(exc)}
    return {
        "users": len(data.get("users") or []),
        "tickets": len(data.get("tickets") or []),
        "products": len(data.get("products") or []),
        "error": "",
    }


def context() -> dict:
    """Контекст запуска для отчёта: корпус, документация поддержки и база клиентов.

    Числа берутся из тех же служб, что и у бэкенда (загрузчик корпуса, хранилище
    чанков, файл базы), поэтому отчёт описывает состояние, на котором прогон
    действительно шёл, а не состояние из документации.
    """
    store = ChunkStore()
    doc_counts = {
        strategy: sum(int(store.counts_by_source(strategy).get(slug) or 0)
                      for slug in support.SUPPORT_SLUGS)
        for strategy in rag_mode.RAG_STRATEGIES
    }
    return {"corpus": RagCorpusLoader().status(), "doc_counts": doc_counts,
            "doc_files": len(support.SUPPORT_SOURCES), "dataset": dataset_counts()}


def run_scenarios(service: SupportService, provider: str) -> list:
    """Пять сценариев демо: печать строк прогона и записи для отчёта."""
    total = len(support.DEMO_SCENARIOS)
    rows = []
    for position, scenario in enumerate(support.DEMO_SCENARIOS, start=1):
        record = service.answer(scenario["question"], scenario["user_id"] or None,
                                scenario["ticket_id"] or None, provider)
        record["label"] = scenario["label"]
        record["question"] = scenario["question"]
        record["user_id"] = scenario["user_id"]
        record["ticket_id"] = scenario["ticket_id"]
        record["verdict"] = support.verdict(record)
        print(f"[{position}/{total}] {scenario['label']}: {scenario['question']}")
        print(f"  контекст: user={scenario['user_id'] or '—'}, "
              f"ticket={scenario['ticket_id'] or '—'}")
        print(f"  ответ: {_flat(record['answer'], PRINT_LIMIT)}")
        print(f"  источники: {_sources_text(record['sources'])}")
        print(f"  MCP: {_tools_text(record['mcp_tools_used'])}")
        print(f"  время: {record['duration_ms'] / 1000:.2f} с")
        for warning in record["warnings"]:
            print(f"  предупреждение: {warning}")
        rows.append(record)
    return rows


def write_report(path: Path, rows: list, meta: dict) -> Path:
    """Пишет markdown-отчёт прогона и возвращает путь к файлу."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Отчёт дня 33: ассистент поддержки пользователей",
        "",
        f"Прогон: {meta['stamp']}, скрипт `scripts/demo_support.py`, "
        f"провайдер {meta['provider_label']}. Ответ собирается из документации "
        "поддержки (RAG), профиля клиента и тикета (MCP-сервер `support_server`).",
        "",
        "## Контекст запуска",
        "",
    ]
    lines.extend(f"* {item}" for item in _context_lines(meta))
    lines.extend([
        "",
        "## Сводка прогона",
        "",
        "| # | Сценарий | Вопрос | Контекст (user/ticket) | Источники RAG | "
        "MCP-инструменты | Ответ | Вердикт |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for position, row in enumerate(rows, start=1):
        lines.append("| " + " | ".join([
            str(position), _cell(row["label"], 60), _cell(row["question"], 120),
            _cell(_context_text(row), 120), _cell(_sources_text(row["sources"]), 90),
            _cell(_tools_text(row["mcp_tools_used"]), 90),
            _cell(row["answer"], ANSWER_LIMIT), _cell(row["verdict"], 40),
        ]) + " |")
    for position, row in enumerate(rows, start=1):
        lines.extend(["", f"## Сценарий {position}", "",
                      f"**{row['label']}**: {row['question']}", "",
                      row["answer"] or "(пустой ответ)", ""])
        lines.append(f"Контекст: {_context_text(row)} · время: "
                     f"{row['duration_ms'] / 1000:.2f} с · вердикт {row['verdict']}")
        if row["warnings"]:
            lines.extend(["", "Предупреждения:", ""])
            lines.extend(f"* {warning}" for warning in row["warnings"])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _context_lines(meta: dict) -> list:
    """Пункты раздела «Контекст запуска»: корпус, документация, база клиентов."""
    corpus = meta["corpus"]
    counts = meta["doc_counts"]
    dataset = meta["dataset"]
    return [
        f"корпус: {corpus['documents']} документов, {corpus['chars']} символов "
        f"(~{corpus['pages']} страниц)",
        f"документация поддержки: {meta['doc_files']} файлов, чанков "
        f"{counts[rag_mode.RAG_STRATEGY_FIXED]} ({rag_mode.RAG_STRATEGY_FIXED}) и "
        f"{counts[rag_mode.RAG_STRATEGY_STRUCTURAL]} "
        f"({rag_mode.RAG_STRATEGY_STRUCTURAL}) при минимуме "
        f"{support.SUPPORT_MIN_CHUNKS} на стратегию",
        f"база поддержки: клиентов {dataset['users']}, тикетов {dataset['tickets']}, "
        f"разделов продукта {dataset['products']}"
        + (f" (ошибка чтения: {dataset['error']})" if dataset["error"] else ""),
        f"MCP-сервер поддержки: {support.SUPPORT_SERVER_NAME}, "
        f"цель подключения `{support.SUPPORT_SERVER_TARGET}`",
    ]


def _context_text(row: dict) -> str:
    """Контекст строки: профиль и тикет так, как их увидел ответ модели."""
    parts = []
    user = row.get("user_context") or {}
    if user:
        parts.append(f"{user.get('id')} ({user.get('plan')})")
    ticket = row.get("ticket_context") or {}
    if ticket:
        parts.append(f"{ticket.get('id')} «{ticket.get('subject')}» "
                     f"({ticket.get('status')}, {ticket.get('priority')})")
    return " · ".join(parts) if parts else "нет"


def _sources_text(sources: list) -> str:
    """Источники одной строки: «файл · секция» через точку с запятой."""
    parts = [f"{item.get('source') or '—'} · {item.get('section') or '—'}"
             for item in sources]
    return "; ".join(parts) if parts else "нет"


def _tools_text(used: list) -> str:
    """Инструменты одной строки: «имя ok/ошибка» через точку с запятой."""
    parts = [f"{item.get('tool')} {'✅' if item.get('ok') else 'ошибка'}"
             for item in used]
    return "; ".join(parts) if parts else "нет"


def _flat(text: object, limit: int) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def _cell(text: object, limit: int) -> str:
    """Ячейка markdown-таблицы: обрезанный текст без вертикальных черт."""
    return _flat(text, limit).replace("|", "\\|") or "—"


def main(argv=None) -> int:
    """Прогоняет пять сценариев, печатает строки и пишет отчёт."""
    args = build_parser().parse_args(argv)
    service = SupportService()
    try:
        meta = {**context(), "provider_label": llm_provider.label(args.provider),
                "stamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
        rows = run_scenarios(service, args.provider)
    finally:
        service.close()
    if any(warning.startswith(INDEX_WARNING)
           for row in rows for warning in row["warnings"]):
        print("Индекс поддержки пуст: пересоберите его командой "
              "`uv run python scripts/reindex_with_support.py` и повторите прогон.")
        return 2
    if any(row["verdict"] == PROVIDER_FAILED for row in rows):
        source = ("Ollama на 127.0.0.1:11434" if args.provider == llm_provider.PROVIDER_LOCAL
                  else "DEEPSEEK_API_KEY в day21/.env")
        print(f"Провайдер {meta['provider_label']} недоступен: проверьте {source}.")
        return 2
    if not args.no_report:
        path = write_report(Path(args.report), rows, meta)
        print(f"отчёт: {path}")
    failed = [row for row in rows if not row["verdict"].startswith("✅")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
