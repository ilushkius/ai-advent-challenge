"""Юнит-тесты службы подготовки релиза (день 35) на фейках MCP, модели и проверок.

Проверяются РЕШЕНИЯ службы, а не git и не диск: что попадает в раздел CHANGELOG, какая
версия выбирается (и что написано в причине), что происходит при отказе модели, что
записано в историю и — отдельно — что в ``dry_run`` инструменты записи не вызываются ни
разу. Настоящий процесс сервера файлов и настоящий git проверяет slow-интеграция
(``tests/integration/test_release_flow.py``).
"""
import pytest

from backend.domain import llm_provider, release
from backend.services.mcp_errors import MCPConnectionError
from backend.services.release_files import ReleaseError
from backend.storage.release_store import ReleaseRunNotFoundError

from release_fakes import (CHANGELOG_JSON, CHANGELOG_TEXT, DEFAULT_COMMITS, FakeMCP,
                           FailingLLM, ScriptedLLM, VERSION_JSON, make_checks, make_service)

#: Хранилище в тестах — временная БД фикстуры ``session_factory``.


def _written(result: dict) -> list[str]:
    """Пути, записанные прогоном: по плану правки, а не по отдельному полю ответа."""
    return [entry["path"] for entry in result["files_to_modify"] if entry["ok"]]


@pytest.fixture
def mcp():
    """MCP-клиент стенда: файлы в словаре, git-данные заготовлены."""
    return FakeMCP()


@pytest.fixture
def service(mcp, session_factory):
    """Служба на фейках: заглушка модели, стенд файлов и временная БД."""
    return make_service(mcp=mcp, session_factory=session_factory)


# ---------- сухой прогон ----------
def test_dry_run_never_writes_files(service, mcp):
    """В ``dry_run`` служба не вызывает инструменты записи НИ РАЗУ, а план показывает."""
    before = dict(mcp.files)
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert mcp.writes == []
    assert mcp.files == before
    assert result["status"] == release.STATUS_DRY_RUN and result["dry_run"] is True
    assert [entry["path"] for entry in result["files_to_modify"]] == [
        release.CHANGELOG_PATH, release.RELEASE_NOTES_PATH, release.README_PATH]
    assert all(entry["ok"] is False for entry in result["files_to_modify"])
    for path in (release.CHANGELOG_PATH, release.README_PATH):
        assert result["diff_preview"][path].startswith(f"--- a/{path}")
    assert release.CHANGELOG_PATH in result["diff_preview"]


def test_dry_run_records_history_row(service):
    """Строка истории заводится и в ``dry_run``: прогон видно в разделе и в API."""
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    record = service.export(result["run_id"])
    assert record["status"] == release.STATUS_DRY_RUN
    assert record["from_tag"] == "day22" and record["to_tag"] == "HEAD"
    assert record["version"] == result["version"]
    assert record["version_reason"] == result["version_reason"]
    assert record["changelog"] == result["changelog"]["section"]
    assert record["release_notes"] == result["release_notes"]
    assert record["files_modified"] == []
    assert service.history()["count"] == 1


# ---------- версия ----------
def test_version_comes_from_model_when_it_answers(service):
    """Годный ответ модели задаёт тип изменения и причину (версия считается от базы)."""
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert result["version_bump"] == "patch"
    assert result["version"] == "1.0.1"
    assert result["version_reason"] == "служебные правки и документация"
    assert result["breaking_changes"] == [] and result["features"] == ["ассистент файлов"]
    assert result["fixes"] == ["правка README"]


def test_explicit_version_must_not_be_lower(service, session_factory):
    """Явная версия не ниже предложенной; ниже — ``ValueError`` и закрытый запуск."""
    accepted = service.prepare_release("day22", "HEAD", version="2.0.0", dry_run=True)
    assert accepted["version"] == "2.0.0"
    assert "версия задана явно" in accepted["version_reason"]

    with pytest.raises(ValueError) as exc:
        service.prepare_release("day22", "HEAD", version="0.0.1", dry_run=True)
    assert "ниже предложенной" in str(exc.value)
    statuses = [run["status"] for run in service.history()["runs"]]
    assert release.STATUS_FAILED in statuses


