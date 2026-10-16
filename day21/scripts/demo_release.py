"""Прогон демо подготовки релиза (день 35): один диапазон, полный отчёт.

Скрипт вызывает ту же службу, что и ``POST /release/prepare``, — никакой отдельной
логики релиза здесь нет. Поэтому прогон из консоли и прогон из раздела интерфейса дают
один результат, а флаг ``--no-dry-run`` делает то же, что снятый флажок ``dry_run``:
без него файлы репозитория не меняются.

По умолчанию диапазон — ``day1..HEAD``: тега ``day1`` в репозитории нет (челлендж
начался задолго до первого тега дня 22), и git-инструмент честно берёт начало истории —
поэтому «собрать релиз по всему челленджу» работает до и после создания тега ``day35``.

Проверки готовности (два прогона ``pytest``) идут по умолчанию: отчёт должен показывать
их результат, а не «проверки пропущены». Флаг ``--no-checks`` подменяет их заглушкой —
он нужен для быстрых повторных прогонов, когда проверяется сама сборка раздела.

Отчёт — markdown-файл ``docs/reports/release_demo.md``: контекст запуска, таблица
прогона, метрики проекта, проверки готовности, заметки и первые строки diff-а.
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

from backend.domain import llm_provider, release  # noqa: E402
from backend.services import release_checks  # noqa: E402
from backend.services.release_files import ReleaseError  # noqa: E402
from backend.services.release_service import ReleaseService  # noqa: E402
from backend.storage import database  # noqa: E402

#: Отчёт прогона: тот же файл, на который ссылается README дня.
DEFAULT_REPORT = DAY_ROOT / "docs" / "reports" / "release_demo.md"

#: Пределы текста в таблице отчёта.
CELL_LIMIT = 110
REASON_LIMIT = 60
PREVIEW_LIMIT = 120
DIFF_LINES = 40
#: Что печатать вместо проверок, когда они пропущены флагом ``--no-checks``.
SKIPPED_CHECKS = {"tests_passed": False, "coverage_percent": 0.0, "readme_exists": False,
                  "docs_exists": False, "passed": False, "files": {}, "commands": [],
                  "notes": ["проверки пропущены флагом --no-checks"]}


def build_parser() -> argparse.ArgumentParser:
    """Аргументы прогона: диапазон, версия, провайдер, режим, проверки и отчёт."""
    parser = argparse.ArgumentParser(
        description="Собрать релиз выбранного диапазона тегов и написать отчёт.",
    )
    parser.add_argument("--from-tag", default="day1",
                        help="тег начала диапазона (по умолчанию day1: тега нет — берётся "
                             "начало истории)")
    parser.add_argument("--to-tag", default="HEAD",
                        help="тег конца диапазона (по умолчанию HEAD)")
    parser.add_argument("--version", default="auto",
                        help="версия X.Y.Z или auto (по умолчанию auto)")
    parser.add_argument("--provider", choices=llm_provider.PICKER_PROVIDERS,
                        default=llm_provider.PROVIDER_DEEPSEEK,
                        help="провайдер ответа (по умолчанию deepseek)")
    parser.add_argument("--no-dry-run", action="store_true",
                        help="ЗАПИСАТЬ файлы релиза (по умолчанию — предпросмотр)")
    parser.add_argument("--no-checks", action="store_true",
                        help="не прогонять тесты и покрытие: проверки пропускаются")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--no-report", action="store_true",
                        help="не писать отчёт: только печать сводки")
    return parser


def context(args: argparse.Namespace, record: dict) -> dict:
    """Контекст запуска для отчёта: режим, провайдер, диапазон и цель подключения."""
    return {
        "mode": "реальный прогон (файлы записаны)" if args.no_dry_run
                else "dry_run (файлы не менялись)",
        "provider_label": llm_provider.label(args.provider),
        "stamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "from_tag": args.from_tag,
        "to_tag": args.to_tag,
        "duration": f"{record['duration_ms'] / 1000:.1f} с",
        "server": release.FILE_SERVER_NAME,
        "target": release.FILE_SERVER_TARGET,
        "checks": "пропущены флагом --no-checks" if args.no_checks else "выполнены",
    }


def verdict(record: dict) -> str:
    """Вердикт строки отчёта: готов, не готов или предпросмотр."""
    if record["status"] == release.STATUS_DRY_RUN:
        return release.VERDICT_DRY_RUN
    if not record["checks_passed"]:
        return release.VERDICT_NOT_READY.format(
            version=record["version"],
            failed=", ".join(release_checks.failed_names(record["checks"])) or "проверки")
    return release.VERDICT_READY.format(version=record["version"])


def print_summary(record: dict, args: argparse.Namespace) -> None:
    """Печатает версию, счётчики, проверки, записанные файлы и вердикт."""
    changelog = record["changelog"]
    kept = sum(len(changelog[key]) for key in release.GROUP_ORDER)
    checks = record["checks"]
    print(f"  версия: {record['version']} ({record['version_bump']}) — "
          f"{record['version_reason']}")
    print(f"  коммитов: {record['commits_count']}, ключевых пунктов: {kept}, "
          f"свёрнуто: {changelog['minor_count']}")
    print(f"  проверки: {'пройдены' if record['checks_passed'] else 'не пройдены'}, "
          f"покрытие {checks.get('coverage_percent', 0.0):.1f}%, "
          f"время {record['duration_ms'] / 1000:.1f} с")
    print(f"  файлы: {_files_text(record['files_to_modify'])}")
    print(f"  вердикт: {verdict(record)}")
    for line in record["notes"]:
        print(f"  заметка: {line}")
    if args.no_dry_run:
        print("  файлы записаны — откат: git checkout -- CHANGELOG.md README.md "
              "day21/docs/RELEASE_NOTES.md")


def write_report(path: Path, record: dict, meta: dict) -> Path:
    """Пишет markdown-отчёт прогона и возвращает путь к файлу."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    changelog = record["changelog"]
    lines = [
        "# Отчёт демо подготовки релиза (день 35)",
        "",
        f"Прогон: {meta['stamp']}, скрипт `scripts/demo_release.py`, режим {meta['mode']}, "
        f"провайдер {meta['provider_label']}, диапазон `{meta['from_tag']}..{meta['to_tag']}` "
        f"({record['from_label']} → {record['to_label']}), длительность {meta['duration']}.",
        "Коммиты читает MCP-сервер "
        f"`{meta['server']}` (`{meta['target']}`), версию и раздел CHANGELOG предлагает "
        f"модель, проверки готовности {meta['checks']}.",
        "",
        "## Сводка прогона",
        "",
        "| from_tag | to_tag | suggested_version | reason | breaking_changes_count | "
        "changelog_preview | checks_passed | files_to_modify | вердикт |",
        "|---|---|---|---|---|---|---|---|---|",
        "| " + " | ".join([
            _cell(meta["from_tag"], CELL_LIMIT), _cell(meta["to_tag"], CELL_LIMIT),
            _cell(record["version"], CELL_LIMIT), _cell(record["version_reason"], REASON_LIMIT),
            str(len(record["breaking_changes"])), _cell(_preview(changelog), PREVIEW_LIMIT),
            "да" if record["checks_passed"] else "нет",
            _cell(_files_text(record["files_to_modify"]), CELL_LIMIT),
            _cell(verdict(record), 60),
        ]) + " |",
        "",
        "## Метрики проекта",
        "",
        "| метрика | значение |",
        "|---|---|",
    ]
    for key in release.METRIC_KEYS:
        if key in record["metrics"]:
            lines.append(f"| {key} | {record['metrics'][key]} |")
    lines.extend(["", f"Строкой: {release.metrics_line(record['metrics']) or 'нет данных'}", "",
                  "## Проверки готовности", "",
                  "| проверка | значение | итог | команда |", "|---|---|---|---|"])
    checks = record["checks"]
    lines.append("| тесты | — | " + ("✅" if checks.get("tests_passed") else "❌") + " | "
                 + _cell(_command(checks, "tests"), CELL_LIMIT) + " |")
    lines.append(f"| покрытие | {float(checks.get('coverage_percent') or 0.0):.1f}% | "
                 + ("✅" if checks.get("coverage_percent") else "❌") + " | "
                 + _cell(_command(checks, "coverage"), CELL_LIMIT) + " |")
    for key, title in (("readme", release.README_PATH), ("docs", "day21/docs/architecture.md")):
        exists = bool((checks.get("files") or {}).get(key, {}).get("exists"))
        lines.append(f"| {title} | на месте | " + ("✅" if exists else "❌") + " | — |")
    lines.extend(["", "## Notes", ""])
    lines.extend([f"* {note}" for note in record["notes"]] or ["* заметок нет"])
    lines.extend(["", "## Diff (первые строки)", "",
                  f"Файлы плана: {_files_text(record['files_to_modify'])}",
                  "", "```diff"])
    diff = str((record.get("diff_preview") or {}).get(release.CHANGELOG_PATH) or "")
    lines.extend(diff.splitlines()[:DIFF_LINES] or ["(diff пуст)"])
    lines.extend(["```", ""])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _preview(changelog: dict) -> str:
    """Первые три ключевых пункта раздела одной строкой (для таблицы отчёта)."""
    items = [item for key in release.GROUP_ORDER for item in changelog[key]][:3]
    return "; ".join(items) if items else "ключевых пунктов нет"


