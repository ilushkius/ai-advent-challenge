"""HTTP-часть фронтенда дня 22 для режима RAG.

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы RAG: ответ по корпусу (с контекстом и без него),
сравнение двух ответов на один вопрос, сравнение режимов отбора (день 23),
состояние корпуса с лимитами режима, демо-сценарий дня 24 (контрольные вопросы и
их прогон с источниками, цитатами и режимом «не знаю») и сравнение провайдеров дня
28 (тот же вопрос — на локальной модели Ollama и на облаке DeepSeek).

Отдельный модуль, а не дополнение ``api_client``, по той же причине, что у
``indexing_api.py``, ``mcp_api.py`` и ``cost_api.py``: ``api_client`` держит
транспорт и девять доменов, туда его 400 строк и не пускают.

Панель чата и раздел сравнения (``frontend/rag_section.py``) ходят в бэкенд только
через эти функции: правила поиска и сборки промпта живут на бэкенде.
"""
from backend.domain.llm_provider import PROVIDER_LOCAL

from .api_client import LONG_TIMEOUT, request_json


def api_rag_query(question, top_k=None, strategy=None, use_rag=True, rewrite=False,
                  rerank=False, min_score=None, top_k_candidates=None, provider=None):
    """POST /rag/query -> ответ по корпусу (``use_rag``) или ответ без контекста.

    ``rewrite``/``rerank`` — ступени отбора дня 23: переформулировка вопроса моделью
    и пересортировка кандидатов кросс-энкодером; ``min_score`` — порог отсечения,
    ``top_k_candidates`` — сколько кандидатов запросить у поиска. Нулевой порог и
    пустой ``top_k_candidates`` не отправляются: это значения дня 22 по умолчанию.

    ``provider`` (день 26) — кто отвечает: ``deepseek`` или ``local``; для локальной
    модели предел ожидания длиннее (первый запрос грузит веса в память).

    400 — пустой вопрос, неизвестная стратегия, неизвестный режим и незнакомый
    провайдер, 422 — порог вне диапазона, 409 — корпус не проиндексирован, 502 —
    сбой вызова модели, когда откат на ответ без RAG тоже не удался.
    """
    payload = {"question": question, "use_rag": bool(use_rag),
               "rewrite": bool(rewrite), "rerank": bool(rerank)}
    if top_k:
        payload["top_k"] = int(top_k)
    if strategy:
        payload["strategy"] = strategy
    if min_score not in (None, 0):
        payload["min_score"] = float(min_score)
    if top_k_candidates:
        payload["top_k_candidates"] = int(top_k_candidates)
    if provider:
        payload["provider"] = provider
    return request_json("POST", "/rag/query", json=payload,
                        timeout=LONG_TIMEOUT if provider == PROVIDER_LOCAL else None)


def api_rag_compare(question, top_k=None, strategy=None):
    """POST /rag/compare -> оба ответа на один вопрос: сначала без RAG, затем с ним."""
    payload = {"question": question}
    if top_k:
        payload["top_k"] = int(top_k)
    if strategy:
        payload["strategy"] = strategy
    return request_json("POST", "/rag/compare", json=payload)


def api_rag_compare_modes(question, top_k=None, strategy=None, modes=None, min_score=None,
                          top_k_candidates=None):
    """POST /rag/compare_modes -> ответы каждого режима отбора на один вопрос.

    Режимы приходят списком имён (``baseline``/``rewrite``/``rerank``/
    ``rerank_filter``); неизвестные имена бэкенд отбрасывает, а если не осталось ни
    одного — отвечает 400 ``bad_mode``. Поле ``modes`` в ответе содержит по записи
    на режим: ``mode``, ``label`` и ``result`` формы ``RagQueryOut``.
    """
    payload = {"question": question}
    if top_k:
        payload["top_k"] = int(top_k)
    if strategy:
        payload["strategy"] = strategy
    if modes:
        payload["modes"] = list(modes)
    if min_score not in (None, 0):
        payload["min_score"] = float(min_score)
    if top_k_candidates:
        payload["top_k_candidates"] = int(top_k_candidates)
    return request_json("POST", "/rag/compare_modes", json=payload)


def api_rag_config():
    """GET /rag/config -> готовность корпуса, чанки стратегий и лимиты режима."""
    return request_json("GET", "/rag/config")


def api_rag_demo_questions():
    """GET /rag/demo-questions -> контрольные вопросы демо-сценария (день 24)."""
    return request_json("GET", "/rag/demo-questions")


def api_rag_demo_run(question=None):
    """POST /rag/demo-run -> прогон демо: все вопросы или один (пустое тело — все).

    Ответ: ``rows`` (вопрос, режим, ответ, источники, цитаты, вердикт) и ``summary``
    (распределение режимов и вердиктов). Сбой одного вопроса приходит строкой с
    вердиктом «ошибка модели», а не отказом всего прогона.
    """
    return request_json("POST", "/rag/demo-run",
                        json={"question": question} if question else {})


def api_rag_compare_providers(questions=None, top_k=None, strategy=None):
    """POST /rag/compare_providers -> ответы локальной и облачной модели на вопросы.

    Тело: ``questions`` (список текстов; пусто — десять вопросов демо), ``top_k``,
    ``strategy``. Предел ожидания — ``LONG_TIMEOUT``: на вопрос приходится два вызова,
    и первый запрос к Ollama грузит веса модели в память.
    """
    payload = {}
    if questions:
        payload["questions"] = [str(item) for item in questions]
    if top_k is not None:
        payload["top_k"] = int(top_k)
    if strategy:
        payload["strategy"] = strategy
    return request_json("POST", "/rag/compare_providers", json=payload,
                        timeout=LONG_TIMEOUT)
