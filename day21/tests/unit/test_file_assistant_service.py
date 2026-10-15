"""Юнит-тесты ассистента файлов (день 34): план, исполнение шагов и правила diff.

Проверяются три вещи — как служба получает план, как исполняет его шаги и какими
правилами домена пользуется. Всё офлайн: модель — ``ScriptedLLM``, файловый сервер —
``FakeMCP`` (словарь файлов вместо диска), хранилище — на временной БД, поэтому
рабочая ``agents.db`` и рабочее дерево дня не трогаются. Настоящий процесс
``mcp_servers/file_server/server.py`` и настоящую запись на диск проверяет
slow-интеграция (``tests/integration/test_file_assistant_flow.py``).
"""
from __future__ import annotations

import json

import pytest

from backend.domain import file_assistant
from backend.domain.file_assistant_plan import (
    needs_generation,
    parse_generate,
    path_is_within,
    path_problem,
)
from backend.domain.file_assistant_report import presumed_diff, verdict
from backend.services import file_mcp as file_mcp_module
from backend.services.file_assistant_service import FileAssistantService
from backend.services.rag_errors import RAGUpstreamError
from backend.storage.file_assistant_store import FileAssistantStore

from file_assistant_fakes import (FailingStdioClient, FakeMCP, FakeStdioClient,
                                 ScriptedLLM, make_service)

#: Содержимое двух файлов: один найден поиском, второй правится.
FILES = {
    "backend/a.py": "from x import IndexService\n\nservice = IndexService()\n",
    "docs/usage.md": "# Документация\n\n## 16. Частые ошибки\n\nТекст раздела.\n",
}
#: Совпадение поиска: путь из него подставляет вторая фаза.
MATCHES = [{"path": "backend/a.py", "line_number": 1, "match": "IndexService",
            "line": "from x import IndexService", "context_before": [],
            "context_after": [""]}]


def plan_json(steps: list) -> str:
    """Ответ модели с планом шагов (форма, которую ждёт ``parse_plan``)."""
    return json.dumps({"steps": steps}, ensure_ascii=False)


def store_of(session_factory) -> FileAssistantStore:
    """Хранилище запусков на временной БД теста."""
    return FileAssistantStore(session_factory=session_factory)


