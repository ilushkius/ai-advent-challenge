"""Прогон демо ассистента разработчика (день 31): пять вопросов ``/help`` и отчёт.

Скрипт идёт ТЕМ ЖЕ путём, что раздел «🧑‍💻 Ассистент разработчика»: служба
``DevAssistantService`` собирает контекст из двух источников (фрагменты
документации проекта из индекса корпуса и ответы инструментов MCP-сервера
``dev_server``), отвечает моделью провайдера и возвращает источники, вызовы
инструментов и предупреждения. Индекс и корпус берутся ЖИВЫЕ — те же файлы, что у
бэкенда: скрипт ничего не пересобирает, иначе отчёт описывал бы другой корпус.

Пять вопросов покрывают все ветки службы: два вопроса по документации (память
агента, запуск тестов), два по репозиторию (ветка, изменённые файлы) и один про
структуру проекта: у строк отчёта видно, какие источники и инструменты сработали.

Запуск из папки day21/ (перед первым прогоном пересоберите индекс с документацией)::

    uv run python scripts/reindex_with_docs.py
    uv run python scripts/demo_dev_assistant.py
    uv run python scripts/demo_dev_assistant.py --provider local
    uv run python scripts/demo_dev_assistant.py --no-report

Отчёт — ``docs/reports/dev_assistant_demo.md``. Коды возврата: 0 — все строки
подтверждены источниками или MCP-данными, 1 — есть строки с предупреждением или
отказом, 2 — индекс документации пуст или модель недоступна (отчёт не пишется:
прогон без индекса описал бы работу ассистента неверно).
"""
from __future__ import annotations

import argparse
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

from backend.domain import dev_assistant, llm_provider, rag_mode  # noqa: E402
from backend.services.dev_assistant_service import DevAssistantService  # noqa: E402
from backend.services.rag_corpus_loader import RagCorpusLoader  # noqa: E402
from backend.storage.chunk_store import ChunkStore  # noqa: E402

#: Отчёт прогона: тот же файл, на который ссылается README дня.
DEFAULT_REPORT = DAY_ROOT / "docs" / "reports" / "dev_assistant_demo.md"

#: Сколько символов ответа печатать на экран и показывать в таблице отчёта.
PRINT_LIMIT = 300
ANSWER_LIMIT = 200
#: Признак того, что ответ пришёл по документации, а индекс пуст.
INDEX_WARNING = dev_assistant.WARN_INDEX_EMPTY.split("{")[0]


def build_parser() -> argparse.ArgumentParser:
    """Аргументы прогона: провайдер, путь отчёта и его отключение."""
    parser = argparse.ArgumentParser(
        description="Прогнать пять вопросов демо через ассистента разработчика.",
    )
    parser.add_argument("--provider", choices=llm_provider.PICKER_PROVIDERS,
                        default=llm_provider.PROVIDER_DEEPSEEK,
                        help="провайдер ответа (по умолчанию deepseek)")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--no-report", action="store_true",
                        help="не писать отчёт: только печать строк прогона")
    return parser


def context(service: DevAssistantService) -> dict:
    """Контекст запуска для отчёта: корпус, документация, инструменты и git.

    Числа берутся из тех же служб, что и у бэкенда (загрузчик корпуса, хранилище
    чанков, MCP-инструменты), поэтому отчёт описывает состояние, на котором прогон
    действительно шёл, а не состояние из документации. MCP-инструменты спрашиваются
    у службы прогона: второе соединение со stdio-сервером не нужно.
    """
    store = ChunkStore()
    doc_counts = {strategy: sum(int(store.counts_by_source(strategy).get(slug) or 0)
                                for slug in dev_assistant.DOCUMENTATION_SLUGS)
                  for strategy in rag_mode.RAG_STRATEGIES}
    return {"corpus": RagCorpusLoader().status(), "doc_counts": doc_counts,
            "doc_files": len(dev_assistant.DOCUMENTATION_SOURCES),
            "tools": service.tools(), "git": service.git_context()}


