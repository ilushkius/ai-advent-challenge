"""HTTP-часть фронтенда дня 21 для вкладки «💰 Расходы».

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь только запросы раздела расходов: журнал `llm_usage`, состояние рычагов
экономии, прогноз и справка по моделям.

Отдельный модуль, а не дополнение ``api_client``, по той же причине, что у
``indexing_api.py`` и ``orchestration_api.py``: ``api_client`` держит транспорт и
девять доменов, ему нельзя добавлять десятый.

Вкладка (``frontend/cost_section.py``) ходит в бэкенд только через эти функции:
формулы стоимости живут в домене дня, и повторять их в интерфейсе нельзя.
"""
from .api_client import request_json


def api_llm_usage(agent_id=None, period=None, limit=None):
    """GET /llm/usage -> статистика расходов за период и последние запросы (400 — период)."""
    params = {}
    if agent_id:
        params["agent_id"] = agent_id
    if period:
        params["period"] = period
    if limit:
        params["limit"] = int(limit)
    return request_json("GET", "/llm/usage", params=params or None)


def api_llm_status():
    """GET /llm/status -> пик/непик, скидка, статистика кэша префиксов и сжатия."""
    return request_json("GET", "/llm/status")


def api_llm_models():
    """GET /llm/models -> таблица «тип задачи → модель» и тарифы."""
    return request_json("GET", "/llm/models")


def api_llm_peak():
    """GET /llm/peak -> правило непиковых окон и текущий статус."""
    return request_json("GET", "/llm/peak")


def api_llm_estimate(model, task_type, prompt_tokens, completion_tokens=0,
                     cache_hit_tokens=0, compressed_tokens=0,
                     max_response_tokens=0, off_peak_share=0.0):
    """POST /llm/estimate -> прогноз экономии по числам токенов."""
    return request_json("POST", "/llm/estimate", json={
        "model": model,
        "task_type": task_type,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "cache_hit_tokens": int(cache_hit_tokens),
        "compressed_tokens": int(compressed_tokens),
        "max_response_tokens": int(max_response_tokens),
        "off_peak_share": float(off_peak_share),
    })
