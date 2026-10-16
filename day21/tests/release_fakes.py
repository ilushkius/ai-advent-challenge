"""Фейки подготовки релиза (день 35) для юнит-тестов службы, роутера и раздела.

Живут отдельным модулем, потому что подменяются три разные вещи: MCP-сервер файлов
и git-истории (``FakeMCP``), модель (``ScriptedLLM``) и проверки готовности
(``make_checks``). Держать их в тестовом файле нельзя — он не должен расти от каждого
нового случая.

Настоящие файлы и настоящий git здесь не участвуют: ``FakeMCP`` держит содержимое в
словаре ``files`` и меняет его так же, как сервер меняет файлы на диске
(``apply_patch`` заменяет ПЕРВОЕ вхождение, пропавший якорь — ошибка инструмента).
Поэтому юнит-тесты проверяют РЕШЕНИЯ службы (какая версия предложена, что попало в
раздел, какие файлы записаны, что видно в предпросмотре), а настоящий процесс
``mcp_servers/file_server/server.py`` и настоящий git — slow-интеграция
(``tests/integration/test_release_flow.py``).

``FakeMCP.calls`` и ``FakeMCP.writes`` — разные списки намеренно: тест ``dry_run``
должен уметь сказать «записи не было НИ ОДНОЙ» (``writes == []``), а не «не было
среди прочих вызовов».

``ScriptedLLM`` отвечает словарём, как локальный провайдер: ``rag_llm.response_text``
читает поле ``answer``, поэтому тесты не создают ни ``LLMClient``, ни строки журнала
расходов и не пишут в рабочую ``agents.db``.
"""
from __future__ import annotations

from typing import Any, Optional

from backend.domain import file_assistant, release
from backend.domain.mcp_tools import MCPToolResult, make_tool_info
from backend.services.release_service import ReleaseService
from backend.storage.release_store import ReleaseStore

#: Инструменты файлов сервера: клиент обязан отдавать их в каталоге наравне с git.
FILE_TOOLS = file_assistant.TOOLS
#: Тексты ошибок инструментов повторяют настоящий сервер (``mcp_servers/file_server``).
FILE_MISSING = "Файл не найден: {path}"
ANCHOR_MISSING = "Текст для замены не найден в файле {path}"

#: Стенд файлов: ``CHANGELOG.md`` уже с шапкой версии (база для новой), ``README.md`` —
#: с якорем вставки раздела, заметок о релизе ещё нет.
CHANGELOG_TEXT = ("# История изменений\n\nДневник челленджа по дням.\n\n"
                  "## [1.0.0] - 2026-10-15\n\n### Added\n- Первый релиз.\n")
README_TEXT = ("# ai-challenge\n\nПрактикум по LLM.\n\n"
               "## Структура репозитория\n\n- `day21/` — текущий день.\n")

#: Теги и коммиты стенда: заголовки в стиле проекта (метки ``feat``/``BREAKING`` нет,
#: поэтому правило даёт ``patch``), один коммит с телом.
DEFAULT_TAGS = [{"name": "day34", "date": "2026-10-15T22:59:09+05:00", "commit": "99c82f0"},
                {"name": "day22", "date": "2026-09-29T23:07:30+05:00", "commit": "512ecdd"}]
DEFAULT_COMMITS = [
    {"hash": "aaa1111", "author": "ilushkius", "date": "2026-10-15T22:59:09+05:00",
     "subject": "day34: add file assistant with MCP file_server",
     "message": "day34: add file assistant with MCP file_server Сервер читает и правит файлы"},
    {"hash": "bbb2222", "author": "ilushkius", "date": "2026-10-14T23:01:18+05:00",
     "subject": "day33: add user support assistant", "message": "day33: add user support assistant"},
    {"hash": "ccc3333", "author": "ilushkius", "date": "2026-10-13T23:29:46+05:00",
     "subject": "docs: change main README", "message": "docs: change main README"},
]
DEFAULT_CHANGED = ["day21/backend/api/main.py", "day21/frontend/main_sections.py", "README.md"]
DEFAULT_METRICS = {"tags": 14, "commits": 70, "py_files": 579, "tests": 1723,
                   "mcp_servers": 7, "assistants": 4}
#: Ответ ``get_commit_stats`` одного коммита (форма настоящего инструмента).
DEFAULT_STATS = {"ref": "day34", "commit": "99c82f0", "author": "ilushkius",
                 "date": "2026-10-15T22:59:09+05:00", "subject": "day34: add file assistant",
                 "files": 47, "insertions": 5058, "deletions": 212}

#: Готовые ответы модели: тип версии и группы CHANGELOG (валидный JSON без markdown).
VERSION_JSON = ('{"suggested_version": "patch", "reason": "служебные правки и документация", '
                '"breaking_changes": [], "features": ["ассистент файлов"], '
                '"fixes": ["правка README"]}')