def test_bad_version_format_and_empty_tags_are_rejected(service):
    """Версия не ``X.Y.Z`` и пустые теги — ``ValueError`` (роутер отвечает 400)."""
    for version in ("1.0", "latest", "v1.0.0.0"):
        with pytest.raises(ValueError):
            service.prepare_release("day22", "HEAD", version=version, dry_run=True)
    with pytest.raises(ValueError) as exc:
        service.prepare_release("  ", "HEAD", dry_run=True)
    assert str(exc.value) == release.REASON_EMPTY_TAGS
    with pytest.raises(ValueError):
        service.prepare_release("day22", "HEAD", provider="неизвестный", dry_run=True)
    assert service.history()["count"] == 0      # отклонённый запрос строки не создаёт


def test_model_failure_falls_back_to_rule(mcp, session_factory):
    """Отказ модели не роняет прогон: тип изменения определяет правило по меткам."""
    service = make_service(mcp=mcp, session_factory=session_factory, llm=FailingLLM())
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert result["version_bump"] == "patch"
    assert result["version"] == "1.0.1"
    assert release.FALLBACK_REASON.format(rule="меток feat и BREAKING CHANGE нет") == \
        result["version_reason"]
    assert release.FALLBACK_CHANGELOG_NOTE in result["notes"]
    added = result["changelog"]["added"]
    assert added == [commit["subject"] for commit in DEFAULT_COMMITS]


def test_rule_bump_reads_feat_and_breaking(mcp, session_factory):
    """Правило без модели: ``feat`` даёт minor, ``BREAKING CHANGE`` — major."""
    commits = [dict(DEFAULT_COMMITS[0]),
               {"hash": "fff", "author": "a", "date": "d", "subject": "feat: новая команда",
                "message": "feat: новая команда"}]
    service = make_service(mcp=FakeMCP(commits=commits), session_factory=session_factory,
                           llm=FailingLLM())
    assert service.prepare_release("day22", "HEAD", dry_run=True)["version"] == "1.1.0"

    breaking = [{"hash": "ggg", "author": "a", "date": "d", "subject": "fix: правка",
                "message": "fix: правка BREAKING CHANGE в конфиге"}]
    service = make_service(mcp=FakeMCP(commits=breaking), session_factory=session_factory,
                           llm=FailingLLM())
    assert service.prepare_release("day22", "HEAD", dry_run=True)["version"] == "2.0.0"


def test_base_version_reads_current_changelog(mcp, session_factory):
    """База берётся из шапки текущего CHANGELOG: 1.0.0 → 1.1.0 при minor."""
    llm = ScriptedLLM([VERSION_JSON.replace('"patch"', '"minor"'), CHANGELOG_JSON])
    service = make_service(mcp=mcp, session_factory=session_factory, llm=llm)
    assert service.prepare_release("day22", "HEAD", dry_run=True)["version"] == "1.1.0"


def test_missing_changelog_starts_from_fallback_version(mcp, session_factory):
    """Файла CHANGELOG нет — база ``1.0.0``, раздел создаётся с нуля, инструмент — write_file."""
    mcp.files.pop(release.CHANGELOG_PATH)
    service = make_service(mcp=mcp, session_factory=session_factory)
    result = service.prepare_release("day1", "HEAD", dry_run=False)
    assert result["version"] == "1.0.1"
    assert release.WARN_CHANGELOG_MISSING.format(path=release.CHANGELOG_PATH) in result["notes"]
    changelog_change = result["files_to_modify"][0]
    assert changelog_change["tool"] == release.TOOL_WRITE_FILE and changelog_change["ok"] is True
    assert mcp.files[release.CHANGELOG_PATH].startswith(release.release_heading("1.0.1"))


# ---------- теги и метки ----------
def test_missing_tag_is_labelled_but_range_still_works(service):
    """Отсутствие тега видно в подписи диапазона, а не ошибкой."""
    result = service.prepare_release("day1", "HEAD", dry_run=True)
    assert result["from_tag"] == "day1"
    assert result["from_label"] == release.TAG_MISSING_FROM.format(tag="day1")
    assert result["to_label"] == "HEAD"
    known = service.prepare_release("day22", "day34", dry_run=True)
    assert known["from_label"] == "day22" and known["to_label"] == "day34"


