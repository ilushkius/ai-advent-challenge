"""Юнит-тесты git-инструментов релиза (день 35) на временном репозитории.

Инструменты читают историю через ``git``, поэтому проверяются на НАСТОЯЩЕМ маленьком
репозитории в ``tmp_path``: тег, три коммита, изменённые файлы и бинарный файл.
Корни (``REPO_ROOT``/``DAY_ROOT``) подменяются в ``config`` сервера файлов — на них
смотрят и ``git_history``, и ``diffing.run_git``, поэтому подмена одна на оба модуля.

Проверяется то, ради чего инструменты и делались: форма ответа (словари с хешем,
автором, датой и сообщением), порядок коммитов, прощение незнакомого ref (диапазон
читается от начала истории) и правила подсчёта метрик проекта — они должны быть
проверяемыми, а не «примерно такими».
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.file_server import config as file_server_config
from mcp_servers.file_server import git_history


def _git(root: Path, *args: str, env: dict | None = None) -> str:
    """Команда git в тестовом репозитории (без глобального конфига пользователя)."""
    environment = {**os.environ, **(env or {})}
    completed = subprocess.run(
        ["git", "-c", "user.name=Тест", "-c", "user.email=test@example.com", *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=True,
        env=environment)
    return completed.stdout or ""


def _commit(root: Path, message: str, date: str | None = None) -> None:
    """Коммит всего, что лежит в рабочем дереве.

    Дата задаётся явно: у тегов в ``creatordate`` стоит дата коммита, и в репозитории,
    созданном за одну секунду, порядок тегов был бы неразличим (сортировка по дате
    сравнивала бы одинаковые значения — тест стал бы случайным).
    """
    environment = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message, env=environment)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Временный репозиторий: два тега, три коммита и метрики проекта под ним.

    ``DAY_ROOT`` тоже подменяется: метрики считают файлы папки дня, и проверять их на
    настоящем репозитории дня значило бы закрепить в тесте текущие числа проекта.
    """
    root = tmp_path / "repo"
    (root / "day21").mkdir(parents=True)
    (root / "mcp_server").mkdir()
    (root / "mcp_servers" / "alpha").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "frontend").mkdir()
    _git(root, "init")

    (root / "day21" / "first.py").write_text("a = 1\n", encoding="utf-8", newline="\n")
    (root / "mcp_server" / "server.py").write_text("# сервер\n", encoding="utf-8",
                                                  newline="\n")
    (root / "mcp_servers" / "alpha" / "server.py").write_text("# альфа\n", encoding="utf-8",
                                                              newline="\n")
    (root / "tests" / "test_sample.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n", encoding="utf-8",
        newline="\n")
    (root / "frontend" / "main_sections.py").write_text(
        'SECTIONS = ("🧑\u200d💻 Ассистент (Day 31)", "🚀 Релиз (Day 35)")\n',
        encoding="utf-8", newline="\n")
    _commit(root, "feat: первый коммит", "2026-01-01T10:00:00+00:00")
    _git(root, "tag", "day1")

    (root / "day21" / "second.py").write_text("b = 2\nc = 3\n", encoding="utf-8",
                                              newline="\n")
    _commit(root, "day2: второй коммит", "2026-01-02T10:00:00+00:00")
    _git(root, "tag", "day2")

    (root / "day21" / "first.py").write_text("a = 2\n", encoding="utf-8", newline="\n")
    (root / "docs.bin").write_bytes(b"\x00\x01\x02\x03")
    _commit(root, "fix: третий коммит\n\nТело с подробностями.", "2026-01-03T10:00:00+00:00")
    monkeypatch.setattr(file_server_config, "REPO_ROOT", root)
    monkeypatch.setattr(file_server_config, "DAY_ROOT", root)
    return root


def test_get_tags_returns_dates_and_commits(repo):
    """Теги идут от свежих к старым, у каждого есть дата и короткий хеш."""
    tags = git_history.get_tags()
    assert [tag["name"] for tag in tags] == ["day2", "day1"]
    assert tags[0]["date"] > tags[1]["date"]
    assert all(tag["date"] and len(tag["commit"]) >= 7 for tag in tags)