def test_builds_plan_for_goal(session_factory):
    """Поиск по цели: план, разрешение маркера, файлы и режим ``dry_run``.

    План состоит из поиска, чтения найденного файла и правки другого файла: так
    проверяются обе фазы сразу — путь для чтения берётся из результатов поиска
    (``$generate``), а якорь замены считается уже по содержимому файла. В ``dry_run``
    write-инструменты не вызываются вовсе, а diff остаётся предполагаемым.
    """
    store = store_of(session_factory)
    mcp = FakeMCP(FILES, MATCHES, diff="diff --git a/docs/usage.md b/docs/usage.md")
    llm = ScriptedLLM([
        plan_json([
            {"step_index": 0, "tool": file_assistant.TOOL_SEARCH_IN_FILES,
             "arguments": {"pattern": "IndexService", "directory": "."},
             "reason": "найти места использования"},
            {"step_index": 1, "tool": file_assistant.TOOL_READ_FILE,
             "arguments": {"path": file_assistant.GENERATE_MARK},
             "reason": "прочитать найденный файл"},
            {"step_index": 2, "tool": file_assistant.TOOL_APPLY_PATCH,
             "arguments": {"path": "docs/usage.md",
                           "old_text": file_assistant.GENERATE_MARK,
                           "new_text": file_assistant.GENERATE_MARK},
             "reason": "добавить раздел"},
        ]),
        plan_json([{"step_index": 1, "arguments": {"path": "backend/a.py"}},
                   {"step_index": 2, "arguments": {
                       "path": "docs/usage.md", "old_text": "## 16. Частые ошибки",
                       "new_text": "## 16. Ассистент файлов\n\nТекст.\n\n## 17. Частые ошибки"}}]),
        "Прочитан backend/a.py, раздел добавлен в docs/usage.md.",
    ])
    service = make_service(llm=llm, mcp=mcp, store=store)

    record = service.execute_goal("Найди все места, где используется IndexService",
                                 dry_run=True)

    assert record["status"] == file_assistant.STATUS_DRY_RUN
    assert record["dry_run"] is True
    assert record["provider"] == "deepseek"
    assert isinstance(record["run_id"], int)
    assert [step["tool"] for step in record["plan"]] == [
        file_assistant.TOOL_SEARCH_IN_FILES, file_assistant.TOOL_READ_FILE,
        file_assistant.TOOL_APPLY_PATCH]
    assert record["plan"][1]["arguments"]["path"] == "backend/a.py"   # из результатов поиска
    assert record["plan"][2]["arguments"]["old_text"] == "## 16. Частые ошибки"
    assert needs_generation(record["plan"][0]["arguments"]) is False
    # ``docs/usage.md`` прочитан внутренним шагом: без него не посчитать diff
    assert record["files_read"] == ["backend/a.py", "docs/usage.md"]
    assert record["files_modified"] == [] and record["files_created"] == []
    written = [name for name in mcp.names() if name in file_assistant.WRITE_TOOLS]
    assert written == []                        # dry_run не вызывает write-инструменты
    assert mcp.files["docs/usage.md"] == FILES["docs/usage.md"]   # файл не изменён
    assert "# предполагаемый diff: docs/usage.md" in record["diff"]
    assert "+## 16. Ассистент файлов" in record["diff"]
    assert record["summary"].startswith("Прочитан backend/a.py")
    assert [step["status"] for step in record["steps_executed"]] == [
        file_assistant.STEP_OK, file_assistant.STEP_OK, file_assistant.STEP_OK,
        file_assistant.STEP_SKIPPED]
    assert llm.calls[0]["task_type"] == "orchestration"
    assert llm.calls[1]["task_type"] == "code"
    assert llm.calls[-1]["task_type"] == "chat"
    assert file_assistant.catalog_text() in llm.calls[0]["context"]
    saved = store.list_runs(1)[0]
    assert (saved["id"], saved["status"]) == (record["run_id"], "dry_run")
    assert saved["finished_at"] is not None and saved["plan"] and saved["steps"]

    # --- цель пуста ---
    with pytest.raises(ValueError):
        service.execute_goal("   ")

    # --- план не разобран ни с первого, ни со второго ответа ---
    broken = make_service(llm=ScriptedLLM(["никакого json", "и тут не json"]),
                          mcp=FakeMCP(FILES), store=store)
    with pytest.raises(file_assistant.PlanRejected) as error:
        broken.execute_goal("Обнови docs/usage.md")
    assert error.value.problems == [file_assistant.REASON_BAD_JSON]
    assert error.value.raw == "и тут не json"

    # --- негодный план: неизвестный инструмент и путь вне проекта ---
    for steps, fragment in (
        ([{"step_index": 0, "tool": "rm_rf", "arguments": {}}], "шаг 0"),
        ([{"step_index": 0, "tool": file_assistant.TOOL_READ_FILE,
           "arguments": {"path": "../etc/passwd"}}], "шаг 0"),
    ):
        bad = make_service(llm=ScriptedLLM([plan_json(steps)]), mcp=FakeMCP(FILES),
                           store=store)
        with pytest.raises(file_assistant.PlanRejected) as error:
            bad.execute_goal("Прочитай файл")
        assert any(fragment in problem for problem in error.value.problems)

    # --- провайдер не ответил: запуск закрывается, а не висит в running ---
    silent = make_service(llm=ScriptedLLM([""], error=RAGUpstreamError("сеть недоступна")),
                          mcp=FakeMCP(FILES), store=store)
    with pytest.raises(Exception) as error:
        silent.execute_goal("Прочитай файл")
    assert "сеть недоступна" in str(error.value)
    assert store.list_runs(1)[0]["status"] == file_assistant.STATUS_FAILED