def test_no_commits_is_rejected_and_run_closed(mcp, session_factory):
    """Пустой диапазон — ``ValueError``, а строка запуска закрывается ``failed``."""
    service = make_service(mcp=FakeMCP(commits=[]), session_factory=session_factory)
    with pytest.raises(ValueError) as exc:
        service.prepare_release("day22", "HEAD", dry_run=True)
    assert "нет коммитов" in str(exc.value)
    assert [run["status"] for run in service.history()["runs"]] == [release.STATUS_FAILED]


# ---------- отказы и заметки ----------
def test_mcp_failure_is_release_error_and_run_failed(session_factory):
    """Недоступный сервер файлов — ``ReleaseError`` (500) и закрытая строка запуска."""
    mcp = FakeMCP(error=MCPConnectionError("сервер не отвечает"))
    service = make_service(mcp=mcp, session_factory=session_factory)
    with pytest.raises(ReleaseError):
        service.prepare_release("day22", "HEAD", dry_run=True)
    assert [run["status"] for run in service.history()["runs"]] == [release.STATUS_FAILED]


def test_non_fatal_reads_do_not_stop_release(mcp, session_factory):
    """Метрики и теги — необязательные данные: их отказ идёт заметкой, релиз продолжается."""
    def mcp_with_broken_metrics():
        instance = FakeMCP()
        original = instance.call_tool

        def call_tool(name, arguments=None):
            if name in (release.TOOL_PROJECT_METRICS, release.TOOL_GET_TAGS):
                instance.calls.append((name, dict(arguments or {})))
                from backend.domain.mcp_tools import MCPToolResult
                return MCPToolResult(tool=name, arguments=arguments or {}, is_error=True,
                                     text="инструмент недоступен", duration_ms=1)
            return original(name, arguments)

        instance.call_tool = call_tool
        return instance

    instance = mcp_with_broken_metrics()
    service = make_service(mcp=instance, session_factory=session_factory)
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert result["metrics"] == {}
    assert release.WARN_METRICS_UNAVAILABLE.format(error="MCP-инструмент get_project_metrics "
                                                         "вернул ошибку: инструмент недоступен") \
        in result["notes"]
    assert any("список тегов не получен" in note for note in result["notes"])


def test_truncated_changelog_adds_note(mcp, session_factory):
    """Обрезанное чтение CHANGELOG попадает в заметки (diff в предпросмотре неполон).

    Чтение ограничено ``release.RELEASE_MAX_READ_BYTES``, поэтому стенд делается больше
    предела: так проверяется настоящее условие обрезки, а не подмена константы.
    """
    head = f"# История\n\n## [1.0.0] - 2026-01-01\n\n{'x' * release.RELEASE_MAX_READ_BYTES}\n"
    mcp.files[release.CHANGELOG_PATH] = head
    service = make_service(mcp=mcp, session_factory=session_factory)
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert release.WARN_CHANGELOG_TRUNCATED.format(path=release.CHANGELOG_PATH) in result["notes"]


def test_failed_checks_are_reported_but_writes_happen(mcp, session_factory):
    """Непройденные проверки — заметка; файлы всё равно записываются."""
    service = make_service(mcp=mcp, session_factory=session_factory,
                           checks=lambda: make_checks(passed=False))
    result = service.prepare_release("day22", "HEAD", dry_run=False)
    assert result["checks_passed"] is False
    assert result["status"] == release.STATUS_COMPLETED
    assert release.WARN_CHECKS_FAILED.format(failed="tests") in result["notes"]
    assert len(result["files_to_modify"]) == 3


# ---------- запись ----------
def test_real_run_writes_all_three_files(service, mcp):
    """Реальный прогон: раздел в CHANGELOG, заметки, раздел README — всё через MCP."""
    result = service.prepare_release("day22", "HEAD", dry_run=False)
    assert result["status"] == release.STATUS_COMPLETED
    assert sorted(_written(result)) == sorted(
        [release.CHANGELOG_PATH, release.RELEASE_NOTES_PATH, release.README_PATH])
    assert service.export(result["run_id"])["files_modified"] == _written(result)
    changelog = mcp.files[release.CHANGELOG_PATH]
    assert changelog.index(release.release_heading("1.0.1")) < changelog.index("## [1.0.0]")
    assert "### Added" in changelog and "- MCP-инструменты git-истории релиза" in changelog
    assert release.README_SECTION_TITLE in mcp.files[release.README_PATH]
    notes = mcp.files[release.RELEASE_NOTES_PATH]
    assert notes.startswith("# Релиз 1.0.1 — ") and "## Как обновиться" in notes