def run_questions(service: DevAssistantService, provider: str) -> list:
    """Пять вопросов демо: печать строк прогона и записи для отчёта."""
    total = len(dev_assistant.DEMO_QUESTIONS)
    rows = []
    for position, question in enumerate(dev_assistant.DEMO_QUESTIONS, start=1):
        record = service.handle_help(question, provider)
        record["verdict"] = dev_assistant.verdict(record)
        print(f"[{position}/{total}] {question}")
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
        "# День 31 — ассистент разработчика: /help по документации и git-контексту",
        "",
        f"Прогон: {meta['stamp']}, скрипт `scripts/demo_dev_assistant.py`, "
        f"провайдер {meta['provider_label']}. Отчёт снят до коммита дня, поэтому "
        "инструмент `get_git_diff` показывает незакоммиченные правки дня.",
        "",
        "## Контекст запуска",
        "",
    ]
    lines.extend(f"* {item}" for item in _context_lines(meta))
    lines.extend([
        "",
        "## Сводка прогона",
        "",
        "| # | Вопрос | Источники RAG | MCP-инструменты | Ответ | Вердикт |",
        "|---|---|---|---|---|---|",
    ])
    for position, row in enumerate(rows, start=1):
        lines.append("| " + " | ".join([
            str(position), _cell(row["question"], 120), _cell(_sources_text(row["sources"]), 90),
            _cell(_tools_text(row["mcp_tools_used"]), 90),
            _cell(row["answer"], ANSWER_LIMIT), _cell(row["verdict"], 40),
        ]) + " |")
    for position, row in enumerate(rows, start=1):
        lines.extend(["", f"## Вопрос {position}", "", f"**{row['question']}**", "",
                      row["answer"] or "(пустой ответ)", ""])
        lines.append(f"Тип вопроса: {row['question_type']} · время: "
                     f"{row['duration_ms'] / 1000:.2f} с · вердикт: {row['verdict']}")
        if row["warnings"]:
            lines.extend(["", "Предупреждения:", ""])
            lines.extend(f"* {warning}" for warning in row["warnings"])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _context_lines(meta: dict) -> list:
    """Пункты раздела «Контекст запуска»: корпус, документация, инструменты, git."""
    corpus = meta["corpus"]
    counts = meta["doc_counts"]
    tools = meta["tools"]
    git = meta["git"]
    lines = [
        f"корпус: {corpus['documents']} документов, {corpus['chars']} символов "
        f"(~{corpus['pages']} страниц)",
        f"документация проекта: {meta['doc_files']} файлов, чанков "
        f"{counts[rag_mode.RAG_STRATEGY_FIXED]} ({rag_mode.RAG_STRATEGY_FIXED}) и "
        f"{counts[rag_mode.RAG_STRATEGY_STRUCTURAL]} "
        f"({rag_mode.RAG_STRATEGY_STRUCTURAL}) при минимуме "
        f"{dev_assistant.DOCUMENTATION_MIN_CHUNKS} на стратегию",
        f"MCP-инструментов сервера разработки: {tools['count']}"
        + (f" (ошибка подключения: {tools['error']})" if tools["error"] else ""),
        f"репозиторий: ветка {git['branch'] or '—'}, коммит {git['last_commit'] or '—'}"
        + (f", ошибка: {git['error']}" if git["error"] else ""),
        "изменённых файлов: " + (
            ", ".join(f"`{path}`" for path in git["modified_files"]) or "нет"),
    ]
    return lines


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
    """Прогоняет пять вопросов, печатает строки и пишет отчёт."""
    args = build_parser().parse_args(argv)
    service = DevAssistantService()
    try:
        meta = {**context(service), "provider_label": llm_provider.label(args.provider),
                "stamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
        rows = run_questions(service, args.provider)
    finally:
        service.close()
    if any(warning.startswith(INDEX_WARNING)
           for row in rows for warning in row["warnings"]):
        print("Индекс документации пуст: пересоберите его командой "
              "`uv run python scripts/reindex_with_docs.py` и повторите прогон.")
        return 2
    if any(row["verdict"] == "❌ провайдер недоступен" for row in rows):
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