CHANGELOG_JSON = ('{"breaking": [], "added": ["MCP-инструменты git-истории релиза", '
                  '"эндпоинты /release/*"], "changed": ["README: раздел результата"], '
                  '"fixed": [], "removed": []}')


class ScriptedLLM:
    """Модель-заглушка: ответ по номеру вызова (последний повторяется)."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def generate_with_context(self, *, system: str, context: str, question: str,
                              task_type: str, agent_id: str, temperature: float,
                              max_tokens: int) -> dict:
        """Ответ словарём (как локальный провайдер): ``answer`` читает ``response_text``."""
        self.calls.append({"system": system, "context": context, "question": question,
                           "task_type": task_type, "agent_id": agent_id,
                           "temperature": temperature, "max_tokens": max_tokens})
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return {"answer": self.replies[index], "tokens": {}}


class FailingLLM:
    """Модель, которая всегда отказывает: ``RAGUpstreamError`` из ``call_with_retry``."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_with_context(self, **kwargs) -> dict:
        self.calls += 1
        raise RuntimeError("модель недоступна")


class FakeMCP:
    """Подмена MCP-клиента сервера файлов: словарь файлов и данные git вместо процесса.

    Подменяется именно КЛИЕНТ (``MCPClient``), а не обвязка ``FileMCPCalls``: тогда
    настоящий код разбора форм ответа и текстов ошибок остаётся в тесте, и проверяются
    решения службы, а не заглушки. Формы ответов повторяют сервер: словарь у
    ``read_file``/``write_file``/``apply_patch``, обёртка ``{"result": …}`` — у
    инструментов git-истории (SDK отдаёт так список).

    ``calls`` — все вызовы по порядку, ``writes`` — только изменяющие: тест ``dry_run``
    проверяет «записи не было НИ ОДНОЙ», а не «её не было среди прочих вызовов».
    ``error`` бросается из ``call_tool`` — так проверяется недоступный сервер.
    """

    def __init__(self, *, files: Optional[dict] = None, tags: Optional[list] = None,
                 commits: Optional[list] = None, changed: Optional[list] = None,
                 metrics: Optional[dict] = None, stats: Optional[dict] = None,
                 tool_error: str = "", error: Optional[Exception] = None) -> None:
        self.files = dict(files if files is not None else {
            release.CHANGELOG_PATH: CHANGELOG_TEXT, release.README_PATH: README_TEXT})
        self.tags = list(tags if tags is not None else DEFAULT_TAGS)
        self.commits = list(commits if commits is not None else DEFAULT_COMMITS)
        self.changed = list(changed if changed is not None else DEFAULT_CHANGED)
        self.metrics = dict(metrics if metrics is not None else DEFAULT_METRICS)
        self.stats = dict(stats or DEFAULT_STATS)
        self.tool_error = tool_error
        self.error = error
        self.calls: list[tuple] = []
        self.writes: list[tuple] = []
        self.closed = False
        self._tools = [make_tool_info(name, f"Инструмент {name}")
                       for name in (*FILE_TOOLS, *release.GIT_TOOLS)]

    # ---------- контракт клиента ----------
    def list_tools(self, *, refresh: bool = False) -> list:
        """Каталог инструментов: файловые и git-истории."""
        return list(self._tools)

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> MCPToolResult:
        """Вызов инструмента: запись в ``calls`` и ответ по имени."""
        call = dict(arguments or {})
        self.calls.append((name, call))
        if self.error is not None:
            raise self.error
        if self.tool_error:
            return MCPToolResult(tool=name, arguments=call, is_error=True,
                                 text=self.tool_error, duration_ms=1)
        if name == release.TOOL_READ_FILE:
            return self._read(call)
        if name == release.TOOL_WRITE_FILE:
            return self._write(call)
        if name == release.TOOL_APPLY_PATCH:
            return self._patch(call)
        if name == release.TOOL_GET_TAGS:
            return _wrap(name, call, list(self.tags))
        if name == release.TOOL_COMMITS_BETWEEN:
            return _wrap(name, call, list(self.commits))
        if name == release.TOOL_CHANGED_FILES_BETWEEN:
            return _wrap(name, call, list(self.changed))
        if name == release.TOOL_COMMIT_STATS:
            return _wrap(name, call, dict(self.stats))
        if name == release.TOOL_PROJECT_METRICS:
            return _wrap(name, call, dict(self.metrics))
        return MCPToolResult(tool=name, arguments=call, is_error=True,
                             text=f"Неизвестный инструмент: {name}", duration_ms=1)

    def close(self) -> None:
        """Помечает соединение закрытым (проверяется ``close()`` службы)."""
        self.closed = True

    @property
    def tools_called(self) -> list:
        """Имена вызванных инструментов в порядке вызовов."""
        return [name for name, _call in self.calls]

    # ---------- инструменты ----------
    def _read(self, call: dict) -> MCPToolResult:
        """``read_file``: содержимое словаря, пропавший файл — ошибка инструмента."""
        path = str(call.get("path") or "")
        if path not in self.files:
            return MCPToolResult(tool=release.TOOL_READ_FILE, arguments=call, is_error=True,
                                 text=FILE_MISSING.format(path=path), duration_ms=1)
        text = str(self.files[path])
        limit = int(call.get("max_bytes") or 0)
        data = text.encode("utf-8")
        truncated = bool(limit) and len(data) > limit
        content = data[:limit].decode("utf-8", "replace") if truncated else text
        return MCPToolResult(
            tool=release.TOOL_READ_FILE, arguments=call, text="ok", duration_ms=2,
            structured={"path": path, "size_bytes": len(data), "chars": len(content),
                        "lines": len(content.splitlines()), "truncated": truncated,
                        "extension": "." + path.rsplit(".", 1)[-1], "content": content})

    def _write(self, call: dict) -> MCPToolResult:
        """``write_file``: дописывает или перезаписывает содержимое словаря."""
        path = str(call.get("path") or "")
        content = str(call.get("content") or "")
        mode = str(call.get("mode") or "overwrite")
        created = path not in self.files
        if mode == "append" and not created and content:
            current = str(self.files[path])
            content = current + ("\n" if current and not current.endswith("\n") else "") + content
        self.files[path] = content
        self.writes.append((release.TOOL_WRITE_FILE, dict(call)))
        return MCPToolResult(
            tool=release.TOOL_WRITE_FILE, arguments=call, text="ok", duration_ms=2,
            structured={"path": path, "mode": mode, "created": created,
                        "chars": len(content), "size_bytes": len(content.encode("utf-8")),
                        "lines": len(content.splitlines())})

    def _patch(self, call: dict) -> MCPToolResult:
        """``apply_patch``: заменяет первое вхождение, как настоящий сервер."""
        path = str(call.get("path") or "")
        old_text = str(call.get("old_text") or "")
        new_text = str(call.get("new_text") or "")
        current = self.files.get(path)
        if current is None:
            return MCPToolResult(tool=release.TOOL_APPLY_PATCH, arguments=call,
                                 is_error=True, text=FILE_MISSING.format(path=path),
                                 duration_ms=1)
        occurrences = str(current).count(old_text) if old_text else 0
        if not occurrences:
            return MCPToolResult(tool=release.TOOL_APPLY_PATCH, arguments=call,
                                 is_error=True, text=ANCHOR_MISSING.format(path=path),
                                 duration_ms=1)
        self.files[path] = str(current).replace(old_text, new_text, 1)
        self.writes.append((release.TOOL_APPLY_PATCH, dict(call)))
        return MCPToolResult(
            tool=release.TOOL_APPLY_PATCH, arguments=call, text="ok", duration_ms=3,
            structured={"path": path, "replaced": 1, "occurrences": occurrences,
                        "chars": len(str(self.files[path]))})