def test_existing_section_is_skipped(mcp, session_factory):
    """Раздел, который уже есть в файле, не дублируется: CHANGELOG пропущен, README записан.

    Именно этот случай и достижим: база версии берётся из первой шапки CHANGELOG, а
    раздел сравнивается со ВСЕМ файлом — поэтому прогон версии, раздел которой уже
    вставлен, не удваивает её, а причину пропуска видно в заметках.
    """
    mcp.files[release.CHANGELOG_PATH] = (
        "# История изменений\n\n## [1.0.0] - 2026-10-15\n\n### Added\n- Первый релиз.\n\n"
        "## [1.0.1] - 2026-10-16\n\n### Added\n- Раздел уже на месте.\n")
    service = make_service(mcp=mcp, session_factory=session_factory)
    result = service.prepare_release("day22", "HEAD", dry_run=False)
    assert result["version"] == "1.0.1"
    skipped = {entry["path"] for entry in result["files_to_modify"] if entry["skipped"]}
    assert skipped == {release.CHANGELOG_PATH}
    assert _written(result) == [release.RELEASE_NOTES_PATH, release.README_PATH]
    assert result["status"] == release.STATUS_COMPLETED
    entry = next(item for item in result["files_to_modify"]
                 if item["path"] == release.CHANGELOG_PATH)
    assert entry["note"] == release.WARN_SECTION_EXISTS.format(
        heading=release.release_heading("1.0.1"), path=release.CHANGELOG_PATH)
    assert result["diff_preview"][release.CHANGELOG_PATH] == ""
    assert mcp.files[release.CHANGELOG_PATH].count(release.release_heading("1.0.1")) == 1


def test_missing_readme_is_skipped_with_note(mcp, session_factory):
    """Пропавший README не дописывается с нуля: правка пропускается, причина — в заметке."""
    mcp.files.pop(release.README_PATH)
    service = make_service(mcp=mcp, session_factory=session_factory)
    result = service.prepare_release("day1", "HEAD", dry_run=False)
    entry = next(item for item in result["files_to_modify"]
                 if item["path"] == release.README_PATH)
    assert entry["skipped"] is True and entry["ok"] is False
    assert release.WARN_CHANGELOG_MISSING.format(path=release.README_PATH) in result["notes"]
    assert _written(result) == [release.CHANGELOG_PATH, release.RELEASE_NOTES_PATH]


def test_write_failure_is_recorded_per_file(mcp, session_factory):
    """Сбой записи одного файла не останавливает остальные: он виден в строке плана."""
    original = mcp.call_tool

    def call_tool(name, arguments=None):
        if name == release.TOOL_APPLY_PATCH:
            from backend.domain.mcp_tools import MCPToolResult
            mcp.calls.append((name, dict(arguments or {})))
            return MCPToolResult(tool=name, arguments=arguments or {}, is_error=True,
                                 text="нет прав на запись", duration_ms=1)
        return original(name, arguments)

    mcp.call_tool = call_tool
    service = make_service(mcp=mcp, session_factory=session_factory)
    result = service.prepare_release("day22", "HEAD", dry_run=False)
    assert result["status"] == release.STATUS_FAILED
    assert _written(result) == [release.RELEASE_NOTES_PATH]
    failed = [entry for entry in result["files_to_modify"] if entry["error"]]
    assert {entry["path"] for entry in failed} == {release.CHANGELOG_PATH, release.README_PATH}
    assert release.WARN_WRITE_FAILED.format(
        path=release.CHANGELOG_PATH,
        error="MCP-инструмент apply_patch вернул ошибку: нет прав на запись") in result["notes"]


