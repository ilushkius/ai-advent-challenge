"""Демо локальной модели (день 26): три запроса к Ollama одним вызовом.

Единственный источник этих трёх запросов: их показывают ``POST /llm/local-demo``,
скрипт ``scripts/demo_local_llm.py`` и отчёт дня. Запросы разные по типу — факт,
логика, генерация кода: по ним видно и что отвечает программа (а не ``curl``), и
сколько локальная модель думает.

Оценка качества (``quality_score``) — эвристика по тексту ответа, а не оценка
человека: в отчёте это сказано прямо, а порог не подкручивается под результат.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ..core import config
from ..domain import llm_provider
from . import llm_factory

__all__ = ["DEMO_AGENT_ID", "LOCAL_DEMO_QUESTIONS", "quality_score", "run_demo"]

#: Подпись вызова: у локального провайдера журнала расходов нет, но вызов остаётся
#: подписанным так же, как у облачного (одна форма отчёта на оба провайдера).
DEMO_AGENT_ID = "local-demo"

#: Три запроса демо: ключ ведёт предел ответа в ``config.LOCAL_LLM_DEMO_MAX_TOKENS``.
LOCAL_DEMO_QUESTIONS: Tuple[Dict[str, str], ...] = (
    {"key": "fact", "title": "Простой факт", "prompt": "Столица Франции?"},
    {"key": "logic", "title": "Логическая задача",
     "prompt": "У Алисы 3 яблока, у Боба в 2 раза больше. Сколько всего яблок?"},
    {"key": "code", "title": "Генерация кода",
     "prompt": "Напиши функцию на Python для сортировки списка пузырьком."},
)


def quality_score(key: str, answer: str) -> int:
    """Эвристика 1…5 по тексту ответа: «Париж» для факта, «9» для задачи, код — слова.

    Это не оценка человека: у факта и задачи проверяется наличие ожидаемого числа
    или города, у кода — ``def``/``for``/``return``. Эвристика нужна, чтобы
    сравнивать прогоны между собой, а не чтобы выставить модели оценку.
    """
    text = str(answer or "").lower()
    if key == "fact":
        return 5 if "париж" in text else 1
    if key == "logic":
        return 5 if "9" in text else 1
    if key == "code":
        return min(5, 1 + (2 if "def " in text else 0)
                   + (1 if "for " in text else 0) + (1 if "return" in text else 0))
    return 1


def run_demo(*, client: Any = None) -> dict:
    """Три запроса локальной модели: строки ответа и суммарное время.

    Клиент берётся у фабрики дня 26 (провайдер ``local`` — HTTP к Ollama). Сбой
    Ollama не глотается: роутер переводит ``LocalLLMError`` в 502, скрипт — в код
    возврата 1, а молчаливо пустые ответы выглядели бы как «модель не умеет».
    """
    client = client or llm_factory.get_llm_client(llm_provider.PROVIDER_LOCAL,
                                                  agent_id=DEMO_AGENT_ID)
    rows = [_row(item, client) for item in LOCAL_DEMO_QUESTIONS]
    return {
        "provider": llm_provider.PROVIDER_LOCAL,
        "model": config.LOCAL_LLM_MODEL,
        "url": config.LOCAL_LLM_URL,
        "rows": rows,
        "total_ms": sum(int(row["duration_ms"]) for row in rows),
    }


def _row(item: Dict[str, str], client: Any) -> dict:
    """Одна строка демо: вопрос, ответ, время, токены и эвристика качества."""
    result = client.generate(item["prompt"],
                             max_tokens=config.LOCAL_LLM_DEMO_MAX_TOKENS[item["key"]])
    answer = str(result.get("answer") or "")
    return {
        "key": item["key"],
        "title": item["title"],
        "question": item["prompt"],
        "answer": answer,
        "duration_ms": int(result.get("duration_ms") or 0),
        "quality": quality_score(item["key"], answer),
        "provider": str(result.get("provider") or llm_provider.PROVIDER_LOCAL),
        "model": str(result.get("model") or config.LOCAL_LLM_MODEL),
        "tokens": dict(result.get("tokens") or {}),
    }
