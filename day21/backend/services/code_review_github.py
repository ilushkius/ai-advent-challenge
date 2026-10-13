"""Ревью PR из GitHub (день 32): URL и номер → diff, файлы, RAG-контекст и комментарий.

Вынесено из службы (расширение дня 32): поток GitHub — это второй источник diff-а
рядом с локальным (payload или MCP), и держать оба сценария в одном методе значило бы
смешать две разные последовательности шагов. Здесь только то, чем они различаются:
откуда берётся diff и куда уходит готовое ревью. Дальше путь общий —``review_pr``
службы: два поиска по корпусу, модель по JSON-контракту, разбор находок.

Публикация комментария включается флагом: отказ публикации НЕ отменяет ревью — он
попадает в ``warnings``, а ``posted`` остаётся ``False``. Иначе токена без права на
запись было бы достаточно, чтобы потерять уже полученное ревью.
"""
from __future__ import annotations

from typing import Sequence

from shared.logging_utils import get_logger

from ..domain import code_review, code_review_report
from . import github_client

logger = get_logger(__name__)

__all__ = ["review_github_pr"]


def review_github_pr(service, repo_url: str, pr_number: int, provider: str = "deepseek",
                     post_comment: bool = False) -> dict:
    """Ревью PR из GitHub: REST API вместо MCP, ответ и публикация — как у ``review_pr``.

    Diff и список файлов берутся из GitHub REST API (``GitHubClient``), дальше идёт тот
    же путь, что у ``POST /review/pr``: два поиска по корпусу, модель, разбор находок.
    Публикация комментария включается флагом ``post_comment``: отказ публикации не
    отменяет ревью — он попадает в ``warnings``, а ``posted`` остаётся ``False``.
    """
    client = service.github
    owner, repo = client.parse_repo_url(repo_url)
    repository = client.get_repo(owner, repo)
    pull = client.get_pr(owner, repo, pr_number)
    diff = client.get_pr_diff(owner, repo, pr_number)
    files = client.get_changed_files(owner, repo, pr_number)
    changed = _changed_files(files)
    full_name = str(repository.get("full_name") or f"{owner}/{repo}")
    label = f"{full_name}#{int(pr_number)}"
    pr_url = str(pull.get("html_url") or f"https://github.com/{full_name}/pull/{int(pr_number)}")
    record = service.review_pr({"diff": diff, "changed_files": changed, "owner": owner,
                                "repo": repo, "pr_number": int(pr_number),
                                "pr_label": label}, provider)
    record["github_meta"] = {"owner": owner, "repo": repo, "pr_number": int(pr_number),
                             "pr_url": pr_url, "changed_files_count": len(changed),
                             "diff_lines": len(diff.splitlines())}
    posted, comment_url = False, ""
    if post_comment:
        body = code_review_report.render_markdown(record, label=label)
        try:
            comment = client.post_review_comment(owner, repo, pr_number, body)
            posted = True
            comment_url = str(comment.get("html_url") or "")
        except github_client.GitHubError as exc:
            logger.warning("GitHub: комментарий не опубликован: %s", exc)
            record.setdefault("warnings", []).append(
                code_review.WARN_GITHUB_COMMENT_FAILED.format(error=exc))
    record.update({"posted": posted, "comment_url": comment_url, "pr_url": pr_url})
    return record


def _changed_files(files: Sequence[dict]) -> list[str]:
    """Пути изменённых файлов из ответа GitHub: пустые и дубликаты выбрасываются."""
    paths: list[str] = []
    for item in files or []:
        path = str((item or {}).get("filename") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return paths