# ---------- пределы и счётчики ----------
def test_key_items_are_capped_and_minor_count_reported(mcp, session_factory):
    """Ключевых пунктов не больше 20; остальное сворачивается в счётчик коммитов."""
    commits = [{"hash": f"h{index}", "author": "a", "date": "d",
                "subject": f"day{index}: правка {index}", "message": f"day{index}: правка"}
               for index in range(25)]
    added = ", ".join(f'"пункт {index}"' for index in range(15))
    changed = ", ".join(f'"правка {index}"' for index in range(10))
    llm = ScriptedLLM([VERSION_JSON, f'{{"added": [{added}], "changed": [{changed}]}}'])
    service = make_service(mcp=FakeMCP(commits=commits), session_factory=session_factory,
                           llm=llm)
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    kept = sum(len(result["changelog"][key]) for key in release.GROUP_ORDER)
    assert kept == release.MAX_KEY_CHANGES
    assert result["changelog"]["dropped_count"] == 5
    assert len(result["changelog"]["added"]) == 15      # порядок групп: added идёт первым
    assert len(result["changelog"]["changed"]) == 5
    assert result["commits_count"] == 25
    assert result["changelog"]["minor_count"] == 25 - release.MAX_KEY_CHANGES


def test_unparseable_model_answer_uses_commit_subjects(mcp, session_factory):
    """Ответ модели не разобран — пунктами становятся заголовки коммитов, и есть заметка."""
    llm = ScriptedLLM(["никакого JSON", "тоже без JSON"])
    service = make_service(mcp=mcp, session_factory=session_factory, llm=llm)
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert result["version"] == "1.0.1"
    assert result["changelog"]["added"] == [commit["subject"] for commit in DEFAULT_COMMITS]
    assert release.FALLBACK_CHANGELOG_NOTE in result["notes"]
    assert llm.calls and len(llm.calls) == 4     # две попытки на каждый из двух вопросов


# ---------- читающие эндпоинты ----------
def test_tags_metrics_and_health(service):
    """Теги, метрики и проверки отдаются в формах схем API."""
    tags = service.tags()
    assert tags["count"] == 2 and tags["tags"][0]["name"] == "day34"
    assert service.metrics()["metrics"]["tests"] == 1723
    health = service.health()
    assert health["checks_passed"] is True and health["checks"]["coverage_percent"] == 91.5


def test_history_and_export_shapes(service):
    """История отдаёт запуски без текстов, выгрузка — с текстами; чужой id — ошибка."""
    first = service.prepare_release("day22", "HEAD", dry_run=True)
    service.prepare_release("day33", "HEAD", dry_run=True)
    runs = service.history()["runs"]
    assert [run["id"] for run in runs] == [2, 1]
    assert "changelog" not in runs[0] and "release_notes" not in runs[0]
    assert service.export(first["run_id"])["changelog"].startswith("## [1.0.1]")
    with pytest.raises(ReleaseRunNotFoundError):
        service.export(999)


def test_unknown_provider_is_rejected_before_mcp(service, mcp):
    """Незнакомый провайдер — ``ValueError`` до обращения к MCP и до строки истории."""
    with pytest.raises(ValueError):
        service.prepare_release("day22", "HEAD", provider="openai", dry_run=True)
    assert mcp.calls == [] and service.history()["count"] == 0
    assert llm_provider.PICKER_PROVIDERS == (llm_provider.PROVIDER_DEEPSEEK,
                                             llm_provider.PROVIDER_LOCAL)


def test_changed_files_and_commits_are_in_the_answer(service):
    """Коммиты и изменённые файлы попадают в ответ прогона целиком."""
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    assert result["commits_count"] == len(DEFAULT_COMMITS)
    assert result["changed_files"] == ['day21/backend/api/main.py',
                                       'day21/frontend/main_sections.py', 'README.md']
    assert result["provider"] == llm_provider.PROVIDER_DEEPSEEK
    assert result["metrics"]["assistants"] == 4


def test_current_changelog_is_read_and_diffed(service):
    """Предпросмотр diff-а показывает вставку раздела в начало файла."""
    result = service.prepare_release("day22", "HEAD", dry_run=True)
    diff = result["diff_preview"][release.CHANGELOG_PATH]
    added = [line for line in diff.splitlines() if line.startswith("+")]
    assert release.release_heading("1.0.1") in "\n".join(added)
    assert CHANGELOG_TEXT.splitlines()[0] not in "\n".join(added)
