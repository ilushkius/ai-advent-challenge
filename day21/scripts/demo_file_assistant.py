"""Прогон демо ассистента файлов (день 34): три сценария цели и отчёт о результате.

Скрипт идёт ТЕМ ЖЕ путём, что раздел «🗂 Ассистент файлов»: служба
``FileAssistantService`` просит модель собрать план шагов из ЦЕЛИ пользователя, проверяет
план правилами домена, исполняет шаги через свой MCP-сервер ``file_server`` (чтение,
поиск, список, запись, замена, diff) и возвращает журнал, списки файлов, diff и сводку.
Файлы берутся ЖИВЫЕ — рабочее дерево ``day21/``, а не копия: иначе отчёт описывал бы
другой проект.

Три сценария покрывают все исходы дня: только чтение (поиск использования компонента),
правка существующего файла (раздел в ``docs/usage.md``) и создание нового
(``docs/adr/0001-deepseek-primary.md``). Отчёт — журнал прогона: его diff — это diff
ТОГО прогона, который применил изменения.

Запуск из папки day21/::

    uv run python scripts/demo_file_assistant.py --dry-run --no-report
    uv run python scripts/demo_file_assistant.py
    uv run python scripts/demo_file_assistant.py --provider local
    uv run python scripts/demo_file_assistant.py --dry-run --report docs/reports/fa.md

Режим ``--dry-run`` безопасен и повторяем: ``write_file`` и ``apply_patch`` в нём не
вызываются, diff — предполагаемый. Обычный прогон МЕНЯЕТ файлы, поэтому повторять его
сценариями 2–3 не нужно: патч вставил бы раздел второй раз. Для повторных проверок —
только ``--dry-run``.

Коды возврата: 0 — все вердикты ✅ или 🧪 (репетиция без ошибок тоже 0); 1 — есть ❌ или
⚠️; 2 — провайдер недоступен (ни один сценарий не дошёл до сводки) или отчёт не записан.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня и в корне
# репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import file_assistant, llm_provider  # noqa: E402
from backend.domain.file_assistant_report import verdict  # noqa: E402
from backend.services.file_assistant_service import (  # noqa: E402
    FileAssistantError,
    FileAssistantService,
)

#: Отчёт прогона: тот же файл, на который ссылается README дня.
DEFAULT_REPORT = DAY_ROOT / "docs" / "reports" / "file_assistant_demo.md"

#: Пределы текста на экране и в таблице отчёта.
PRINT_LIMIT = 300
CELL_LIMIT = 110
PLAN_LIMIT = 90
DIFF_CELL_LIMIT = 60
#: Вердикт строки, до которой прогон не дошёл (модель или ключ недоступны).
PROVIDER_FAILED = "❌ провайдер недоступен"


def build_parser() -> argparse.ArgumentParser:
    """Аргументы прогона: провайдер, режим ``dry_run``, путь отчёта и его отключение."""
    parser = argparse.ArgumentParser(
        description="Прогнать три сценария демо через ассистента файлов.",
    )
    parser.add_argument("--provider", choices=llm_provider.PICKER_PROVIDERS,
                        default=llm_provider.PROVIDER_DEEPSEEK,
                        help="провайдер ответа (по умолчанию deepseek)")
    parser.add_argument("--dry-run", action="store_true",
                        help="не менять файлы: показать план и предполагаемый diff")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--no-report", action="store_true",
                        help="не писать отчёт: только печать строк прогона")
    return parser


def context(provider: str, dry_run: bool) -> dict:
    """Контекст запуска для отчёта: режим, провайдер, корень и цель подключения сервера."""
    return {
        "mode": "dry_run (файлы не меняются)" if dry_run else "реальный (файлы меняются)",
        "provider_label": llm_provider.label(provider),
        "stamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "root": str(DAY_ROOT),
        "server": file_assistant.FILE_SERVER_NAME,
        "target": file_assistant.FILE_SERVER_TARGET,
    }


def run_scenarios(service: FileAssistantService, provider: str,
                  dry_run: bool) -> list:
    """Три сценария демо: печать хода прогона и записи для отчёта."""
    total = len(file_assistant.DEMO_SCENARIOS)
    rows = []
    for position, scenario in enumerate(file_assistant.DEMO_SCENARIOS, start=1):
        print(f"[{position}/{total}] {scenario['label']}: {scenario['goal']}")
        record = _run_one(service, scenario, provider, dry_run)
        record.update({"label": scenario["label"], "goal": scenario["goal"]})
        _print_record(record)
        rows.append(record)
    return rows


def _run_one(service: FileAssistantService, scenario: dict, provider: str,
             dry_run: bool) -> dict:
    """Один сценарий: результат прогона либо строка отказа без результата.

    Отказ планирования (нет ключа, недоступна Ollama) не должен ронять весь прогон:
    строк отчёта три, и по каждой видно, дошла ли она до сводки.
    """
    try:
        record = service.execute_goal(scenario["goal"], provider, dry_run=dry_run)
    except (FileAssistantError, ValueError) as exc:
        print(f"  отказ: {exc}")
        return {"status": file_assistant.STATUS_FAILED, "plan": [], "steps_executed": [],
                "files_read": [], "files_modified": [], "files_created": [], "diff": "",
                "summary": "", "duration_ms": 0, "run_id": None, "dry_run": dry_run,
                "provider": provider, "verdict": PROVIDER_FAILED}
    record["verdict"] = verdict(record, scenario)
    return record


def _print_record(record: dict) -> None:
    """Печатает план, шаги, файлы, время и вердикт одного сценария."""
    print("  план:")
    for step in record["plan"]:
        print(f"    {step['step_index']}. {step['tool']} — "
              f"{_flat(step.get('reason'), PLAN_LIMIT)}")
    print("  шаги:")
    for step in record["steps_executed"]:
        print(f"    {step['tool']}: {step['status']}, {step['duration_ms']} мс")
        if step.get("error"):
            print(f"      ошибка: {_flat(step['error'], PRINT_LIMIT)}")
    print(f"  файлы: прочитаны {_files_text(record['files_read'])} / "
          f"изменены {_files_text(record['files_modified'])} / "
          f"созданы {_files_text(record['files_created'])}")
    print(f"  время: {record['duration_ms'] / 1000:.2f} с")
    if record["summary"]:
        print(f"  итог: {_flat(record['summary'], PRINT_LIMIT)}")
    print(f"  вердикт: {record['verdict']}")


def write_report(path: Path, rows: list, meta: dict) -> Path:
    """Пишет markdown-отчёт прогона и возвращает путь к файлу."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Отчёт дня 34: ассистент файлов проекта",
        "",
        f"Прогон: {meta['stamp']}, скрипт `scripts/demo_file_assistant.py`, режим "
        f"{meta['mode']}, провайдер {meta['provider_label']}. Цель пользователя "
        "превращается в план шагов, а шаги выполняет MCP-сервер файлов "
        f"`{meta['server']}`.",
        "",
        "## Контекст запуска",
        "",
        f"* режим прогона: {meta['mode']}",
        f"* провайдер ответа: {meta['provider_label']}",
        f"* корень рабочей области: `{meta['root']}` (пути в плане относительны ему)",
        f"* цель подключения сервера: `{meta['target']}`",
        "",
        "## Сводка прогона",
        "",
        "| # | Сценарий | Цель | План | Выполненные шаги | Файлы прочитаны | "
        "Файлы изменены/созданы | Diff | Вердикт |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for position, row in enumerate(rows, start=1):
        lines.append("| " + " | ".join([
            str(position), _cell(row["label"], CELL_LIMIT), _cell(row["goal"], CELL_LIMIT),
            _cell(_plan_text(row), CELL_LIMIT), _cell(_steps_text(row), CELL_LIMIT),
            _cell(_files_text(row["files_read"]), CELL_LIMIT),
            _cell(_files_text([*row["files_modified"], *row["files_created"]]), CELL_LIMIT),
            _cell(row["diff"] or "нет", DIFF_CELL_LIMIT), _cell(row["verdict"], 40),
        ]) + " |")
    for position, row in enumerate(rows, start=1):
        lines.extend(["", f"## Сценарий {position}: {row['label']}", "",
                      f"**Цель:** {row['goal']}", ""])
        if row["summary"]:
            lines.extend([row["summary"], ""])
        lines.append(f"Время: {row['duration_ms'] / 1000:.2f} с · статус "
                     f"`{row['status']}` · вердикт {row['verdict']}")
        for step in row["steps_executed"]:
            if step.get("error"):
                lines.extend(["", f"* ошибка шага {step['step_index']} "
                                  f"({step['tool']}): {step['error']}"])
        lines.extend(["", "```diff", row["diff"] or "(изменений нет)", "```"])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _plan_text(row: dict) -> str:
    """План строки: «номер. tool — причина» через точку с запятой."""
    return "; ".join(f"{step['step_index']}. {step['tool']} — {step.get('reason') or '—'}"
                     for step in row["plan"]) or "нет"


