"""HTTP-часть фронтенда дня 20 для раздела «🔀 Пайплайны».

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы пайплайна: запуск, история запусков, отчёт о запуске,
его шаги и удаление.

Отдельный модуль, а не дополнение ``api_client``, по той же причине, что у
``mcp_api.py`` и ``scheduler_api.py``: ``api_client`` уже держит восемь доменов и
подошёл к лимиту 400 строк, а пайплайн стал девятым.

Раздел интерфейса (``frontend/pipeline_section.py``) ходит в бэкенд только через
эти функции. Запуск живёт в процессе бэкенда (и в фоновом потоке), поэтому
перерисовка страницы Streamlit его не прерывает: интерфейс лишь опрашивает статус.
"""
from .api_client import request_json


def api_pipeline_run(pipeline=None, initial_args=None, background=True):
    """POST /pipelines/run -> запуск пайплайна (400 — негодная конфигурация).

    ``pipeline=None`` означает встроенный пайплайн (search → summarize →
    save_to_file): декларация живёт в домене дня, интерфейс её не дублирует.
    """
    return request_json("POST", "/pipelines/run",
                        json={"pipeline": pipeline,
                              "initial_args": initial_args or {},
                              "background": background})


def api_pipeline_runs(status=None, limit=None):
    """GET /pipelines/runs -> история запусков (400 — неизвестный статус)."""
    params = {}
    if status:
        params["status"] = status
    if limit:
        params["limit"] = int(limit)
    return request_json("GET", "/pipelines/runs", params=params or None)


def api_pipeline_run_report(run_id):
    """GET /pipelines/runs/{run_id} -> запуск, его шаги, итог и ошибка (404 — нет)."""
    return request_json("GET", f"/pipelines/runs/{int(run_id)}")


def api_pipeline_run_steps(run_id):
    """GET /pipelines/runs/{run_id}/steps -> только шаги запуска (404 — нет)."""
    return request_json("GET", f"/pipelines/runs/{int(run_id)}/steps")


def api_pipeline_delete_run(run_id):
    """DELETE /pipelines/runs/{run_id} -> запуск удалён вместе с шагами (404 — нет)."""
    return request_json("DELETE", f"/pipelines/runs/{int(run_id)}")
