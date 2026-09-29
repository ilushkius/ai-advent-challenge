"""HTTP-часть фронтенда дня 22 для режима RAG.

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы RAG: ответ по корпусу (с контекстом и без него),
сравнение двух ответов на один вопрос и состояние корпуса с лимитами режима.

Отдельный модуль, а не дополнение ``api_client``, по той же причине, что у
``indexing_api.py``, ``mcp_api.py`` и ``cost_api.py``: ``api_client`` держит
транспорт и девять доменов, туда его 400 строк и не пускают.

Панель чата и раздел сравнения (``frontend/rag_section.py``) ходят в бэкенд только
через эти функции: правила поиска и сборки промпта живут на бэкенде.
"""
from .api_client import request_json


def api_rag_query(question, top_k=None, strategy=None, use_rag=True):
    """POST /rag/query -> ответ по корпусу (``use_rag``) или ответ без контекста.

    400 — пустой вопрос и неизвестная стратегия, 409 — корпус не проиндексирован,
    502 — сбой вызова модели, когда откат на ответ без RAG тоже не удался.
    """
    payload = {"question": question, "use_rag": bool(use_rag)}
    if top_k:
        payload["top_k"] = int(top_k)
    if strategy:
        payload["strategy"] = strategy
    return request_json("POST", "/rag/query", json=payload)


def api_rag_compare(question, top_k=None, strategy=None):
    """POST /rag/compare -> оба ответа на один вопрос: сначала без RAG, затем с ним."""
    payload = {"question": question}
    if top_k:
        payload["top_k"] = int(top_k)
    if strategy:
        payload["strategy"] = strategy
    return request_json("POST", "/rag/compare", json=payload)


def api_rag_config():
    """GET /rag/config -> готовность корпуса, чанки стратегий и лимиты режима."""
    return request_json("GET", "/rag/config")
