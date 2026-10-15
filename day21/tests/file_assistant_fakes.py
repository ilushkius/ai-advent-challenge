"""Фейки ассистента файлов (день 34) для юнит-тестов службы и роутера.

Живут отдельным модулем, потому что фейков два набора: файловый сервер (словарь
файлов вместо диска, вызовы, ошибки) и соединение со stdio-сервером (ленивое
подключение и закрытие). Держать их в тестовом файле нельзя — он не должен расти от
каждого нового случая.

Настоящие файлы здесь не участвуют: ``FakeMCP`` держит содержимое в словаре
``files`` и меняет его так же, как сервер меняет файлы на диске. Поэтому юнит-тесты
проверяют РЕШЕНИЯ службы (какие шаги выполнены, что попало в журнал, какой вышел
diff, что записано в историю), а настоящую запись на диск и настоящий процесс
``mcp_servers/file_server/server.py`` — slow-интеграция
(``tests/integration/test_file_assistant_flow.py``).

Формы ответов фейка повторяют то, что служба получает от настоящего сервера через
SDK: объект — у ``read_file``/``write_file``/``apply_patch``, обёртка
``{"result": …}`` — у ``search_in_files``/``list_files``/``get_file_diff``. Так
проверяется и разбор форм (``FileMCPCalls.payload``), а не только логика шагов.

``ScriptedLLM`` отвечает словарём, как локальный провайдер: ``rag_llm.response_text``
читает поле ``answer``, поэтому тесты не создают ни ``LLMClient``, ни строки журнала
расходов и не пишут в рабочую ``agents.db``.
"""
from __future__ import annotations

from typing import Any, Optional

from backend.domain import file_assistant
from backend.domain.mcp_tools import MCPToolResult, make_tool_info
from backend.services.file_assistant_service import FileAssistantService
from backend.services.mcp_errors import MCPConnectionError

#: Что вернуть на ``read_file``, когда файла в словаре нет.
FILE_MISSING = "Файл не найден: {path}"
#: Что вернуть на ``apply_patch``, когда якорь не найден (текст сервера).
ANCHOR_MISSING = "Текст для замены не найден в файле {path}: прочитайте файл и повторите"


class ScriptedLLM:
    """Модель-заглушка: ответ по номеру вызова (последний повторяется).

    Возвращает словарь, как локальный провайдер (``rag_llm.response_text`` читает
    ``answer``), поэтому тесты не создают ни ``LLMClient``, ни журнала расходов и
    не пишут в рабочую ``agents.db``. Каждое обращение записывается в ``calls``:
    по нему проверяется, с каким типом задачи и каким системным промптом служба
    обратилась к модели (``orchestration`` у плана, ``code`` у второй фазы, ``chat``
    у сводки), и что каталог инструментов доехал в контексте.
    """

    def __init__(self, replies, error: Optional[Exception] = None) -> None:
        self.replies = list(replies)
        self.error = error
        self.calls: list = []

    def generate_with_context(self, *, system: str, context: str, question: str,
                              task_type: Optional[str] = None,
                              max_tokens: Optional[int] = None,
                              temperature: Optional[float] = None,
                              agent_id: Optional[str] = None) -> dict:
        """Ответ заглушки: пишет аргументы вызова и отдаёт следующий сценарий."""
        self.calls.append({"system": system, "context": context, "question": question,
                           "task_type": task_type, "max_tokens": max_tokens,
                           "temperature": temperature, "agent_id": agent_id})
        if self.error is not None:
            raise self.error
        position = min(len(self.calls) - 1, len(self.replies) - 1)
        return {"answer": self.replies[position]}

    def questions(self) -> list:
        """Вопросы всех вызовов: план, вторая фаза и сводка по порядку."""
        return [call["question"] for call in self.calls]