def test_executes_steps_with_mcp_mock(session_factory):
    """Правка файла: порядок вызовов, якорь из прочитанного и запись в историю.

    Обычный режим (не ``dry_run``) обязан прочитать файл ДО правки: якорь замены
    берётся дословно из содержимого, и ``apply_patch`` получает именно его. Diff
    собирается отдельным вызовом ``get_file_diff`` по изменённому пути.
    """
    store = store_of(session_factory)
    mcp = FakeMCP(FILES, MATCHES, diff="diff --git a/docs/usage.md b/docs/usage.md\n@@")
    llm = ScriptedLLM([
        plan_json([
            {"step_index": 0, "tool": file_assistant.TOOL_READ_FILE,
             "arguments": {"path": "docs/usage.md"}, "reason": "прочитать файл"},
            {"step_index": 1, "tool": file_assistant.TOOL_APPLY_PATCH,
             "arguments": {"path": "docs/usage.md",
                           "old_text": file_assistant.GENERATE_MARK,
                           "new_text": file_assistant.GENERATE_MARK},
             "reason": "добавить раздел"},
        ]),
        plan_json([{"step_index": 1, "arguments": {
            "path": "docs/usage.md", "old_text": "## 16. Частые ошибки",
            "new_text": "## 16. Ассистент файлов\n\n## 17. Частые ошибки"}}]),
        "Раздел добавлен в docs/usage.md.",
    ])
    service = make_service(llm=llm, mcp=mcp, store=store)

    record = service.execute_goal("Обнови docs/usage.md: добавь раздел про ассистента файлов")

    assert record["status"] == file_assistant.STATUS_COMPLETED
    assert mcp.names() == [file_assistant.TOOL_READ_FILE, file_assistant.TOOL_APPLY_PATCH,
                          file_assistant.TOOL_GET_FILE_DIFF]
    patched = next(arguments for name, arguments in mcp.calls
                   if name == file_assistant.TOOL_APPLY_PATCH)
    assert patched["old_text"] == "## 16. Частые ошибки"
    assert patched["old_text"] in FILES["docs/usage.md"]       # якорь дословный
    assert record["files_read"] == ["docs/usage.md"]
    assert record["files_modified"] == ["docs/usage.md"]
    assert record["files_created"] == []
    assert "тот же язык" not in record["summary"] and record["summary"]
    assert "# diff: docs/usage.md" in record["diff"]
    saved = store.run(record["run_id"])
    assert saved["finished_at"] is not None
    assert [step["status"] for step in saved["steps"]] == ["ok", "ok"]
    assert saved["diff"] == record["diff"]

    # --- инструмент вернул ошибку: прогон остановлен, шаги после него пропущены ---
    broken_mcp = FakeMCP(FILES, MATCHES, tool_error="инструмент недоступен")
    broken = make_service(llm=ScriptedLLM([plan_json([
        {"step_index": 0, "tool": file_assistant.TOOL_READ_FILE,
         "arguments": {"path": "docs/usage.md"}, "reason": "прочитать"},
        {"step_index": 1, "tool": file_assistant.TOOL_READ_FILE,
         "arguments": {"path": "backend/a.py"}, "reason": "прочитать ещё"},
    ]), "сводка"]), mcp=broken_mcp, store=store)

    failed = broken.execute_goal("Прочитай оба файла")

    assert failed["status"] == file_assistant.STATUS_FAILED
    assert "инструмент недоступен" in failed["steps_executed"][0]["error"]
    assert failed["steps_executed"][0]["status"] == file_assistant.STEP_FAILED
    assert failed["steps_executed"][1]["status"] == file_assistant.STEP_SKIPPED
    assert failed["steps_executed"][1]["ok"] is False
    assert store.run(failed["run_id"])["status"] == file_assistant.STATUS_FAILED


def test_diff_formation():
    """Правила diff-а, маркера, путей и вердикта — без службы и без MCP.

    Предполагаемый diff (``dry_run``) обязан совпадать по смыслу с настоящей правкой:
    перезапись — против нового содержимого, дозапись — против дописанного варианта
    (с переводом строки, как у сервера), замена — против результата подстановки.
    Отсутствие якоря даёт пустой diff: обещать правку, которой не будет, нельзя.
    """
    assert "-old line" in presumed_diff("docs/a.md", "old line\n",
                                        file_assistant.TOOL_WRITE_FILE,
                                        {"content": "new line\n"})
    assert "+new line" in presumed_diff("docs/a.md", "old line\n",
                                        file_assistant.TOOL_WRITE_FILE,
                                        {"content": "new line\n"})
    appended = presumed_diff("docs/a.md", "old", file_assistant.TOOL_WRITE_FILE,
                             {"content": "next", "mode": "append"})
    assert "+next" in appended and "old" in appended
    assert "-b" in presumed_diff("docs/a.md", "a\nb\n", file_assistant.TOOL_APPLY_PATCH,
                                 {"old_text": "b", "new_text": "B"})
    assert presumed_diff("docs/a.md", "a\n", file_assistant.TOOL_APPLY_PATCH,
                         {"old_text": "нет такого", "new_text": "x"}) == ""
    assert presumed_diff("docs/a.md", "a\n", file_assistant.TOOL_WRITE_FILE,
                         {"content": "a\n"}) == file_assistant.NO_PRESUMED_DIFF

    assert needs_generation({"path": [file_assistant.GENERATE_MARK]}) is True
    assert needs_generation({"content": file_assistant.GENERATE_MARK + ": текст"}) is True
    assert needs_generation({"path": "docs/usage.md"}) is False
    assert parse_generate('{"steps": [{"step_index": 2, "arguments": {"a": 1}}]}',
                          [2]) == {2: {"a": 1}}
    assert parse_generate('{"steps": [{"step_index": 2, "arguments": {"a": 1}}]}',
                          [1, 2]) is None
    assert parse_generate("никакого json", [0]) is None

    for good in ("docs/usage.md", "backend/a.py", "."):
        assert path_problem(good) == "" and path_is_within(good)
    for bad in ("../AGENTS.md", "/etc/passwd", "", "docs\\usage.md", "C:/x", "a/../b"):
        assert path_problem(bad) and not path_is_within(bad)

    done = {"status": file_assistant.STATUS_COMPLETED, "dry_run": False,
            "steps_executed": [{"step_index": 0, "tool": "read_file", "ok": True}],
            "files_modified": ["docs/usage.md"], "files_created": []}
    assert verdict(done, file_assistant.DEMO_SCENARIOS[2]).startswith("⚠️")
    assert verdict(done, file_assistant.DEMO_SCENARIOS[1]).startswith("✅")
    assert verdict({**done, "dry_run": True},
                   file_assistant.DEMO_SCENARIOS[1]).startswith("🧪")
    assert verdict({**done, "steps_executed": [
        {"step_index": 1, "tool": "apply_patch", "ok": False, "error": "не найден"}]},
        file_assistant.DEMO_SCENARIOS[1]).startswith("❌")