def _steps_text(row: dict) -> str:
    """Журнал строки: «tool (status)» через точку с запятой."""
    return "; ".join(f"{step['tool']} ({step['status']})"
                     for step in row["steps_executed"]) or "нет"


def _files_text(paths) -> str:
    """Список путей через точку с запятой; пустой — «нет»."""
    items = [str(path) for path in (paths or [])]
    return "; ".join(items) if items else "нет"


def _flat(text: object, limit: int) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def _cell(text: object, limit: int) -> str:
    """Ячейка markdown-таблицы: обрезанный текст без вертикальных черт."""
    return _flat(text, limit).replace("|", "\\|") or "—"


def main(argv=None) -> int:
    """Прогоняет три сценария, печатает строки и пишет отчёт."""
    args = build_parser().parse_args(argv)
    service = FileAssistantService()
    try:
        rows = run_scenarios(service, args.provider, args.dry_run)
    finally:
        service.close()
    meta = context(args.provider, args.dry_run)
    if all(row["verdict"] == PROVIDER_FAILED for row in rows):
        source = ("Ollama на 127.0.0.1:11434" if args.provider == llm_provider.PROVIDER_LOCAL
                  else "DEEPSEEK_API_KEY в day21/.env")
        print(f"Провайдер {meta['provider_label']} недоступен: проверьте {source}.")
        return 2
    if not args.no_report:
        try:
            path = write_report(Path(args.report), rows, meta)
        except OSError as exc:
            print(f"Отчёт не записан: {exc}")
            return 2
        print(f"отчёт: {path}")
    # Сбой дня — это ❌ (шаг упал) или ⚠️ (ожидаемого изменения нет). Вердикт
    # ``dry_run`` означает, что план выполнен и файлы не менялись ПО ЗАМЫСЛУ:
    # репетиция без ошибок не заканчивается кодом 1.
    broken = [row for row in rows if not row["verdict"].startswith(("✅", "🧪"))]
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
