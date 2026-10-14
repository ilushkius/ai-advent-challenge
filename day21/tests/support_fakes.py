"""Фейки ассистента поддержки (день 33) для юнит-тестов службы.

Живут отдельным модулем, потому что фейков два набора: служба (контекст трёх
источников, отказы инструментов и ответы модели) и соединение со stdio-сервером
поддержки (ленивое подключение и закрытие). Держать их в тестовом файле нельзя — он
не должен расти от каждого нового случая.

Настоящие зависимости здесь не участвуют: индекс — фейк (отдаёт заданные попадания
или падает), MCP-клиент — фейк (пишет вызовы, отдаёт результат по имени инструмента,
умеет «запись не найдена»), модель — ``RagStubClient`` из ``tests/rag_fakes.py``.
Поэтому тесты службы идут офлайн, а настоящий корпус и настоящий процесс
``support_server`` проверяет slow-интеграция (``tests/integration/test_support_flow.py``).

Формы ответов фейков повторяют схемы сервера поддержки
(``mcp_servers/support_server/schemas.py``): найденная запись приходит с пустым
``error``, ненайденная — с заполненными пустыми значениями и ``error="not found"``.
"""
from __future__ import annotations

from backend.domain import support
from backend.domain.mcp_tools import MCPToolResult, make_tool_info
from backend.services.mcp_errors import MCPConnectionError
from backend.services.support_service import SupportService

#: Профиль клиента: то, что видит служба в ``structuredContent`` инструмента.
USER_STRUCTURED = {
    "id": "user_003",
    "name": "Мария Кузнецова",
    "email": "m.kuznetsova@example.com",
    "plan": "pro",
    "registered_at": "2026-05-21",
    "last_seen": "2026-10-14",
    "error": "",
}

#: Тикет с историей из трёх сообщений: тема, статус и приоритет видны в ответе.
TICKET_STRUCTURED = {
    "id": "ticket_007",
    "user_id": "user_003",
    "subject": "Не работает авторизация",
    "status": "open",
    "priority": "high",
    "created_at": "2026-10-06T08:45:00",
    "messages": [
        {"author": "user", "text": "С утра не могу войти: возвращает на форму.",
         "timestamp": "2026-10-06T08:45:00"},
        {"author": "support", "text": "Так выглядит истёкший токен сессии.",
         "timestamp": "2026-10-06T09:30:00"},
        {"author": "user", "text": "Да, вчера меняла пароль после письма.",
         "timestamp": "2026-10-06T10:02:00"},
    ],
    "error": "",
}

#: Раздел продукта: форма ответа ``get_product_info`` (область подставляется вызовом).
PRODUCT_STRUCTURED = {
    "area": support.AREA_AUTH,
    "title": support.AREA_LABELS[support.AREA_AUTH],
    "description": "Вход по email и паролю, токен доступа и токен обновления.",
    "faq": ["Как сменить пароль?", "Что делать, если токен сессии истёк?"],
    "error": "",
}

#: Тикеты клиента в списке: ``messages`` — число сообщений, истории здесь нет.
TICKETS_STRUCTURED = {
    "user_id": "user_003",
    "count": 2,
    "tickets": [
        {"id": "ticket_007", "subject": "Не работает авторизация", "status": "open",
         "priority": "high", "created_at": "2026-10-06T08:45:00", "messages": 3},
        {"id": "ticket_009", "subject": "Не приходит код подтверждения по SMS",
         "status": "open", "priority": "normal", "created_at": "2026-10-09T13:40:00",
         "messages": 2},
    ],
    "error": "",
}

#: Каталог клиентов: селектор пользователей раздела строится из него.
USERS_STRUCTURED = {
    "count": 2,
    "users": [
        USER_STRUCTURED,
        {"id": "user_001", "name": "Анна Смирнова", "email": "a.smirnova@example.com",
         "plan": "free", "registered_at": "2026-02-14", "last_seen": "2026-10-12",
         "error": ""},
    ],
    "error": "",
}

#: Ответы фейкового сервера по именам инструментов. Раздела продукта здесь нет: его
#: фейк собирает по запрошенной области (как настоящий сервер), см. ``product_result``.
TOOL_RESULTS = {
    support.TOOL_GET_USER: USER_STRUCTURED,
    support.TOOL_GET_TICKET: TICKET_STRUCTURED,
    support.TOOL_LIST_USER_TICKETS: TICKETS_STRUCTURED,
    support.TOOL_LIST_USERS: USERS_STRUCTURED,
}

#: Два канонических фрагмента документации поддержки: текст попадает в промпт,
#: поэтому он ищется в сообщениях заглушки — так проверяется, что контекст доехал.
HITS = [
    {"chunk_id": "c-1", "source": "day21-docs-support-faq.md", "title": "FAQ",
     "section": "Как сменить тариф?", "score": 0.83,
     "content": "Смена тарифа — «Настройки → Тарифы»."},
    {"chunk_id": "c-2", "source": "day21-docs-support-troubleshooting.md",
     "title": "Разборы симптомов", "section": "Не работает вход", "score": 0.61,
     "content": "Токен сессии истёк: очистите cookies и войдите заново."},
]


