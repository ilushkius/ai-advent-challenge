"""HTTP-часть фронтенда дня 17 для раздела «🔌 MCP».

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы MCP-домена: подключение к MCP-серверу, статус
соединения, отключение, список инструментов, вызов инструмента и каталог
известных серверов. Разделы интерфейса (``frontend/mcp_section.py``,
``mcp_call.py``, ``mcp_ask.py``) ходят в бэкенд лишь через эти функции — сами они
соединение не открывают и не держат: подключение живёт в процессе бэкенда,
поэтому переживает перерисовку страницы Streamlit.

Модуль вынесен отдельно, потому что ``api_client.py`` уже держит пять доменов
(агенты, контекст, память, профили, задачи, инварианты) и подошёл к лимиту
400 строк — MCP-запросы стали его седьмым доменом.
"""
from .api_client import request_json


def api_mcp_status():
    """GET /mcp/status -> состояние подключения, сервер, число инструментов."""
    return request_json("GET", "/mcp/status")


def api_mcp_connect(target, transport="auto"):
    """POST /mcp/connect -> статус после подключения (400 — цель, 502 — сервер)."""
    return request_json("POST", "/mcp/connect",
                        json={"target": target, "transport": transport})


def api_mcp_disconnect():
    """POST /mcp/disconnect -> статус после закрытия соединения."""
    return request_json("POST", "/mcp/disconnect", json={})


def api_mcp_tools(refresh=False):
    """GET /mcp/tools -> {"tools", "count", ...} (409 — нет соединения)."""
    return request_json("GET", "/mcp/tools", params={"refresh": refresh})


def api_mcp_call(tool, arguments):
    """POST /mcp/call -> исход вызова (400/409 — отказ, 502 — сбой связи).

    Ошибка самого инструмента приходит с кодом 200 и ``is_error: true`` —
    это ответ, а не BackendError: показывать её нужно результатом вызова.
    """
    return request_json("POST", "/mcp/call",
                        json={"tool": tool, "arguments": arguments})


def api_mcp_servers():
    """GET /mcp/servers -> состав ФЛОТА серверов и состояние их подключений.

    Соединений у процесса столько, сколько серверов в ``mcp_servers.json``,
    поэтому ``connected`` здесь — свойство сервера, а не «какой из них выбран».
    """
    return request_json("GET", "/mcp/servers")
