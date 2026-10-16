"""Тесты эндпоинтов подготовки релиза (день 35) — контракт ``/release/*``.

Проверяется то, что видит раздел интерфейса и внешний клиент: коды ответов (400 на
негодный запрос, 404 на неизвестный запуск, 500 на недоступный MCP), форма ответа
прогона, история релизов и выгрузка файлов. Служба подменяется одной точкой
(``main.get_release_service``) — так же, как её подменяют в тестах остальных дней;
внутри стоит та же служба дня 35 на фейках MCP, модели и временной БД, поэтому
проверяется и связка «роутер → служба → история», а не только роутер.
"""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.domain import release
from backend.services.mcp_errors import MCPConnectionError

from release_fakes import FakeMCP, make_checks, make_service


@pytest.fixture
def client(session_factory, monkeypatch):
    """TestClient с подменённой службой релиза на фейках и временной БД."""
    import backend.api.main as main

    service = make_service(mcp=FakeMCP(), session_factory=session_factory)
    monkeypatch.setattr(main, "get_release_service", lambda: service)
    instance = TestClient(main.app)
    instance.service = service
    return instance


@pytest.fixture
def prepared(client):
    """Готовый прогон (``dry_run``) в истории: его номер нужен выгрузке."""
    response = client.post("/release/prepare", json={"from_tag": "day22", "to_tag": "HEAD",
                                                     "dry_run": True})
    assert response.status_code == 200
    return response.json()