class FakeMCP:
    """MCP-клиент сервера файлов без транспорта: словарь файлов вместо диска.

    Подменяет и файловую систему, и процесс сервера: ``files`` — содержимое файлов,
    ``search`` — что вернуть на поиск, ``diff`` — текст ответа ``get_file_diff``,
    ``listed`` — имена файлов каталога (по умолчанию выводятся из ``files``). Полный
    список вызовов лежит в ``calls`` в порядке обращения: по нему проверяется и
    порядок шагов, и то, что в ``dry_run`` write-инструменты не вызывались вовсе.
    """

    def __init__(self, files: Optional[dict] = None, search: Optional[list] = None,
                 diff: str = "", listed: Optional[dict] = None,
                 error: Optional[Exception] = None, tool_error: str = "",
                 tools: Optional[tuple] = None) -> None:
        self.files = dict(files or {})
        self.search = list(search or [])
        self.diff = diff
        self.listed = dict(listed or {})
        self.error = error
        self.tool_error = tool_error
        self.calls: list = []
        self.closed = False
        self._tools = [make_tool_info(name, f"Инструмент {name}")
                       for name in (file_assistant.TOOLS if tools is None else tools)]

    # ---------- контракт клиента ----------
    def list_tools(self, *, refresh: bool = False) -> list:
        """Каталог инструментов: шесть функций сервера файлов."""
        return list(self._tools)

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> MCPToolResult:
        """Вызов инструмента: запись в ``calls`` и результат по имени."""
        call = dict(arguments or {})
        self.calls.append((name, call))
        if self.error is not None:
            raise self.error
        if self.tool_error:
            return MCPToolResult(tool=name, arguments=call, is_error=True,
                                 text=self.tool_error, duration_ms=1)
        if name == file_assistant.TOOL_READ_FILE:
            return self._read(call)
        if name == file_assistant.TOOL_APPLY_PATCH:
            return self._patch(call)
        if name == file_assistant.TOOL_WRITE_FILE:
            return self._write(call)
        if name == file_assistant.TOOL_SEARCH_IN_FILES:
            return self._wrap(name, call, self.search)
        if name == file_assistant.TOOL_LIST_FILES:
            return self._wrap(name, call, self._names(call))
        return self._wrap(name, call, self.diff)

    def close(self) -> None:
        """Помечает соединение закрытым (проверяется ``close()`` службы)."""
        self.closed = True

    def names(self) -> list:
        """Имена вызванных инструментов по порядку: порядок шагов в тесте."""
        return [name for name, _ in self.calls]

    # ---------- инструменты ----------
    def _read(self, call: dict) -> MCPToolResult:
        """``read_file``: содержимое словаря или ошибка инструмента (файла нет)."""
        path = str(call.get("path") or "")
        if path not in self.files:
            return MCPToolResult(tool=file_assistant.TOOL_READ_FILE, arguments=call,
                                 is_error=True, text=FILE_MISSING.format(path=path),
                                 duration_ms=1)
        text = self.files[path]
        return MCPToolResult(
            tool=file_assistant.TOOL_READ_FILE, arguments=call, text="ok", duration_ms=2,
            structured={"path": path, "size_bytes": len(text.encode("utf-8")),
                        "chars": len(text), "lines": len(text.splitlines()),
                        "truncated": False, "extension": "." + path.rsplit(".", 1)[-1],
                        "modified_at": "2026-10-15T00:00:00+00:00", "content": text})

    def _write(self, call: dict) -> MCPToolResult:
        """``write_file``: дописывает или перезаписывает содержимое словаря."""
        path = str(call.get("path") or "")
        content = str(call.get("content") or "")
        mode = str(call.get("mode") or "overwrite")
        created = path not in self.files
        if mode == "append" and not created:
            current = self.files[path]
            content = current + ("\n" if current and not current.endswith("\n") else "") + content
        self.files[path] = content
        return MCPToolResult(
            tool=file_assistant.TOOL_WRITE_FILE, arguments=call, text="ok", duration_ms=2,
            structured={"path": path, "mode": mode, "created": created,
                        "size_bytes": len(content.encode("utf-8")), "chars": len(content),
                        "lines": len(content.splitlines()),
                        "written_at": "2026-10-15T00:00:00+00:00"})

    def _patch(self, call: dict) -> MCPToolResult:
        """``apply_patch``: заменяет первое вхождение, как настоящий сервер."""
        path = str(call.get("path") or "")
        old_text = str(call.get("old_text") or "")
        new_text = str(call.get("new_text") or "")
        current = self.files.get(path)
        if current is None:
            return MCPToolResult(tool=file_assistant.TOOL_APPLY_PATCH, arguments=call,
                                 is_error=True, text=FILE_MISSING.format(path=path),
                                 duration_ms=1)
        occurrences = current.count(old_text) if old_text else 0
        if not occurrences:
            return MCPToolResult(tool=file_assistant.TOOL_APPLY_PATCH, arguments=call,
                                 is_error=True,
                                 text=ANCHOR_MISSING.format(path=path), duration_ms=1)
        self.files[path] = current.replace(old_text, new_text, 1)
        patched = self.files[path]
        return MCPToolResult(
            tool=file_assistant.TOOL_APPLY_PATCH, arguments=call, text="ok", duration_ms=3,
            structured={"path": path, "replaced": 1, "occurrences": occurrences,
                        "size_bytes": len(patched.encode("utf-8")),
                        "chars": len(patched), "lines": len(patched.splitlines()),
                        "patched_at": "2026-10-15T00:00:00+00:00"})

    def _names(self, call: dict) -> list:
        """Имена файлов каталога: из ``listed`` или выведенные из ``files``."""
        directory = str(call.get("directory") or ".").strip("/") or "."
        if directory in self.listed:
            return list(self.listed[directory])
        prefix = "" if directory in (".", "") else directory + "/"
        names = sorted(path[len(prefix):] for path in self.files
                       if path.startswith(prefix) and "/" not in path[len(prefix):])
        return names

    @staticmethod
    def _wrap(name: str, call: dict, value: Any) -> MCPToolResult:
        """Ответ-обёртка ``{"result": …}``: так SDK отдаёт список или строку."""
        return MCPToolResult(tool=name, arguments=call, duration_ms=1,
                             structured={"result": value}, text="ok")