def _wrap(name: str, call: dict, value: Any) -> MCPToolResult:
    """Ответ-обёртка ``{"result": …}``: так SDK отдаёт список или словарь инструмента."""
    return MCPToolResult(tool=name, arguments=call, duration_ms=1,
                         structured={"result": value}, text="ok")


def make_checks(*, passed: bool = True, coverage: float = 91.5, readme: bool = True,
                docs: bool = True) -> dict:
    """Результат проверок готовности: тот же контракт, что у ``release_checks``."""
    commands = [{"name": "tests", "command": "uv run pytest -m not slow -q",
                 "returncode": 0 if passed else 1, "duration_ms": 1000,
                 "tail": "10 passed"},
                {"name": "coverage", "command": "uv run pytest --cov=backend -q",
                 "returncode": 0, "duration_ms": 2000, "tail": f"TOTAL ... {coverage}%"}]
    files = {"readme": {"path": release.README_PATH, "exists": readme},
             "docs": {"path": "day21/docs/architecture.md", "exists": docs}}
    return {"tests_passed": passed, "coverage_percent": coverage, "readme_exists": readme,
            "docs_exists": docs, "passed": bool(passed and readme and docs), "notes": [],
            "files": files, "commands": commands}


def make_service(*, llm: Any = None, mcp: Any = None, store: Any = None,
                 session_factory: Any = None, checks: Any = None, **kwargs: Any):
    """Служба релиза на фейках: заглушка модели, словарь файлов и временная БД."""
    return ReleaseService(
        llm_client=llm if llm is not None else ScriptedLLM([VERSION_JSON, CHANGELOG_JSON]),
        mcp_client=mcp if mcp is not None else FakeMCP(),
        store=store if store is not None else ReleaseStore(session_factory=session_factory),
        checks=checks if checks is not None else make_checks,
        sleep=lambda _seconds: None, **kwargs)