def test_diff_blocks_and_connection(session_factory, monkeypatch):
    """Итоговый diff — блок на каждый файл, а соединение сервера одно на процесс.

    Диффы изменённых и созданных файлов склеиваются с шапкой ``# diff: <путь>``:
    одного текста ``git diff`` на два файла не хватило бы, чтобы понять, что к чему.
    Соединение поднимается лениво, переиспользуется вторым прогоном и закрывается
    ``close()`` — иначе stdio-процесс сервера остался бы висеть после остановки.
    """
    store = store_of(session_factory)
    mcp = FakeMCP(FILES, MATCHES, diff="diff --git a/x b/x")
    plan = plan_json([
        {"step_index": 0, "tool": file_assistant.TOOL_WRITE_FILE,
         "arguments": {"path": "docs/a.md", "content": "A"}, "reason": "создать A"},
        {"step_index": 1, "tool": file_assistant.TOOL_WRITE_FILE,
         "arguments": {"path": "docs/b.md", "content": "B"}, "reason": "создать B"},
    ])
    service = make_service(llm=ScriptedLLM([plan, "Созданы два файла."]),
                           mcp=mcp, store=store)

    record = service.execute_goal("Создай два файла в docs")

    assert record["files_created"] == ["docs/a.md", "docs/b.md"]
    assert record["diff"].count("# diff:") == 2
    assert "# diff: docs/a.md" in record["diff"] and "# diff: docs/b.md" in record["diff"]
    assert mcp.names().count(file_assistant.TOOL_GET_FILE_DIFF) == 2

    # --- ленивое соединение: один клиент на процесс, закрывается по close() ---
    FakeStdioClient.created = 0
    monkeypatch.setattr(file_mcp_module, "MCPClient", FakeStdioClient)
    live = FileAssistantService(llm_client=ScriptedLLM(["текст плана — не json"]),
                               store=store, sleep=lambda _seconds: None)
    with pytest.raises(file_assistant.PlanRejected):
        live.execute_goal("Что-нибудь")
    assert FakeStdioClient.created == 0          # план не собрался — сервер не поднимался
    live.close()

    listed = plan_json([
        {"step_index": 0, "tool": file_assistant.TOOL_LIST_FILES,
         "arguments": {"directory": "."}, "reason": "посмотреть каталог"}])
    working = FileAssistantService(
        llm_client=ScriptedLLM([listed, "Каталог прочитан.",
                                listed, "Каталог прочитан."]), store=store,
        sleep=lambda _seconds: None)
    working.execute_goal("Что лежит в каталоге?")
    working.execute_goal("Что лежит в каталоге?")
    assert FakeStdioClient.created == 1          # соединение одно на процесс
    created = working._mcp.server
    working.close()
    assert created.closed is True

    # --- сервер не поднимается: шаг сообщает причину, а не падает стеком ---
    monkeypatch.setattr(file_mcp_module, "MCPClient", FailingStdioClient)
    down = FileAssistantService(llm_client=ScriptedLLM([listed, "Каталог прочитан."]),
                                store=store, sleep=lambda _seconds: None)
    broken = down.execute_goal("Что лежит в каталоге?")
    assert broken["status"] == file_assistant.STATUS_FAILED
    assert file_assistant.WARN_MCP_UNAVAILABLE.split("{")[0] in \
        broken["steps_executed"][0]["error"]
    down.close()