class FakeStdioClient:
    """Подмена настоящего ``MCPClient``: считает созданные клиенты и помнит закрытие.

    Нужна там, где служба обязана поднять сервер САМА (``mcp_client`` не передан):
    настоящий клиент запускал бы процесс, а проверяется здесь логика соединения —
    один раз на процесс, с закрытием по ``close()``.
    """

    created = 0
    last_kwargs: dict = {}

    def __init__(self, target, **kwargs) -> None:
        type(self).created += 1
        type(self).last_kwargs = {"target": target, **kwargs}
        self.calls: list = []
        self.closed = False
        self.connected = True
        self._tools = [make_tool_info(name, f"Инструмент {name}")
                       for name in file_assistant.TOOLS]

    def connect(self):
        return self

    def list_tools(self, *, refresh: bool = False) -> list:
        return list(self._tools)

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> MCPToolResult:
        call = dict(arguments or {})
        self.calls.append((name, call))
        return MCPToolResult(tool=name, arguments=call, structured={"result": []},
                             text="ok", duration_ms=1)

    def close(self) -> None:
        self.closed = True


class FailingStdioClient(FakeStdioClient):
    """Подмена ``MCPClient``, у которой сервер не поднимается (нет процесса/команды)."""

    def connect(self):
        raise MCPConnectionError("сервер не отвечает")


def make_service(*, llm=None, mcp=None, store=None, **kwargs) -> FileAssistantService:
    """Служба на фейках: подставленные зависимости вместо модели, MCP и БД дня.

    ``store`` передаётся обязательно в тестах с историей: рабочая ``agents.db`` не
    должна видеть прогоны тестов, поэтому хранилище строится на временной фабрике
    сессий (``FileAssistantStore(session_factory=…)``).
    """
    return FileAssistantService(llm_client=llm, mcp_client=mcp, store=store,
                                sleep=lambda _seconds: None, **kwargs)