def product_result(area: str) -> dict:
    """Ответ ``get_product_info`` по запрошенной области.

    Фейк повторяет поведение сервера: раздел продукта зависит от аргумента, иначе
    проверка «область вопроса определилась верно» ничего не проверяла бы.
    """
    return {**PRODUCT_STRUCTURED, "area": area,
            "title": support.AREA_LABELS.get(area, area)}


def not_found_result(name: str, arguments: dict) -> dict:
    """Ответ инструмента с ненайденной записью: пустые поля и ``error``.

    Служба различает «инструмент ответил, но записи нет» и «инструмент упал»: первое
    приходит данными (как у настоящего сервера), второе — флагом ``is_error``.
    """
    if name == support.TOOL_GET_USER:
        return {**USER_STRUCTURED, "id": str(arguments.get("user_id") or ""), "name": "",
                "email": "", "plan": "", "registered_at": "", "last_seen": "",
                "error": "not found"}
    if name == support.TOOL_GET_TICKET:
        return {**TICKET_STRUCTURED, "id": str(arguments.get("ticket_id") or ""),
                "user_id": "", "subject": "", "status": "", "priority": "",
                "created_at": "", "messages": [], "error": "not found"}
    if name == support.TOOL_LIST_USER_TICKETS:
        return {"user_id": str(arguments.get("user_id") or ""), "count": 0,
                "tickets": [], "error": "not found"}
    if name == support.TOOL_GET_PRODUCT_INFO:
        return {**PRODUCT_STRUCTURED, "area": str(arguments.get("product_area") or ""),
                "title": "", "description": "", "faq": [], "error": "not found"}
    return {"count": 0, "users": [], "error": "not found"}


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
    """MCP-клиент поддержки без транспорта: пишет вызовы и отдаёт результат по имени."""

    def __init__(self, error: Exception | None = None, tool_error: str = "",
                 results=None, tools=None, not_found=(), empty_tools=()) -> None:
        self.error = error
        self.tool_error = tool_error
        self.results = dict(TOOL_RESULTS if results is None else results)
        self.calls: list = []
        self.connected = True
        self.closed = False
        #: Инструменты, вернувшие «запись не найдена» (данные, а не ошибка вызова).
        self.not_found = tuple(not_found)
        #: Инструменты, вернувшие пустой ответ: ни структуры, ни текста.
        self.empty_tools = tuple(empty_tools)
        self._tools = [make_tool_info(name, f"Инструмент {name}")
                       for name in (support.TOOLS if tools is None else tools)]

    def list_tools(self, *, refresh: bool = False):
        return list(self._tools)

    def call_tool(self, name: str, arguments=None):
        call = dict(arguments or {})
        self.calls.append((name, call))
        if self.error is not None:
            raise self.error
        if self.tool_error:
            return MCPToolResult(tool=name, arguments=call, text=self.tool_error,
                                 is_error=True, duration_ms=3)
        if name in self.not_found:
            return MCPToolResult(tool=name, arguments=call,
                                 structured=not_found_result(name, call),
                                 text="not found", duration_ms=2)
        if name in self.empty_tools:
            return MCPToolResult(tool=name, arguments=call, structured=None, text="",
                                 duration_ms=1)
        result = self.results.get(name)
        if result is None and name == support.TOOL_GET_PRODUCT_INFO:
            result = product_result(str(call.get("product_area") or ""))
        if result is None:
            return MCPToolResult(tool=name, arguments=call, structured=None,
                                 text="текст без структуры", duration_ms=2)
        if isinstance(result, str):
            return MCPToolResult(tool=name, arguments=call,
                                 structured={"result": result}, text=result, duration_ms=2)
        return MCPToolResult(tool=name, arguments=call, structured=result, text="ok",
                             duration_ms=2)

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
        return [make_tool_info(name, f"Инструмент {name}") for name in support.TOOLS]

    def call_tool(self, name: str, arguments=None):
        call = dict(arguments or {})
        self.calls.append((name, call))
        return MCPToolResult(tool=name, arguments=call, structured=dict(USER_STRUCTURED),
                             text="ok", duration_ms=1)

    def close(self) -> None:
        self.closed = True


class FailingStdioClient(FakeStdioClient):
    """Подмена ``MCPClient``, у которой сервер не поднимается (нет процесса/команды)."""

    def connect(self):
        raise MCPConnectionError("сервер не отвечает")


def make_service(*, index=None, mcp=None, client=None, **kwargs) -> SupportService:
    """Служба на фейках: подставленные зависимости вместо служб процесса."""
    return SupportService(index_service=index if index is not None else FakeIndexService(),
                          mcp_client=mcp if mcp is not None else FakeMCP(),
                          llm_client=client, sleep=lambda _seconds: None, **kwargs)
