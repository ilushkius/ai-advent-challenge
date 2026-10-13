"""Публикация ревью PR комментарием (день 32): markdown из ``POST /review/pr``.

Скрипт берёт JSON-ответ эндпоинта (из файла или stdin), превращает его в markdown
разметкой домена (``domain/code_review_report.render_markdown`` — тот же вид, что в
отчёте ``docs/reports/code_review_demo.md``) и публикует комментарий через ``gh``.
В действии GitHub (``.github/workflows/ai-review.yml``) это последний шаг: до него
бэкенд получил запрос, а ``curl`` сохранил ответ файлом.

Запуск из папки day21/::

    uv run python scripts/gh_review_comment.py --pr 12 --dry-run --input review.json
    uv run python scripts/gh_review_comment.py --pr 12 --input review.json

Коды возврата: 0 — комментарий опубликован (или напечатан при ``--dry-run``),
1 — ``gh`` не сработал, 2 — вход не JSON-объект.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакет backend — в корне дня: добавляем его в
# sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import code_review_report  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Аргументы: номер PR, репозиторий, источник JSON и режим печати."""
    parser = argparse.ArgumentParser(
        description="Опубликовать ответ POST /review/pr комментарием в PR через gh.",
    )
    parser.add_argument("--pr", type=int, required=True, help="номер PR")
    parser.add_argument("--repo", default="",
                        help="owner/repo (по умолчанию — репозиторий текущего каталога)")
    parser.add_argument("--input", default="-",
                        help="файл с JSON-ответом ревью; «-» — stdin (по умолчанию)")
    parser.add_argument("--dry-run", action="store_true",
                        help="только напечатать markdown, не публиковать")
    return parser


def read_record(path: str) -> object:
    """JSON ответа ревью: из файла или из stdin."""
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def publish(pr: int, repo: str, body: str) -> int:
    """Комментарий в PR через ``gh pr comment``; текст уходит телом файла stdin."""
    command = ["gh", "pr", "comment", str(pr)]
    if repo:
        command += ["--repo", repo]
    command += ["--body-file", "-"]
    try:
        subprocess.run(command, input=body, text=True, encoding="utf-8", check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"gh не сработал: {exc}")
        return 1
    print(f"комментарий опубликован в PR #{pr}")
    return 0


def main(argv=None) -> int:
    """Читает ответ ревью, печатает markdown и публикует его комментарием."""
    args = build_parser().parse_args(argv)
    try:
        record = read_record(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"вход не разобран: {exc}")
        return 2
    if not isinstance(record, dict):
        print("вход должен быть JSON-объектом ответа POST /review/pr")
        return 2
    body = code_review_report.render_markdown(record, label=f"PR #{args.pr}")
    if args.dry_run:
        print(body)
        return 0
    return publish(args.pr, args.repo, body)


if __name__ == "__main__":
    sys.exit(main())