def _files_text(changes: list) -> str:
    """План правки одной строкой: «путь (инструмент)», пропущенные помечены."""
    if not changes:
        return "нет"
    return "; ".join(
        f"{entry['path']} ({entry['tool']}{', пропущено' if entry.get('skipped') else ''})"
        for entry in changes)


def _command(checks: dict, name: str) -> str:
    """Команда проверки по имени или «—», если она не выполнялась."""
    for command in checks.get("commands") or []:
        if command.get("name") == name:
            return f"{command.get('command')} (код {command.get('returncode')})"
    return "—"


def _flat(text: object, limit: int) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def _cell(text: object, limit: int) -> str:
    """Ячейка markdown-таблицы: обрезанный текст без вертикальных черт."""
    return _flat(text, limit).replace("|", "\\|") or "—"


def main(argv=None) -> int:
    """Собирает релиз заданного диапазона, печатает сводку и пишет отчёт."""
    args = build_parser().parse_args(argv)
    dry_run = not args.no_dry_run
    # Схему создаёт бэкенд на старте (``lifespan``), но скрипт запускается и сам по
    # себе: ``create_all`` идемпотентен, поэтому таблицы дня дописываются в рабочую
    # ``agents.db`` до первого обращения к истории.
    database.init_db()
    print(f"Прогон релиза: {args.from_tag}..{args.to_tag}, версия {args.version}, "
          f"режим {'dry_run' if dry_run else 'РЕАЛЬНЫЙ (файлы будут записаны)'}, "
          f"провайдер {llm_provider.label(args.provider)}")
    if args.no_checks:
        print("Проверки пропущены (--no-checks): тесты и покрытие не прогоняются.")
    service = ReleaseService(checks=(lambda: dict(SKIPPED_CHECKS)) if args.no_checks else None)
    try:
        record = service.prepare_release(args.from_tag, args.to_tag, args.version,
                                        args.provider, dry_run)
    except (ReleaseError, ValueError) as exc:
        print(release.VERDICT_FAILED.format(error=exc))
        return 1
    finally:
        service.close()
    print_summary(record, args)
    if args.no_report:
        return 0
    try:
        path = write_report(Path(args.report), record, context(args, record))
    except OSError as exc:
        print(f"Отчёт не записан: {exc}")
        return 1
    print(f"отчёт: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
