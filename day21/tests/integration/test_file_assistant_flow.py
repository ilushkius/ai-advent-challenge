"""Интеграционный тест ассистента файлов (день 34): весь путь целиком.

Проверяется то, что юнит-тесты подменяют: НАСТОЯЩИЙ процесс
``mcp_servers/file_server/server.py``, запущенный дочерним процессом того же
интерпретатора, НАСТОЯЩИЕ файлы на диске и НАСТОЯЩИЙ diff относительно ``HEAD``.
Модель — заглушка (``ScriptedLLM``): тест не ходит в сеть и не тратит токены, но путь
«цель → план → чтение → правка → создание файла → diff → история» исполняется целиком.

Рабочий корень сервера — временный каталог (``tmp_path`` с файлами стенда): рабочее
дерево дня тест не трогает вообще. Поэтому ветка «файл вне репозитория git» в
``get_file_diff`` здесь и проверяется: временный каталог лежит вне ``ai-challenge/``,
и сервер честно отвечает текстом ``config.NOT_TRACKED_NOTE`` вместо diff-а.

Тест медленнее юнит-тестов (поднимается процесс MCP-сервера, файлы пишутся на диск),
поэтому файл помечен ``slow``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.core import config
from backend.domain import file_assistant
from mcp_servers.file_server import config as file_server_config
from backend.services.file_assistant_service import FileAssistantService
from backend.storage.file_assistant_store import FileAssistantStore

from file_assistant_fakes import ScriptedLLM

pytestmark = pytest.mark.slow

#: Тот же путь, что у службы: файл сервера файлов в пакете дня.
SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_servers" / "file_server" / "server.py"

#: Содержимое стенда: якорь для замены, две строки с ``IndexService`` и вложенный каталог.
USAGE_MD = "# Документация\n\n## 16. Частые ошибки\n\nТекст раздела.\n"
FILE_A = "from x import IndexService\n\nservice = IndexService()\n"
FILE_B = "# комментарий\n\ndef build() -> IndexService:\n    return IndexService()\n"
#: Куда правка вставляет новый раздел (якорь — заголовок следующего раздела).
ANCHOR = "## 16. Частые ошибки"
NEW_TEXT = "## 16. Ассистент файлов\n\nРаздел.\n\n## 17. Частые ошибки"
#: Создаваемый ADR: путь с новым вложенным каталогом.
ADR_PATH = "docs/adr/0001-deepseek-primary.md"
ADR_TEXT = "# ADR 0001: DeepSeek как основной провайдер\n\n## Решение\n\nИспользуем.\n"
SUMMARY = "Раздел добавлен в docs/usage.md, ADR создан."


def _plan(steps: list) -> str:
    """Ответ модели с планом шагов."""
    return json.dumps({"steps": steps}, ensure_ascii=False)


@pytest.fixture
def root(tmp_path):
    """Временный корень рабочей области сервера: файлы стенда и два каталога.

    Корень — ПОДкаталог ``tmp_path``: рядом pytest и фикстура ``session_factory``
    создают файл временной базы (``test.db``), и он не должен попадать в список
    файлов рабочей области, иначе проверка ``list_files(".")`` видела бы лишнее.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "backend").mkdir()
    # ``newline="\n"`` — файлы стенда побайтово равны константам выше: без этого
    # Windows записал бы переводы строк CRLF и проверки содержимого сравнивали бы разное.
    (root / "docs" / "usage.md").write_text(USAGE_MD, encoding="utf-8", newline="\n")
    (root / "backend" / "a.py").write_text(FILE_A, encoding="utf-8", newline="\n")
    (root / "backend" / "b.py").write_text(FILE_B, encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def flow_service(root, session_factory):
    """Служба на настоящем сервере файлов с временным корнем и заглушкой модели.

    Сценарий модели покрывает три вызова службы: план, вторая фаза (аргументы вместо
    маркеров) и сводка. Соединение закрывается в ``finally``: процесс сервера иначе
    остался бы висеть дочерним.
    """
    replies = [
        _plan([
            {"step_index": 0, "tool": file_assistant.TOOL_SEARCH_IN_FILES,
             "arguments": {"pattern": "IndexService", "directory": ".",
                           "file_glob": "*.py"},
             "reason": "найти места использования"},
            {"step_index": 1, "tool": file_assistant.TOOL_READ_FILE,
             "arguments": {"path": "docs/usage.md"}, "reason": "выбрать якорь замены"},
            {"step_index": 2, "tool": file_assistant.TOOL_APPLY_PATCH,
             "arguments": {"path": "docs/usage.md", "old_text": file_assistant.GENERATE_MARK,
                           "new_text": file_assistant.GENERATE_MARK},
             "reason": "вставить новый раздел"},
            {"step_index": 3, "tool": file_assistant.TOOL_WRITE_FILE,
             "arguments": {"path": ADR_PATH, "content": file_assistant.GENERATE_MARK},
             "reason": "создать ADR"},
        ]),
        _plan([
            {"step_index": 2, "arguments": {"path": "docs/usage.md", "old_text": ANCHOR,
                                            "new_text": NEW_TEXT}},
            {"step_index": 3, "arguments": {"path": ADR_PATH, "content": ADR_TEXT}},
        ]),
        SUMMARY,
    ]
    service = FileAssistantService(
        llm_client=ScriptedLLM(replies),
        mcp_target=f'"{sys.executable}" "{SERVER.resolve()}" --file-root "{root}"',
        mcp_cwd=config.MCP_FLEET_CWD,
        store=FileAssistantStore(session_factory=session_factory),
        sleep=lambda _seconds: None)
    try:
        yield service
    finally:
        service.close()


def test_tools_work_on_real_files(flow_service, root):
    """Инструменты сервера на настоящих файлах: каталог, чтение, поиск, запись и охрана корня.

    Проверяется контракт каждого инструмента глазами вызывающего: имена и схемы в
    каталоге, содержимое и размеры у чтения, совпадения с контекстом у поиска,
    реальная запись у правки и создания файла — и отказ на путь вне корня.
    """
    tools = {tool.name: tool for tool in flow_service.server.list_tools()}
    assert set(tools) == set(file_assistant.TOOLS)
    for name in file_assistant.TOOLS:
        assert tools[name].input_schema.get("properties"), name

    read = flow_service.mcp.call(file_assistant.TOOL_READ_FILE,
                                {"path": "docs/usage.md"})
    assert read[0] is True
    assert read[1]["content"] == USAGE_MD
    assert read[1]["chars"] == len(USAGE_MD) and read[1]["lines"] == 5
    assert read[1]["truncated"] is False and read[1]["extension"] == ".md"

    # ``max_bytes`` — предел БАЙТОВ: русский текст в UTF-8 даёт символов меньше
    short = flow_service.mcp.call(file_assistant.TOOL_READ_FILE,
                                 {"path": "docs/usage.md", "max_bytes": 10})
    assert short[1]["chars"] == len(USAGE_MD.encode("utf-8")[:10].decode("utf-8", "replace"))
    assert short[1]["chars"] < len(USAGE_MD) and short[1]["truncated"] is True

    found = flow_service.mcp.call(file_assistant.TOOL_SEARCH_IN_FILES,
                                 {"pattern": "IndexService", "directory": ".",
                                  "file_glob": "*.py"})
    assert found[0] is True
    assert {(item["path"], item["line_number"]) for item in found[1]} == {
        ("backend/a.py", 1), ("backend/a.py", 3), ("backend/b.py", 3), ("backend/b.py", 4)}
    assert found[1][0]["match"] == "IndexService"
    assert found[1][0]["line"] == "from x import IndexService"
    assert found[1][0]["context_before"] == []           # совпадение в первой строке файла
    assert found[1][0]["context_after"] == ["", "service = IndexService()"]
    later = next(item for item in found[1] if item["line_number"] == 4)
    assert later["context_before"] == ["# комментарий", "", "def build() -> IndexService:"]
    assert later["context_after"] == []                  # совпадение в последней строке

    # список — только ФАЙЛЫ каталога: подкаталоги в него не попадают (в корне стенда
    # файлов нет, поэтому пустой список — ожидаемый ответ, а не сбой)
    assert flow_service.mcp.call(file_assistant.TOOL_LIST_FILES,
                                {"directory": "."})[1] == []
    assert flow_service.mcp.call(file_assistant.TOOL_LIST_FILES,
                                {"directory": "docs"})[1] == ["usage.md"]
    assert flow_service.mcp.call(file_assistant.TOOL_LIST_FILES,
                                {"directory": "backend", "extension": "py"})[1] == [
        "a.py", "b.py"]

    patched = flow_service.mcp.call(file_assistant.TOOL_APPLY_PATCH, {
        "path": "backend/a.py", "old_text": "service = IndexService()",
        "new_text": "service = IndexService(debug=True)"})
    assert patched[0] is True and patched[1]["replaced"] == 1
    assert "IndexService(debug=True)" in (root / "backend" / "a.py").read_text(
        encoding="utf-8")

    written = flow_service.mcp.call(file_assistant.TOOL_WRITE_FILE,
                                   {"path": "docs/adr/0001.md", "content": "# ADR\n"})
    assert written[1]["created"] is True
    assert (root / "docs" / "adr" / "0001.md").read_text(encoding="utf-8") == "# ADR\n"

    escaped = flow_service.mcp.call(file_assistant.TOOL_READ_FILE,
                                   {"path": "../outside.txt"})
    assert escaped[0] is False and "вне проекта" in escaped[2]
    assert not (root.parent / "outside.txt").exists()


def test_goal_changes_files_and_history(flow_service, root):
    """Полная цель без ``dry_run``: файл изменён, ADR создан, diff и история записаны.

    Ожидается именно ДОСТИГНУТЫЙ результат: правка видна в файле на диске, созданный
    файл существует, оба пути попали в свои списки, а diff строится сервером
    (``git diff HEAD`` для изменённого файла и синтез для нового) и сохраняется в
    историю. Лишние файлы прогон не трогает.
    """
    record = flow_service.execute_goal(
        "Обнови docs/usage.md и создай ADR о выборе DeepSeek")

    assert record["status"] == file_assistant.STATUS_COMPLETED
    assert record["dry_run"] is False
    assert record["files_modified"] == ["docs/usage.md"]
    assert record["files_created"] == [ADR_PATH]
    assert record["files_read"] == ["docs/usage.md"]
    assert ANCHOR not in (root / "docs" / "usage.md").read_text(encoding="utf-8")
    assert NEW_TEXT.splitlines()[0] in (root / "docs" / "usage.md").read_text(
        encoding="utf-8")
    assert (root / ADR_PATH).read_text(encoding="utf-8") == ADR_TEXT
    assert [(step["tool"], step["status"]) for step in record["steps_executed"]] == [
        (file_assistant.TOOL_SEARCH_IN_FILES, file_assistant.STEP_OK),
        (file_assistant.TOOL_READ_FILE, file_assistant.STEP_OK),
        (file_assistant.TOOL_APPLY_PATCH, file_assistant.STEP_OK),
        (file_assistant.TOOL_WRITE_FILE, file_assistant.STEP_OK)]
    assert all(step["ok"] for step in record["steps_executed"])
    assert "# diff: docs/usage.md" in record["diff"]
    assert "# diff: " + ADR_PATH in record["diff"]
    # временный корень лежит вне репозитория: сервер отвечает не diff-ом, а этим текстом
    assert file_server_config.NOT_TRACKED_NOTE.split(":")[0] in record["diff"]
    assert record["summary"] == SUMMARY
    assert record["duration_ms"] >= 0

    stored = flow_service.diff_of(record["run_id"])
    assert stored["diff"] == record["diff"]
    assert stored["status"] == file_assistant.STATUS_COMPLETED
    assert (stored["files_modified"], stored["files_created"]) == (
        ["docs/usage.md"], [ADR_PATH])
    history = flow_service.history()
    assert history["count"] == 1
    assert history["runs"][0]["id"] == record["run_id"]
    assert history["runs"][0]["finished_at"] is not None
    assert len(history["runs"][0]["plan"]) == 4
    assert len(history["runs"][0]["steps"]) == 4
