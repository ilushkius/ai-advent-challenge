"""Фейки ассистента разработчика (день 31) для юнит-тестов службы.

Живут отдельным модулем, потому что фейков стало два набора: сама служба (классификация
вопроса, контекст, ответы и отказы) и панели раздела (каталог инструментов, git-контекст,
соединение со stdio-сервером). Держать их в одном тестовом файле нельзя — он вышел за
предел 400 строк, а копировать фейки в два файла значит рано или поздно развести их
поведение.

Настоящие зависимости здесь не участвуют: индекс — фейк (отдаёт заданные попадания или
падает), MCP-клиент — фейк (пишет вызовы, отдаёт результат по имени инструмента),
модель — ``RagStubClient`` из ``tests/rag_fakes.py``. Поэтому тесты службы идут офлайн, а
настоящий корпус и настоящий процесс ``dev_server`` проверяет slow-интеграция.
"""
from __future__ import annotations

from backend.domain import dev_assistant
from backend.domain.mcp_tools import MCPToolResult, make_tool_info
from backend.services.dev_assistant_service import DevAssistantService
from backend.services.mcp_errors import MCPConnectionError

#: Два канонических фрагмента документации: текст попадает в промпт, поэтому он
#: ищется в сообщениях заглушки — так проверяется, что контекст реально доехал.
HITS = [
    {"chunk_id": "c-1", "source": "day21-docs-architecture.md", "title": "Архитектура",
     "section": "Три слоя памяти", "score": 0.83, "content": "Краткосрочная память — сессия."},
    {"chunk_id": "c-2", "source": "day21-docs-usage.md", "title": "Инструкция",
     "section": "Тесты", "score": 0.61, "content": "Тесты запускаются pytest -m not slow."},
]

#: Ответ git-инструмента: то, что видит служба в ``structuredContent``.
GIT_STRUCTURED = {
    "branch": "main",
    "last_commit": "abc123 day30: удалённая LLM",
    "modified_files": ["day21/app.py"],
    "clean": False,
    "repo_root": "/repo",
}

#: Ответы фейкового сервера по именам инструментов: строка — текстовый результат,
#: ``None`` — результат без структуры (только текст).
TOOL_RESULTS = {
    dev_assistant.TOOL_GIT_BRANCH: GIT_STRUCTURED,
    dev_assistant.TOOL_PROJECT_STRUCTURE: {"root": "/repo/day21", "files": 153},
    dev_assistant.TOOL_GIT_DIFF: "@@ -1 +1 @@\n-старое\n+новое",
    dev_assistant.TOOL_LIST_FILES: {"directory": "day21", "count": 2,
                                    "truncated": False, "files": ["app.py", "README.md"]},
}


class FakeIndexService:
    """Служба поиска без индекса: отдаёт заданные попадания или падает."""

    def __init__(self, hits=None, error: Exception | None = None) -> None:
        self.hits = list(HITS if hits is None else hits)
        self.error = error
        self.calls: list = []

    def search(self, query: str, top_k=None, strategy: str = ""):
        self.calls.append({"query": query, "top_k": top_k, "strategy": strategy})
        if self.error is not None:
            raise self.error
        return list(self.hits)


class FakeMCP:
    """MCP-клиент без транспорта: записывает вызовы и отдаёт результат по имени."""

    def __init__(self, error: Exception | None = None, tool_error: str = "",
                 results=None, tools=None, empty_tools=()) -> None:
        self.error = error
        self.tool_error = tool_error
        self.results = dict(TOOL_RESULTS if results is None else results)
        self.calls: list = []
        self.connected = True
        self.closed = False
        #: Инструменты, вернувшие пустой ответ: ни структуры, ни текста.
        self.empty_tools = tuple(empty_tools)
        self._tools = [make_tool_info(name, f"Инструмент {name}")
                       for name in (dev_assistant.TOOLS if tools is None else tools)]

    def list_tools(self, *, refresh: bool = False):
        return list(self._tools)

    def call_tool(self, name: str, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        if self.error is not None:
            raise self.error
        if self.tool_error:
            return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                                 text=self.tool_error, is_error=True, duration_ms=3)
        if name in self.empty_tools:
            return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                                 structured=None, text="", duration_ms=1)
        result = self.results.get(name, {})
        if result is None:
            return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                                 structured=None, text="текст без структуры", duration_ms=2)
        if isinstance(result, str):
            return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                                 structured={"result": result}, text=result, duration_ms=2)
        return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                             structured=result, text="ok", duration_ms=2)

    def close(self) -> None:
        self.closed = True


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
        self._connected = False

    def connect(self):
        self._connected = True
        return self

    def list_tools(self, *, refresh: bool = False):
        return [make_tool_info(name, f"Инструмент {name}")
                for name in dev_assistant.TOOLS]

    def call_tool(self, name: str, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                             structured=dict(GIT_STRUCTURED), text="ok", duration_ms=1)

    def close(self) -> None:
        self.closed = True


class FailingStdioClient(FakeStdioClient):
    """Подмена ``MCPClient``, у которой сервер не поднимается (нет процесса/команды)."""

    def connect(self):
        raise MCPConnectionError("сервер не отвечает")


def make_service(*, index=None, mcp=None, client=None, **kwargs) -> DevAssistantService:
    """Служба на фейках: подставленные зависимости вместо служб процесса."""
    return DevAssistantService(index_service=index if index is not None else FakeIndexService(),
                               mcp_client=mcp if mcp is not None else FakeMCP(),
                               llm_client=client, sleep=lambda _seconds: None, **kwargs)