def test_prepare_returns_full_plan_without_writing(client):
    """``POST /release/prepare`` в ``dry_run`` отдаёт план, раздел и проверки, но не пишет."""
    response = client.post("/release/prepare", json={"from_tag": "day22", "to_tag": "HEAD",
                                                     "dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "1.0.1" and body["version_bump"] == "patch"
    assert body["status"] == release.STATUS_DRY_RUN and body["dry_run"] is True
    assert body["changelog"]["section"].startswith("## [1.0.1] - ")
    assert sorted(body["diff_preview"]) == [release.CHANGELOG_PATH, release.README_PATH,
                                           release.RELEASE_NOTES_PATH]
    assert [entry["path"] for entry in body["files_to_modify"]] == [
        release.CHANGELOG_PATH, release.RELEASE_NOTES_PATH, release.README_PATH]
    assert body["checks"]["commands"] and body["checks_passed"] is True
    assert body["from_label"] == "day22" and body["to_label"] == "HEAD"
    assert body["commits_count"] == 3 and body["metrics"]["tags"] == 14
    assert client.service.server.writes == []      # MCP-клиент стенда, а не обвязка


def test_prepare_rejects_bad_requests(client):
    """Негодный запрос — 400: версия ниже предложенной, версия не ``X.Y.Z``, пустые теги."""
    below = client.post("/release/prepare", json={"from_tag": "day22", "to_tag": "HEAD",
                                                 "version": "0.0.1"})
    assert below.status_code == 400 and "ниже предложенной" in below.json()["detail"]
    for payload in ({"from_tag": "day22", "to_tag": "HEAD", "version": "latest"},
                    {"from_tag": "", "to_tag": "HEAD"},
                    {"from_tag": "day22", "to_tag": "", "dry_run": True},
                    {"from_tag": "day22", "to_tag": "HEAD", "provider": "openai"}):
        response = client.post("/release/prepare", json=payload)
        assert response.status_code == 400, payload


def test_prepare_reports_mcp_failure_as_500(session_factory, monkeypatch):
    """Недоступный сервер файлов — 500 (без коммитов собирать нечего)."""
    import backend.api.main as main

    service = make_service(mcp=FakeMCP(error=MCPConnectionError("сервер не отвечает")),
                           session_factory=session_factory)
    monkeypatch.setattr(main, "get_release_service", lambda: service)
    response = TestClient(main.app).post("/release/prepare",
                                         json={"from_tag": "day22", "to_tag": "HEAD"})
    assert response.status_code == 500
    assert "MCP-сервер файлов недоступен" in response.json()["detail"]


def test_tags_metrics_and_health_endpoints(client):
    """Читающие эндпоинты: теги, метрики и проверки готовности (без модели)."""
    tags = client.get("/release/tags")
    assert tags.status_code == 200 and tags.json()["count"] == 2
    assert tags.json()["tags"][0]["name"] == "day34"
    metrics = client.get("/release/metrics")
    assert metrics.status_code == 200 and metrics.json()["metrics"]["commits"] == 70
    health = client.get("/release/health")
    assert health.status_code == 200
    assert health.json()["checks_passed"] is True
    assert health.json()["checks"]["coverage_percent"] == 91.5


def test_tags_endpoint_reports_mcp_failure(session_factory, monkeypatch):
    """Теги без сервера файлов — 500 с текстом отказа транспорта."""
    import backend.api.main as main

    service = make_service(mcp=FakeMCP(error=MCPConnectionError("нет процесса")),
                           session_factory=session_factory)
    monkeypatch.setattr(main, "get_release_service", lambda: service)
    response = TestClient(main.app).get("/release/tags")
    assert response.status_code == 500 and "нет процесса" in response.json()["detail"]


def test_history_lists_runs_without_texts(client, prepared):
    """История релизов: запуск виден, тексты разделов в список не входят."""
    history = client.get("/release/history")
    assert history.status_code == 200
    body = history.json()
    assert body["count"] == 1
    run = body["runs"][0]
    assert run["id"] == prepared["run_id"] and run["status"] == release.STATUS_DRY_RUN
    assert run["version"] == prepared["version"] and run["checks_passed"] is True
    assert "changelog" not in run and "release_notes" not in run
    limited = client.get("/release/history", params={"limit": 0}).json()
    assert limited["count"] == 1          # предел не может «не вернуть» строку молча


def test_export_single_files_and_archive(client, prepared):
    """Выгрузка: раздел CHANGELOG текстом, заметки текстом, оба файла — ZIP-архивом."""
    changelog = client.post("/release/export", json={"run_id": prepared["run_id"],
                                                    "file": "changelog"})
    assert changelog.status_code == 200
    assert changelog.headers["content-type"].startswith("text/markdown")
    assert 'filename="CHANGELOG.md"' in changelog.headers["content-disposition"]
    assert changelog.text.startswith("## [1.0.1] - ")

    notes = client.post("/release/export", json={"run_id": prepared["run_id"],
                                                "file": "release_notes"})
    assert 'filename="RELEASE_NOTES.md"' in notes.headers["content-disposition"]
    assert notes.text.startswith("# Релиз 1.0.1 — ")

    archive = client.post("/release/export", json={"run_id": prepared["run_id"]})
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert f'filename="release-{prepared["version"]}.zip"' in \
        archive.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(archive.content)) as opened:
        assert sorted(opened.namelist()) == ["CHANGELOG.md", "RELEASE_NOTES.md"]
        assert opened.read("CHANGELOG.md").decode("utf-8") == prepared["changelog"]["section"]
        assert opened.read("RELEASE_NOTES.md").decode("utf-8") == prepared["release_notes"]


def test_export_rejects_unknown_run_and_file(client):
    """Неизвестный запуск — 404, неизвестное значение ``file`` — 400."""
    missing = client.post("/release/export", json={"run_id": 4, "file": "changelog"})
    assert missing.status_code == 404 and "не найден" in missing.json()["detail"]
    unknown = client.post("/release/export", json={"run_id": 1, "file": "readme"})
    assert unknown.status_code == 400
    assert "Неизвестный файл выгрузки" in unknown.json()["detail"]


def test_health_does_not_touch_mcp(client):
    """Проверки готовности не обращаются к MCP: сервер файлов может быть недоступен."""
    calls_before = list(client.service.server.calls)
    assert client.get("/release/health").status_code == 200
    assert client.service.server.calls == calls_before
    assert make_checks()["passed"] is True
