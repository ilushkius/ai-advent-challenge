"""HTTP-часть фронтенда дня 21 для раздела «📦 Индексация».

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы индексации: запуск прогона, демо-сценарий, прогресс,
статистика, поиск, примеры чанков, история и очистка индекса.

Отдельный модуль, а не дополнение ``api_client``, по той же причине, что у
``mcp_api.py``, ``scheduler_api.py``, ``pipeline_api.py`` и
``orchestration_api.py``: ``api_client`` держит транспорт и девять доменов, туда
его 400 строк и не пускают.

Раздел интерфейса (``frontend/indexing_section.py``) ходит в бэкенд только через
эти функции. Прогон живёт в процессе бэкенда (и в фоновом потоке), поэтому
перерисовка страницы Streamlit его не прерывает: интерфейс лишь опрашивает статус.
"""
from .api_client import request_json


def api_indexing_run(strategy, background=True):
    """POST /indexing/run -> индексация одной стратегией (400 — неизвестная).

    ``background=True`` — ответ сразу с номером запуска, прогресс опрашивается
    через ``api_indexing_status``; ``background=False`` — прогон в этом же запросе,
    метрики приходят в ответе.
    """
    return request_json("POST", "/indexing/run",
                        json={"strategy": strategy, "background": background})


def api_indexing_demo(background=True):
    """POST /indexing/demo -> демо-сценарий: обе стратегии, запросы, сравнение."""
    return request_json("POST", "/indexing/demo", json={"background": background})


def api_indexing_status():
    """GET /indexing/status -> последний запуск (``run`` может быть ``None``)."""
    return request_json("GET", "/indexing/status")


def api_indexing_stats():
    """GET /indexing/stats -> статистика обеих стратегий (чанки, токены, файлы)."""
    return request_json("GET", "/indexing/stats")


def api_indexing_search(query, top_k=None, strategy=None):
    """GET /indexing/search -> попадания поиска (400 — запрос, 409 — пусто)."""
    params = {"query": query}
    if top_k:
        params["top_k"] = int(top_k)
    if strategy:
        params["strategy"] = strategy
    return request_json("GET", "/indexing/search", params=params)


def api_indexing_chunks(strategy, limit=None):
    """GET /indexing/chunks -> примеры чанков стратегии."""
    params = {"strategy": strategy}
    if limit:
        params["limit"] = int(limit)
    return request_json("GET", "/indexing/chunks", params=params)


def api_indexing_runs(limit=None):
    """GET /indexing/runs -> история запусков индексации."""
    params = {"limit": int(limit)} if limit else None
    return request_json("GET", "/indexing/runs", params=params)


def api_indexing_run_detail(run_id):
    """GET /indexing/runs/{run_id} -> запуск и его метрики (404 — нет такого)."""
    return request_json("GET", f"/indexing/runs/{int(run_id)}")


def api_indexing_clear(strategy):
    """POST /indexing/clear -> очистка индекса стратегии (``all`` — обеих)."""
    return request_json("POST", "/indexing/clear", json={"strategy": strategy})
