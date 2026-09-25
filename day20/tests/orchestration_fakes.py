"""Фейковый ФЛОТ MCP-серверов и его каталоги для тестов дня 20.

Отличие от ``tests/mcp_fakes.py`` (день 17) в том, что здесь фейк отвечает за
НЕСКОЛЬКО серверов сразу: каталог и ответы инструмента выбираются по имени сервера
в цели подключения. Так проверяются маршрутизация (какой сервер получил вызов),
журнал шагов с колонкой ``server_name`` и сценарий «добавили сервер — код не
менялся».

Файл конфигурации флота пишется во временный каталог (``write_servers_file``):
реестр читает его как обычный ``mcp_servers.json``, поэтому тест проверяет и разбор
конфигурации, и запись кэша инструментов обратно в файл.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from backend.domain.mcp_target import MCPTransport
from backend.domain.mcp_tools import MCPToolInfo, MCPToolResult
from backend.services.mcp_registry import MCPRegistry

from mcp_fakes import FakeMCPClient


def _tool(name: str, description: str, properties: Mapping[str, Any],
          required: Sequence[str], output: Sequence[str] = ()) -> MCPToolInfo:
    """Инструмент с настоящими ``input_schema``/``output_schema`` (как у сервера).

    Схемы важны не для красоты: правила допуска (``admission_reason``) сверяют по
    ним аргументы, поэтому фейк без схем пропустил бы то, что настоящий сервер
    отверг бы (например, лишний ``max_length`` у ``summarize``).
    """
    return MCPToolInfo(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": dict(properties),
                      "required": list(required)},
        output_schema={"type": "object",
                       "properties": {key: {} for key in output}},
    )


#: Каталог флота: 3 инструмента поиска, 4 обработки, 4 хранения — 11 всего.
FLEET_CATALOGS: dict[str, tuple[MCPToolInfo, ...]] = {
    "search_server": (
        _tool("search_web", "Поиск в ленте jsonplaceholder или в Википедии",
              {"query": {"type": "string"}, "source": {"type": "string"},
               "limit": {"type": "integer"}}, ["query"],
              ("query", "source", "source_kind", "count", "items")),
        _tool("search_local", "Поиск по файлу внутри папки дня",
              {"query": {"type": "string"}, "path": {"type": "string"},
               "limit": {"type": "integer"}}, ["query"],
              ("query", "path", "count", "items")),
        _tool("fetch_url", "Страница по HTTP → текст",
              {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, ["url"],
              ("url", "status", "content_type", "chars", "truncated", "text")),
    ),
    "data_server": (
        _tool("summarize", "Сводка списка элементов и ключевые пункты",
              {"items": {"type": "array"}, "style": {"type": "string"},
               "max_length": {"type": "integer"}}, ["items"],
              ("summary_text", "key_points", "total_items", "style_used", "engine")),
        _tool("extract_keywords", "Ключевые слова текста",
              {"text": {"type": "string"}, "limit": {"type": "integer"}}, ["text"],
              ("keywords", "count", "joined", "engine")),
        _tool("filter_by_date", "Отбор записей по дате",
              {"items": {"type": "array"}, "field": {"type": "string"},
               "since": {"type": "string"}, "until": {"type": "string"},
               "limit": {"type": "integer"}}, ["items"],
              ("items", "count", "skipped", "field", "since", "until")),
        _tool("aggregate", "Агрегация записей по группам",
              {"items": {"type": "array"}, "group_by": {"type": "string"},
               "metric": {"type": "string"}, "value_field": {"type": "string"},
               "limit": {"type": "integer"}}, ["items"],
              ("groups", "count", "metric", "group_by")),
    ),
    "storage_server": (
        _tool("save_to_file", "Запись текста в файл каталога output/",
              {"content": {"type": "string"}, "filename": {"type": "string"},
               "format": {"type": "string"}}, ["content"],
              ("filename", "filepath", "size_bytes", "format", "saved_at")),
        _tool("save_to_db", "Строка в базу дня (storage.db)",
              {"kind": {"type": "string"}, "title": {"type": "string"},
               "content": {"type": "string"}, "source": {"type": "string"},
               "metadata": {"type": "object"}}, ["kind", "title", "content"],
              ("row_id", "kind", "title", "source", "size_bytes", "created_at")),
        _tool("list_saved", "Что уже сохранено: файлы и строки базы",
              {"kind": {"type": "string"}, "limit": {"type": "integer"}}, [],
              ("files", "rows", "count", "kind")),
        _tool("load_from_file", "Прочитать сохранённый файл",
              {"filename": {"type": "string"}}, ["filename"],
              ("filename", "filepath", "chars", "format", "text")),
    ),
}

#: Инструмент четвёртого сервера (сценарий «добавили сервер, код не менялся»).
ECHO_CATALOG: tuple[MCPToolInfo, ...] = (
    _tool("echo", "Возвращает переданный текст",
          {"text": {"type": "string"}}, [], ("text",)),
)

#: Ответы инструментов флота: то, что «вернул» бы настоящий сервер.
FLEET_RESULTS: dict[str, dict[str, Any]] = {
    "search_web": {
        "query": "", "source": "posts", "source_kind": "api", "count": 2,
        "items": [
            {"id": "post:1", "title": "Post 1", "content": "Body of post 1",
             "url": "https://example.test/posts/1", "metadata": {"source": "posts"}},
            {"id": "post:2", "title": "Post 2", "content": "Body of post 2",
             "url": "https://example.test/posts/2", "metadata": {"source": "posts"}},
        ],
    },
    "search_local": {
        "query": "RAG", "path": "mcp_server/data/notes.md", "count": 1,
        "items": [{"id": "file:mcp_server/data/notes.md#1", "title": "RAG",
                   "content": "RAG — генерация с опорой на найденные фрагменты",
                   "url": "", "metadata": {"path": "mcp_server/data/notes.md",
                                           "block": "1"}}],
    },
    "fetch_url": {"url": "https://example.test", "status": 200,
                  "content_type": "text/plain", "chars": 12, "truncated": False,
                  "text": "пример текста"},
    "summarize": {"summary_text": "Найдено 2 элементов. Первые: Post 1; Post 2",
                  "key_points": ["Post 1", "Post 2"], "total_items": 2,
                  "style_used": "short", "engine": "aggregation"},
    "extract_keywords": {"keywords": ["post", "body"], "count": 2,
                         "joined": "post, body", "engine": "frequency"},
    "filter_by_date": {"items": [{"id": 1, "created_at": "2026-01-01"}], "count": 1,
                       "skipped": 0, "field": "created_at", "since": "", "until": ""},
    "aggregate": {"groups": [{"key": "все", "value": 2}], "count": 1,
                  "metric": "count", "group_by": ""},
    "save_to_file": {"filename": "demo-scenario.md",
                     "filepath": "/tmp/output/demo-scenario.md", "size_bytes": 120,
                     "format": "md", "saved_at": "2026-01-01T00:00:00+00:00"},
    "save_to_db": {"row_id": 7, "kind": "orchestration", "title": "запрос",
                   "source": "search_web", "size_bytes": 120,
                   "created_at": "2026-01-01T00:00:00+00:00"},
    "list_saved": {"files": [], "rows": [], "count": 0, "kind": "all"},
    "load_from_file": {"filename": "demo-scenario.md",
                       "filepath": "/tmp/output/demo-scenario.md", "chars": 120,
                       "format": "md", "text": "Сводка"},
    "echo": {"text": "эхо"},
}


class FakeFleetClient(FakeMCPClient):
    """Клиент одного сервера флота: каталог и ответы — по имени сервера в цели.

    Настоящая FSM подключения (наследуется) и запись вызовов в ``call_calls``: по
    ней видно, что вызов ушёл именно тому серверу, который объявляет инструмент.
    """

    def __init__(self, target, *, transport=MCPTransport.AUTO, timeout=None,
                 cwd=None, catalogs=None, results=None, error=None,
                 tool_errors=None):
        text = str(target)
        self.server_name = next(
            (name for name in (catalogs or FLEET_CATALOGS) if name in text), ""
        )
        if not self.server_name:
            raise AssertionError(f"Цель {text!r} не называет ни одного сервера флота")
        super().__init__(target, transport=transport, timeout=timeout, fail=error)
        self._tools = tuple((catalogs or FLEET_CATALOGS)[self.server_name])
        self._results = dict(results or FLEET_RESULTS)
        self._tool_errors = dict(tool_errors or {})

    def call_tool(self, tool_name: str, arguments=None) -> MCPToolResult:
        """Фейковый ``tools/call``: ответ берётся из ``FLEET_RESULTS``."""
        if not self.connected:
            from backend.services.mcp_client import MCPNotConnectedError

            raise MCPNotConnectedError(
                f"Соединение с MCP-сервером не установлено (состояние {self.state.value})"
            )
        args = dict(arguments or {})
        self.call_calls.append({"server": self.server_name, "tool": tool_name,
                                "arguments": args})
        failure = self._tool_errors.get(tool_name)
        if failure:
            # Ошибка инструмента — это ДАННЫЕ ответа (``is_error``), как у настоящего
            # сервера: прогон обязан остановиться, но не исключением.
            return MCPToolResult(tool=tool_name, arguments=args, text=failure,
                                 is_error=True, duration_ms=1)
        payload = self._results.get(tool_name, {"tool": tool_name, **args})
        return MCPToolResult(
            tool=tool_name, arguments=args, structured=payload,
            text=json.dumps(payload, ensure_ascii=False), duration_ms=3,
        )


def make_fleet_factory(catalogs: Mapping[str, tuple[MCPToolInfo, ...]] | None = None,
                       results: Mapping[str, dict[str, Any]] | None = None,
                       errors: Mapping[str, str] | None = None,
                       tool_errors: Mapping[str, str] | None = None):
    """Фабрика фейковых клиентов флота: ``factory.created`` — все экземпляры.

    ``errors`` задаёт серверы, которые «не поднимаются» (текст ошибки подключения):
    так проверяется, что сбой одного сервера не мешает остальным и попадает в
    запись ``error`` его сервера. ``tool_errors`` задаёт инструменты, которые
    отвечают ошибкой (``isError``): так проверяется остановка прогона на шаге.
    """
    created: list[FakeFleetClient] = []
    failures = dict(errors or {})
    broken = dict(tool_errors or {})

    def factory(spec, *, transport=MCPTransport.AUTO, timeout=None, cwd=None):
        client = FakeFleetClient(
            spec.target, transport=transport, timeout=timeout, cwd=cwd,
            catalogs=catalogs, results=results, error=failures.get(spec.name),
            tool_errors=broken,
        )
        created.append(client)
        return client

    factory.created = created
    factory.by_server = lambda name: next(
        (item for item in created if item.server_name == name), None
    )
    return factory


def write_servers_file(path, names: Iterable[str] = tuple(FLEET_CATALOGS),
                       extra: Sequence[dict[str, Any]] = ()) -> Path:
    """Пишет временный ``mcp_servers.json``: по записи на сервер плюс ``extra``.

    Команда запуска — ``uv run python mcp_servers/<имя>/server.py``: относительный
    путь от корня дня, как в настоящем файле, поэтому проверяется и разбор цели, и
    подстановка ``cwd``.
    """
    file = Path(path)
    servers = [
        {"name": name, "command": "uv",
         "args": ["run", "python", f"mcp_servers/{name}/server.py"],
         "description": f"Фейковый сервер {name}", "tools_cache": []}
        for name in names
    ]
    servers.extend(dict(record) for record in extra)
    file.write_text(json.dumps({"servers": servers}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return file


def make_fleet_registry(tmp_path, *, factory=None, catalogs=None, results=None,
                        errors=None, tool_errors=None, servers_file=None, names=None,
                        extra=(), **kwargs) -> MCPRegistry:
    """Реестр на фейковом флоте: файл конфигурации и фабрика — временные.

    Файл конфигурации лежит во временном каталоге, поэтому тест не трогает рабочий
    ``day20/mcp_servers.json``, а запись кэша инструментов проверяется чтением
    именно этого файла.
    """
    path = Path(servers_file) if servers_file else write_servers_file(
        Path(tmp_path) / "mcp_servers.json",
        names=tuple(catalogs or FLEET_CATALOGS) if names is None else names,
        extra=extra,
    )
    return MCPRegistry(
        fleet_factory=factory or make_fleet_factory(catalogs=catalogs, results=results,
                                                    errors=errors,
                                                    tool_errors=tool_errors),
        servers_file=path,
        cwd=str(tmp_path),
        **kwargs,
    )
