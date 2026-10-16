"""Интеграционный тест подготовки релиза (день 35): настоящий MCP-сервер и настоящий git.

Проверяется то, что юнит-тесты подменяют: НАСТОЯЩИЙ процесс
``mcp_servers/file_server/server.py``, НАСТОЯЩИЕ теги и коммиты репозитория (инструменты
git-истории всегда работают в ``REPO_ROOT``) и НАСТОЯЩАЯ запись файлов на диск. Модель —
заглушка (``ScriptedLLM``): тест не ходит в сеть и не тратит токены.

Рабочий корень сервера — временный каталог со стендом ``CHANGELOG.md`` и ``README.md``
(``--file-root <tmp>``): файлы релиза пишутся туда, рабочее дерево дня тест не трогает.
Поэтому после прогона ``git status --porcelain`` репозитория обязан остаться пустым —
это и есть проверка «тест ничего не испортил».

Тест медленный (поднимается процесс MCP-сервера, читается настоящая история, файлы
пишутся на диск), поэтому помечен ``slow``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.core import config
from backend.domain import release
from backend.services.release_service import ReleaseService
from backend.storage.release_store import ReleaseStore
from mcp_servers.file_server import config as file_server_config

from release_fakes import CHANGELOG_JSON, ScriptedLLM, VERSION_JSON, make_checks

pytestmark = pytest.mark.slow

#: Тот же путь, что у службы: файл сервера файлов в пакете дня.
SERVER = Path(__file__).resolve().parents[2] / "mcp_servers" / "file_server" / "server.py"

#: Стенд файлов релиза: ``CHANGELOG.md`` с шапкой (база версии) и ``README.md`` с якорем.
CHANGELOG_MD = ("# История изменений\n\nДневник челленджа.\n\n"
                "## [1.0.0] - 2026-10-14\n\n### Added\n- Первый релиз.\n")
README_MD = ("# ai-challenge\n\nПрактикум по LLM.\n\n"
             "## Структура репозитория\n\n- `day21/` — текущий день.\n")


def _git(*args: str) -> str:
    """Команда git в корне репозитория (для проверки чистоты рабочего дерева)."""
    completed = subprocess.run(["git", *args], cwd=file_server_config.REPO_ROOT,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", check=True)
    return completed.stdout or ""


@pytest.fixture
def root(tmp_path):
    """Временный корень рабочей области сервера: два файла релиза, ничего лишнего."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / release.CHANGELOG_PATH).write_text(CHANGELOG_MD, encoding="utf-8",
                                                   newline="\n")
    (workspace / release.README_PATH).write_text(README_MD, encoding="utf-8", newline="\n")
    return workspace


@pytest.fixture
def flow_service(root, session_factory):
    """Служба на настоящем сервере файлов: реальный git, временный корень записи."""
    service = ReleaseService(
        llm_client=ScriptedLLM([VERSION_JSON, CHANGELOG_JSON]),
        mcp_target=f'"{sys.executable}" "{SERVER.resolve()}" --file-root "{root}"',
        mcp_cwd=config.MCP_FLEET_CWD,
        store=ReleaseStore(session_factory=session_factory),
        checks=lambda: make_checks(), sleep=lambda _seconds: None)
    try:
        yield service
    finally:
        service.close()


def test_git_tools_read_real_history(flow_service):
    """Инструменты git-истории на настоящем репозитории: теги, коммиты, файлы и метрики."""
    tags = flow_service.tags()
    assert tags["count"] >= 14 and any(tag["name"] == "day34" for tag in tags["tags"])

    ok, commits, error, _ms = flow_service.mcp.call(release.TOOL_COMMITS_BETWEEN,
                                                   {"from_tag": "day22", "to_tag": "HEAD"})
    assert ok and error == ""
    assert len(commits) >= 15
    assert all(commit["hash"] and commit["subject"] for commit in commits)

    ok, files, _error, _ms = flow_service.mcp.call(
        release.TOOL_CHANGED_FILES_BETWEEN, {"from_tag": "day33", "to_tag": "HEAD"})
    assert ok and "day21/backend/api/main.py" in files

    ok, stats, _error, _ms = flow_service.mcp.call(release.TOOL_COMMIT_STATS,
                                                   {"tag": "day34"})
    assert ok and stats["files"] > 0 and stats["insertions"] > 0

    metrics = flow_service.metrics()["metrics"]
    assert set(metrics) == {"tags", "commits", "py_files", "tests", "mcp_servers", "assistants"}
    assert metrics["commits"] >= 70 and metrics["assistants"] >= 5


