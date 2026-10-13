"""Интеграционный тест GitHub-режима (день 32): живой GitHub REST API по токену.

Проверяется то, что юниты проверить не могут: клиент действительно ходит в GitHub и
получает оттуда метаданные PR, diff в формате unified и список изменённых файлов.
Тест помечен ``slow`` (сеть — это секунды) и ``github`` (маркер снимает autouse-запрет
сети), а без ``GITHUB_TOKEN`` пропускается: анонимный лимит 60 запросов в час — общий на
IP, и тратить его на прогон набора нельзя.

Цель задаётся переменными окружения ``GITHUB_TEST_REPO`` (по умолчанию
``fastapi/fastapi``) и ``GITHUB_TEST_PR`` (по умолчанию 16481) — так тест переводится на
свой репозиторий без правки кода.
"""
from __future__ import annotations

import os

import pytest

from backend.services.github_client import GitHubClient, github_token

#: Репозиторий и PR демо: открытый публичный PR с небольшим diff-ом.
DEFAULT_REPO = "fastapi/fastapi"
DEFAULT_PR = 16481

pytestmark = [pytest.mark.slow, pytest.mark.github,
              pytest.mark.skipif(not github_token(),
                                 reason="GITHUB_TOKEN не задан: живой GitHub API "
                                        "проверяется только с токеном")]


def test_live_pr_fetch():
    """Живой GitHub: метаданные PR, unified diff и список файлов с непустыми именами."""
    repo = os.environ.get("GITHUB_TEST_REPO", DEFAULT_REPO)
    number = int(os.environ.get("GITHUB_TEST_PR", DEFAULT_PR))
    owner, name = repo.split("/", 1)
    client = GitHubClient()
    try:
        pull = client.get_pr(owner, name, number)
        diff = client.get_pr_diff(owner, name, number)
        files = client.get_changed_files(owner, name, number)
    finally:
        client.close()
    assert int(pull["number"]) == number
    assert diff.startswith("diff --git ")
    assert files and all(str(item.get("filename") or "") for item in files)