def test_get_commits_between_reads_range_newest_first(repo):
    """Диапазон от тега до HEAD: коммиты новые сверху, с заголовком и телом сообщения."""
    commits = git_history.get_commits_between("day1", "HEAD")
    assert [commit["subject"] for commit in commits] == ["fix: третий коммит",
                                                        "day2: второй коммит"]
    first = commits[-1]
    assert first["hash"] and first["author"] == "Тест" and first["date"]
    assert first["message"] == "day2: второй коммит"
    assert "Тело с подробностями." in commits[0]["message"]


def test_get_commits_between_forgives_unknown_ref(repo):
    """Незнакомый тег не ошибка: диапазон читается как вся история — с корневым коммитом."""
    commits = git_history.get_commits_between("нет-такого-тега", "HEAD")
    assert len(commits) == 3
    assert commits[-1]["subject"] == "feat: первый коммит"
    assert git_history.get_commits_between("HEAD", "HEAD") == []


def test_get_changed_files_between_returns_unique_paths(repo):
    """Изменённые пути — отсортированный список без повторов; без начала — вся история."""
    files = git_history.get_changed_files_between("day1", "HEAD")
    assert files == ["day21/first.py", "day21/second.py", "docs.bin"]
    whole = git_history.get_changed_files_between("нет-такого-тега", "HEAD")
    assert whole[:3] == files                    # файлы коммитов после day1 на месте
    assert "tests/test_sample.py" in whole       # и файлы КОРНЕВОГО коммита тоже
    assert len(whole) == len(set(whole))


def test_get_commit_stats_counts_files_and_lines(repo):
    """Счётчики коммита: файлы, вставки и удаления; бинарный файл даёт нули строк."""
    stats = git_history.get_commit_stats("day2")
    assert stats["ref"] == "day2" and stats["files"] == 1
    assert stats["insertions"] == 2 and stats["deletions"] == 0
    last = git_history.get_commit_stats("HEAD")
    assert last["files"] == 2 and last["deletions"] == 1
    with pytest.raises(ToolError):
        git_history.get_commit_stats("нет-такого-тега")


def test_ref_longer_than_limit_is_tool_error(repo):
    """Длинный ref — ошибка инструмента (граница аргумента объявлена в ``config``)."""
    with pytest.raises(ToolError):
        git_history.get_commit_stats("x" * (file_server_config.REF_MAX + 1))


def test_project_metrics_counts_documented_rule(repo):
    """Метрики считаются по записанным правилам: теги, коммиты, .py, тесты, серверы, ассистенты."""
    metrics = git_history.get_project_metrics()
    assert sorted(metrics) == ["assistants", "commits", "mcp_servers", "py_files",
                               "tags", "tests"]
    assert metrics["tags"] == 2
    assert metrics["commits"] == 3
    assert metrics["py_files"] == 2          # отслеживаемые .py под day21/
    assert metrics["tests"] == 2             # строки def test_ в tests/
    assert metrics["mcp_servers"] == 2       # mcp_server/server.py и mcp_servers/*/server.py
    assert metrics["assistants"] == 2        # две подписи (Day NN) в main_sections.py


def test_project_metrics_survive_missing_files(tmp_path, monkeypatch):
    """Пустой корень дня не роняет метрики: нули вместо исключений."""
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init")
    (empty / "readme.md").write_text("x\n", encoding="utf-8", newline="\n")
    _commit(empty, "chore: пусто")
    monkeypatch.setattr(file_server_config, "REPO_ROOT", empty)
    monkeypatch.setattr(file_server_config, "DAY_ROOT", empty)
    metrics = git_history.get_project_metrics()
    assert metrics["commits"] == 1 and metrics["tags"] == 0
    assert metrics["tests"] == 0 and metrics["assistants"] == 0
