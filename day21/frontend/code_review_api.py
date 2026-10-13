"""HTTP-часть раздела «🔎 AI-ревью кода» (день 32).

Транспорт общий — ``frontend/api_client.py``; здесь четыре запроса дня 32: ревью
локального diff-а ``/review/pr``, ревью реального PR ``/review/github-pr`` и две
проверки готовности (``/review/health``, ``/review/github-health``).

Предел ожидания — ``LONG_TIMEOUT`` у обоих ревью: каждое идёт в модель (DeepSeek
отвечает десятками секунд, локальная Ollama — с прогревом весов дольше), а проверки
готовности отвечают мгновенно (GitHub-health — один запрос ``/rate_limit``) и
пользуются общим пределом.
"""
from .api_client import LONG_TIMEOUT, request_json


def api_review_pr(payload: dict) -> dict:
    """POST /review/pr -> ревью diff-а: находки, источники RAG и предупреждения."""
    return request_json("POST", "/review/pr", timeout=LONG_TIMEOUT, json=payload)


def api_review_github_pr(payload: dict) -> dict:
    """POST /review/github-pr -> ревью PR из GitHub и признак публикации комментария."""
    return request_json("POST", "/review/github-pr", timeout=LONG_TIMEOUT, json=payload)


def api_review_health() -> dict:
    """GET /review/health -> провайдер по умолчанию, инструменты MCP, предел diff-а."""
    return request_json("GET", "/review/health")


def api_review_github_health() -> dict:
    """GET /review/github-health -> доступность GitHub, токен маской и остаток лимита."""
    return request_json("GET", "/review/github-health")
