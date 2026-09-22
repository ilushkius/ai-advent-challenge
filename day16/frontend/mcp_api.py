"""HTTP-часть фронтенда дня 16 для раздела «🔌 MCP».

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы MCP-домена: подключение к внешнему MCP-серверу,
статус соединения, отключение и список инструментов. Раздел интерфейса
(``frontend/mcp_section.py``) ходит в бэкенд лишь через эти четыре функции —
сам он соединение не открывает и не держит: подключение живёт в процессе
бэкенда, поэтому переживает перерисовку страницы Streamlit.

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