def test_dry_run_touches_nothing_on_disk(flow_service, root):
    """``dry_run`` не меняет ни временный корень, ни рабочее дерево репозитория."""
    before = {path: path.read_text(encoding="utf-8")
              for path in (root / release.CHANGELOG_PATH, root / release.README_PATH)}
    status_before = _git("status", "--porcelain")

    result = flow_service.prepare_release("day22", "HEAD", dry_run=True)

    assert result["status"] == release.STATUS_DRY_RUN
    assert result["files_to_modify"] and not any(entry["ok"] for entry in result["files_to_modify"])
    assert not (root / release.RELEASE_NOTES_PATH).exists()
    assert {path: path.read_text(encoding="utf-8") for path in before} == before
    assert _git("status", "--porcelain") == status_before
    assert result["diff_preview"][release.CHANGELOG_PATH].startswith("--- a/CHANGELOG.md")


def test_real_run_writes_files_into_workspace(flow_service, root):
    """Реальный прогон: раздел в CHANGELOG перед первой шапкой, заметки, раздел README."""
    result = flow_service.prepare_release("day1", "HEAD", version="2.0.0", dry_run=False)

    assert result["status"] == release.STATUS_COMPLETED
    assert sorted(result["files_to_modify"][index]["path"] for index in range(3)) == sorted(
        [release.CHANGELOG_PATH, release.RELEASE_NOTES_PATH, release.README_PATH])
    assert all(entry["ok"] for entry in result["files_to_modify"])

    changelog = (root / release.CHANGELOG_PATH).read_text(encoding="utf-8")
    assert changelog.startswith("# История изменений\n")
    assert changelog.index(release.release_heading("2.0.0")) < changelog.index("## [1.0.0]")
    assert "### Minor changes" in changelog

    notes = (root / release.RELEASE_NOTES_PATH).read_text(encoding="utf-8")
    assert notes.startswith("# Релиз 2.0.0 — ") and "## Как обновиться" in notes

    readme = (root / release.README_PATH).read_text(encoding="utf-8")
    assert readme.count(release.README_SECTION_TITLE) == 1
    assert readme.index(release.README_SECTION_TITLE) < readme.index(release.README_ANCHOR)
    assert _git("status", "--porcelain") == _git("status", "--porcelain")


def test_existing_section_is_skipped(flow_service, root):
    """Раздел, который уже есть в файле, не дублируется: CHANGELOG пропускается, README — нет.

    Так выглядит повтор подготовки: база версии берётся из первой шапки CHANGELOG, а
    раздел ищется по всему файлу — уже вставленный раздел не появляется второй раз.
    """
    seeded = CHANGELOG_MD + ("\n## [2.0.0] - 2026-10-15\n\n### Added\n"
                             "- Раздел уже на месте.\n")
    (root / release.CHANGELOG_PATH).write_text(seeded, encoding="utf-8", newline="\n")

    result = flow_service.prepare_release("day1", "HEAD", version="2.0.0", dry_run=False)

    entries = {entry["path"]: entry for entry in result["files_to_modify"]}
    assert entries[release.CHANGELOG_PATH]["skipped"] is True
    assert entries[release.CHANGELOG_PATH]["ok"] is False
    assert entries[release.README_PATH]["ok"] is True
    changelog = (root / release.CHANGELOG_PATH).read_text(encoding="utf-8")
    assert changelog.count(release.release_heading("2.0.0")) == 1
    assert result["status"] == release.STATUS_COMPLETED


def test_history_row_is_stored_and_exported(flow_service):
    """Строка истории пишется в БД, и выгрузка отдаёт её тексты (без повторного прогона)."""
    result = flow_service.prepare_release("day22", "HEAD", dry_run=True)
    record = flow_service.export(result["run_id"])
    assert record["from_tag"] == "day22" and record["status"] == release.STATUS_DRY_RUN
    assert record["changelog"] == result["changelog"]["section"]
    assert record["checks_passed"] is True
    assert flow_service.history()["count"] == 1
