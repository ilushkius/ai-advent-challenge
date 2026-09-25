"""HTTP-часть фронтенда дня 20 для раздела «🌐 Оркестрация» и флота серверов.

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы оркестрации (запуск, демо-сценарий, история, отчёт о
запуске, его шаги, удаление) и запросы флота MCP-серверов (состав, инструменты
одного сервера, обновление кэша).

Отдельный модуль, а не дополнение ``api_client``: тот держит уже десять доменов и
подошёл к лимиту 400 строк.

Раздел интерфейса (``frontend/orchestration_section.py`` и ``frontend/mcp_call.py``)
ходит в бэкенд только через эти функции. Прогон живёт в процессе бэкенда,
поэтому перерисовка страницы Streamlit его не прерывает: интерфейс опрашивает
статус и показывает след прогона из журнала.
"""
from .api_client import request_json


def api_orchestration_run(query, background=True, plan=None, initial_args=None):
    """POST /orchestration/run -> запуск по реплике (400 — негодный план).

    ``plan=None`` означает «план построй сам»: его предложит модель по каталогу
    флота, а без ключа — эвристика дня. Интерфейс второй копии плана не держит.
    """
    return request_json("POST", "/orchestration/run",
                        json={"query": query, "plan": plan,
                              "initial_args": initial_args or {},
                              "background": background})


def api_orchestration_demo(background=True, initial_args=None):
    """POST /orchestration/demo -> демо-сценарий одной кнопкой (400 — пустой флот)."""
    return request_json("POST", "/orchestration/demo",
                        json={"background": background,
                              "initial_args": initial_args or {}})


def api_orchestration_runs(status=None, limit=None):
    """GET /orchestration/runs -> история запусков плюс статистика (400 — статус)."""
    params = {}
    if status:
        params["status"] = status
    if limit:
        params["limit"] = int(limit)
    return request_json("GET", "/orchestration/runs", params=params or None)


def api_orchestration_run_report(run_id):
    """GET /orchestration/runs/{run_id} -> запуск, шаги, серверы и итог (404 — нет)."""
    return request_json("GET", f"/orchestration/runs/{int(run_id)}")


def api_orchestration_run_steps(run_id):
    """GET /orchestration/runs/{run_id}/steps -> только шаги запуска (404 — нет)."""
    return request_json("GET", f"/orchestration/runs/{int(run_id)}/steps")


def api_orchestration_delete_run(run_id):
    """DELETE /orchestration/runs/{run_id} -> запуск удалён вместе с шагами (404 — нет)."""
    return request_json("DELETE", f"/orchestration/runs/{int(run_id)}")


def api_mcp_fleet():
    """GET /mcp/servers -> состав флота: серверы, их инструменты и состояние."""
    return request_json("GET", "/mcp/servers")


def api_mcp_server_tools(name):
    """GET /mcp/servers/{name}/tools -> инструменты сервера флота (404 — нет сервера)."""
    return request_json("GET", f"/mcp/servers/{name}/tools")


def api_mcp_servers_refresh():
    """POST /mcp/servers/refresh -> перечитать каталоги флота и записать кэш в файл."""
    return request_json("POST", "/mcp/servers/refresh", json={})
