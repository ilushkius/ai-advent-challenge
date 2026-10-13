"""AI-ревью реального GitHub PR (день 32): URL репозитория и номер PR → отчёт.

Скрипт ходит в GitHub сам: diff и список изменённых файлов берутся из GitHub REST API
(``GitHubClient``), дальше идёт тот же путь, что у ``POST /review/pr``, — служба
подтягивает контекст корпуса RAG (документация проекта и код изменённых файлов) и зовёт
модель по JSON-контракту. Найденные баги, архитектурные проблемы, рекомендации и риски
P0–P3 ложатся секцией отчёта вместе с блоком «GitHub PR» (ссылка на PR, число файлов и
строк diff-а).

Флаг ``--post-comment`` публикует готовое ревью комментарием в PR: нужен
``GITHUB_TOKEN`` с правом ``pull requests: write``. Отказ публикации не отменяет ревью —
он печатается предупреждением, а код возврата остаётся нулевым.

Запуск из папки day21/::

    uv run python scripts/run_github_pr_review.py \\
        --repo-url https://github.com/fastapi/fastapi --pr-number 16481
    uv run python scripts/run_github_pr_review.py --repo-url git@github.com:owner/repo.git \\
        --pr-number 7 --post-comment --section-title "Ревью PR owner/repo#7"

Коды возврата: 0 — ревью получено, 1 — модель недоступна (текст отказа в отчёте),
2 — негодные аргументы, отказ GitHub (нет репозитория, PR, токена, rate limit) или сбой
записи отчёта.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Корень дня нужен пакету backend, папка скриптов — общим помощникам соседних скриптов.
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import code_review, code_review_report  # noqa: E402
from backend.services.code_review_service import CodeReviewService  # noqa: E402
from backend.services.github_client import GitHubClient, GitHubError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Аргументы: репозиторий и номер PR, провайдер, публикация, отчёт и его секция."""
    parser = argparse.ArgumentParser(
        description="AI-ревью PR из GitHub: diff и файлы берутся из GitHub REST API.",
    )
    parser.add_argument("--repo-url", required=True,
                        help="URL репозитория: https://github.com/owner/repo, "
                             "https://github.com/owner/repo.git или "
                             "git@github.com:owner/repo.git")
    parser.add_argument("--pr-number", type=int, required=True, help="номер PR")
    parser.add_argument("--provider", default="deepseek",
                        help="провайдер ответа: deepseek | local (по умолчанию deepseek)")
    parser.add_argument("--post-comment", action="store_true",
                        help="опубликовать ревью комментарием в PR (нужен GITHUB_TOKEN)")
    parser.add_argument("--report", default=code_review.GITHUB_REPORT_PATH,
                        help=f"файл отчёта (по умолчанию {code_review.GITHUB_REPORT_PATH})")
    parser.add_argument("--no-report", action="store_true", help="не писать отчёт")
    parser.add_argument("--section-title", default="",
                        help="заголовок секции отчёта (по умолчанию «Ревью PR owner/repo#N»)")
    parser.add_argument("--top-k", type=int, default=code_review.DEFAULT_TOP_K,
                        help="сколько фрагментов берёт поиск по корпусу")
    return parser


def report_target(args) -> Path:
    """Путь отчёта: относительный считается от корня дня, абсолютный — как задан."""
    path = Path(args.report)
    return path if path.is_absolute() else DAY_ROOT / path


def _print_review(record: dict, args) -> None:
    """Предупреждения шагов, источники RAG и строка о комментарии — после сводки."""
    for warning in record["warnings"]:
        print(f"предупреждение: {warning}")
    for item in record["sources"]:
        print(f"источник RAG: {item['source']} · {item['section']} · {item['score']}")
    print(f"PR: {record['pr_url']}")
    print(f"комментарий: {record['comment_url'] or 'не публиковался'}")


def _write_report(record: dict, args, owner: str, repo: str) -> Path:
    """Дописывает секцию отчёта: разметка ревью плюс блок «GitHub PR»."""
    path = report_target(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    title = args.section_title or f"Ревью PR {owner}/{repo}#{args.pr_number}"
    body = (code_review_report.render_markdown(record, label=title) + "\n"
            + code_review_report.render_github_meta(record))
    text = code_review_report.upsert_report_section(
        current, title, body, header=code_review_report.github_report_header())
    path.write_text(text, encoding="utf-8")
    return path


def main(argv=None) -> int:
    """Читает PR из GitHub, зовёт службу ревью, печатает итог и пишет секцию отчёта."""
    args = build_parser().parse_args(argv)
    try:
        owner, repo = GitHubClient.parse_repo_url(args.repo_url)
    except GitHubError as exc:
        print(f"GitHub: {exc}")
        return 2
    print(f"1. Получаю diff PR #{args.pr_number} из репозитория {owner}/{repo}…")
    service = CodeReviewService(top_k=args.top_k)
    try:
        record = service.review_github_pr(args.repo_url, args.pr_number, args.provider,
                                          args.post_comment)
    except GitHubError as exc:
        print(f"GitHub: {exc}")
        return 2
    except ValueError as exc:
        print(str(exc))
        return 2
    finally:
        service.close()
    meta = record["github_meta"]
    print(f"2. Найдено {meta['changed_files_count']} изменённых файлов, diff "
          f"{meta['diff_lines']} строк — поиск контекста в индексе корпуса "
          f"(top_k={args.top_k}) и вызов модели ({args.provider})…")
    print(f"3. ревью готово за {record['duration_ms']} мс: "
          f"багов {len(record['bugs'])}, "
          f"архитектурных проблем {len(record['architecture_issues'])}, "
          f"рекомендаций {len(record['recommendations'])}, "
          f"рисков {len(record['risks'])}")
    _print_review(record, args)
    if not args.no_report:
        try:
            path = _write_report(record, args, owner, repo)
        except OSError as exc:
            print(f"отчёт не записан: {exc}")
            return 2
        print(f"отчёт: {path}")
    return 1 if record["review_text"].startswith("Ревью недоступно") else 0


if __name__ == "__main__":
    sys.exit(main())
