"""Фейки пайплайна для тестов дня 19.

MCP-фейки дня 17 (``mcp_fakes.py``) подменяют клиент, но возвращают один и тот же
``structured`` на любой вызов: пайплайну этого мало — его шаги ДОЛЖНЫ получать
разные ответы (поиск отдаёт элементы, сводка — текст, запись — файл), иначе
проверять маппинг ``$steps.<i>.structured.<поле>`` не на чем.

Отсюда два дополнения:

- ``PIPELINE_TOOL_CATALOG`` — каталог трёх инструментов композиции со схемами
  аргументов: по ним работают правила допуска (``required`` и типы), поэтому
  «items вместо массива» ловится тестом, а не сервером;
- ``FakePipelineClient`` — клиент, который отвечает ПО ИМЕНИ инструмента
  (``results``), а по ``errors`` отдаёт ответ с ``is_error`` — так проверяются обе
  ветки шага: успех и ошибка инструмента.
"""
import json

from backend.domain.mcp_target import MCPTransport
from backend.domain.mcp_tools import MCPToolInfo, MCPToolResult
from backend.services.mcp_client import MCPConnectionError
from backend.services.mcp_registry import MCPRegistry

from mcp_fakes import FakeMCPClient

#: Инструменты композиции со схемами аргументов и результата (день 19).
PIPELINE_TOOL_CATALOG = (
    MCPToolInfo(
        name="search",
        description="Поиск данных в источнике (день 19)",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"},
                           "source": {"type": "string"},
                           "limit": {"type": "integer"}},
            "required": ["query"],
        },
        output_schema={"type": "object",
                       "properties": {"count": {"type": "integer"},
                                      "items": {"type": "array"}}},
    ),
    MCPToolInfo(
        name="summarize",
        description="Сводка списка элементов (день 19)",
        input_schema={
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "object"}},
                           "style": {"type": "string"},
                           "max_length": {"type": "integer"}},
            "required": ["items"],
        },
        output_schema={"type": "object",
                       "properties": {"summary_text": {"type": "string"},
                                      "key_points": {"type": "array"}}},
    ),
    MCPToolInfo(
        name="save_to_file",
        description="Сохранение текста в файл (день 19)",
        input_schema={
            "type": "object",
            "properties": {"content": {"type": "string"},
                           "filename": {"type": "string"},
                           "format": {"type": "string"}},
            "required": ["content"],
        },
        output_schema={"type": "object",
                       "properties": {"filename": {"type": "string"},
                                      "size_bytes": {"type": "integer"}}},
    ),
)

#: Ответы фейковых инструментов: структура, которую видит следующий шаг пайплайна.
SEARCH_RESULT = {
    "query": "RAG",
    "source": "file:notes.md",
    "source_kind": "file",
    "count": 2,
    "items": [
        {"id": "file:notes.md#1", "title": "RAG: что это", "content": "RAG — поиск …",
         "url": "", "metadata": {"path": "notes.md", "block": 1}},
        {"id": "file:notes.md#2", "title": "Чанкинг", "content": "Чанкинг — нарезка …",
         "url": "", "metadata": {"path": "notes.md", "block": 2}},
    ],
}
SUMMARY_RESULT = {
    "summary_text": "Найдено 2 элементов. Первые: RAG: что это; Чанкинг",
    "key_points": ["RAG: что это", "Чанкинг"],
    "total_items": 2,
    "style_used": "short",
    "engine": "aggregation",
}
SAVED_RESULT = {
    "filename": "run.md",
    "filepath": "/tmp/run.md",
    "size_bytes": 64,
    "format": "md",
    "saved_at": "2026-09-24T00:00:00+00:00",
}

#: Ответы по умолчанию: ровно то, что отдают инструменты сервера дня.
PIPELINE_RESULTS = {
    "search": SEARCH_RESULT,
    "summarize": SUMMARY_RESULT,
    "save_to_file": SAVED_RESULT,
}

#: Ответ инструмента с ошибкой (стиль, которого нет у ``summarize``).
STYLE_ERROR = "Стиль «exotic» не поддержан. Допустимы: short, detailed, bullets"


class FakePipelineClient(FakeMCPClient):
    """MCP-клиент, отвечающий по имени инструмента (``results``/``errors``).

    ``results`` — структура ответа для имени инструмента, ``errors`` — текст ошибки
    для имени: инструмент возвращает ``is_error=True``. Так проверяются обе ветки
    шага пайплайна без настоящего сервера, а каталог с реальными схемами
    (``PIPELINE_TOOL_CATALOG``) оставляет в игре правила допуска.
    """

    def __init__(self, *args, results=None, errors=None, **kwargs):
        super().__init__(*args, tools=PIPELINE_TOOL_CATALOG, **kwargs)
        self.results = dict(PIPELINE_RESULTS if results is None else results)
        self.errors = dict(errors or {})

    def call_tool(self, tool_name: str, arguments=None):
        """Ответ по имени инструмента: ошибка, если она задана, иначе структура."""
        if not self.connected:
            return super().call_tool(tool_name, arguments)
        args = dict(arguments or {})
        self.call_calls.append({"tool": tool_name, "arguments": args})
        if self._call_fail:
            raise MCPConnectionError(self._call_fail)
        if tool_name in self.errors:
            return MCPToolResult(tool=tool_name, arguments=args,
                                 text=self.errors[tool_name], is_error=True,
                                 duration_ms=1)
        structured = self.results.get(tool_name, {"tool": tool_name, **args})
        return MCPToolResult(tool=tool_name, arguments=args, structured=structured,
                             text=json.dumps(structured, ensure_ascii=False),
                             duration_ms=1)

def make_pipeline_factory(**client_kwargs):
    """Фабрика фейковых клиентов композиции: ``factory.created`` — все экземпляры."""
    created: list[FakePipelineClient] = []

    def factory(target, *, transport=MCPTransport.AUTO, timeout=None, cwd=None):
        # ``cwd`` принимается и игнорируется: реестр зовёт фабрику и как фабрику
        # флота серверов (день 20), где рабочий каталог есть у настоящего клиента.
        client = FakePipelineClient(target, transport=transport, timeout=timeout,
                                    **client_kwargs)
        created.append(client)
        return client

    factory.created = created
    return factory


def make_pipeline_registry(**client_kwargs) -> MCPRegistry:
    """Реестр на фейковых клиентах композиции (каталог — три инструмента дня 19)."""
    return MCPRegistry(client_factory=make_pipeline_factory(**client_kwargs))
