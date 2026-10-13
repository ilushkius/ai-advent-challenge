"""Локальное AI-ревью PR (день 32): два ref или готовый diff → отчёт в markdown.

Скрипт эмулирует PR без GitHub: берёт diff двух ref-ов (``git diff base..head``) или
файл unified diff-а, отдаёт его службе ревью (``CodeReviewService``) и печатает путь
отчёта. Служба делает то же, что эндпоинт ``POST /review/pr``: подтягивает контекст
корпуса RAG (документация проекта и код изменённых файлов), режет diff до 2000 строк
и зовёт модель по JSON-контракту; найденные баги, архитектурные проблемы,
рекомендации и риски P0–P3 ложатся секцией отчёта.

Секции накапливаются: повторный прогон с тем же ``--section-title`` заменяет свою
секцию, новый заголовок добавляет ещё одну (``upsert_report_section``). Поэтому в
``docs/reports/code_review_demo.md`` лежат два примера — реальный diff дня 30..31 и
синтетический PR.

Запуск из папки day21/::

    uv run python scripts/run_local_pr_review.py --base day30 --head day31
    uv run python scripts/run_local_pr_review.py --diff-file docs/reports/synthetic_pr.diff \\
        --pr-label "synthetic PR" --section-title "Синтетический PR"
    uv run python scripts/run_local_pr_review.py --base day30 --head day31 --no-report --provider local

Коды возврата: 0 — ревью получено, 1 — модель недоступна (текст отказа в отчёте),
2 — негодные аргументы или сбой git.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Корень репозитория нужен git-командам, корень дня — пакету backend.
DAY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import code_review, code_review_report  # noqa: E402
from backend.services.code_review_service import CodeReviewService  # noqa: E402

#: Таймаут одной git-команды: diff большого PR считается секунды, подвисший git —
#: хуже медленного (скрипт запускается руками, и причина должна быть видна).
GIT_TIMEOUT = 60


def build_parser() -> argparse.ArgumentParser:
    """Аргументы: ref-ы или файл diff-а, провайдер, отчёт и его секция."""
    parser = argparse.ArgumentParser(
        description="Локальное AI-ревью diff-а двух ref (или файла diff-а).",
    )
    parser.add_argument("--base", default="", help="базовый ref (напр. day30)")
    parser.add_argument("--head", default="", help="ref изменения (напр. day31)")
    parser.add_argument("--provider", default="deepseek",
                        help="провайдер ответа: deepseek | local (по умолчанию deepseek)")
    parser.add_argument("--diff-file", default="",
                        help="файл unified diff-а вместо пары --base/--head")
    parser.add_argument("--changed-files", default="",
                        help="изменённые файлы через запятую (только с --diff-file)")
    parser.add_argument("--pr-label", default="", help="подпись ревью")
    parser.add_argument("--section-title", default="",
                        help="заголовок секции отчёта (по умолчанию — метка ревью)")
    parser.add_argument("--report", default=code_review.REPORT_PATH,
                        help=f"файл отчёта (по умолчанию {code_review.REPORT_PATH})")
    parser.add_argument("--no-report", action="store_true", help="не писать отчёт")
    parser.add_argument("--top-k", type=int, default=code_review.DEFAULT_TOP_K,
                        help="сколько фрагментов берёт поиск по корпусу")
    return parser


def _git_diff(base: str, head: str, name_only: bool) -> str:
    """Вывод ``git diff`` двух ref-ов; сбой git — ``RuntimeError`` с текстом git."""
    command = ["git", "-C", str(REPO_ROOT), "diff"]
    if name_only:
        command.append("--name-only")
    command.append(f"{base}..{head}")
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", check=True,
                                   timeout=GIT_TIMEOUT)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    return completed.stdout or ""


def collect_diff(args) -> tuple[str, list[str], str]:
    """Diff, изменённые файлы и метка ревью — из файла diff-а или из двух ref-ов."""
    if args.diff_file:
        path = Path(args.diff_file)
        diff = path.read_text(encoding="utf-8")
        changed = [item.strip() for item in args.changed_files.split(",") if item.strip()]
        label = args.pr_label or path.name
    else:
        if not args.base or not args.head:
            raise ValueError("нужны --base и --head (или --diff-file)")
        diff = _git_diff(args.base, args.head, name_only=False)
        changed = [line.strip() for line in
                   _git_diff(args.base, args.head, name_only=True).splitlines()
                   if line.strip()]
        label = args.pr_label or f"{args.base}..{args.head}"
    if not changed:
        changed = code_review.changed_files_from_diff(diff)
    return diff, changed, label


def report_target(args) -> Path:
    """Путь отчёта: относительный считается от корня дня, абсолютный — как задан."""
    path = Path(args.report)
    return path if path.is_absolute() else DAY_ROOT / path


def main(argv=None) -> int:
    """Собирает diff, зовёт службу ревью, печатает итог и пишет секцию отчёта."""
    args = build_parser().parse_args(argv)
    try:
        diff, changed, label = collect_diff(args)
    except ValueError as exc:
        print(str(exc))
        return 2
    except (RuntimeError, OSError) as exc:
        print(f"git не сработал: {exc}")
        return 2
    print(f"1. diff {label}: {len(diff.splitlines())} строк, "
          f"изменённых файлов {len(changed)}")
    print(f"2. поиск контекста в индексе корпуса (top_k={args.top_k}) "
          f"и вызов модели ({args.provider})…")
    service = CodeReviewService(top_k=args.top_k)
    try:
        record = service.review_pr({"base": args.base, "head": args.head, "diff": diff,
                                    "changed_files": changed, "pr_label": label},
                                   args.provider)
    finally:
        service.close()
    print(f"3. ревью готово за {record['duration_ms']} мс: "
          f"багов {len(record['bugs'])}, "
          f"архитектурных проблем {len(record['architecture_issues'])}, "
          f"рекомендаций {len(record['recommendations'])}, "
          f"рисков {len(record['risks'])}")
    for warning in record["warnings"]:
        print(f"предупреждение: {warning}")
    for item in record["sources"]:
        print(f"источник RAG: {item['source']} · {item['section']} · {item['score']}")
    if not args.no_report:
        path = report_target(args)
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        title = args.section_title or args.pr_label or f"Ревью diff {label}"
        text = code_review_report.upsert_report_section(
            current, title, code_review_report.render_markdown(record, label=title))
        path.write_text(text, encoding="utf-8")
        print(f"отчёт: {path}")
    return 1 if record["review_text"].startswith("Ревью недоступно") else 0


if __name__ == "__main__":
    sys.exit(main())
