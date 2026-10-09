"""Домен демо удалённой LLM (день 30): шаги прогона и сводка по его строкам.

Здесь лежит то, что должны видеть обе стороны — служба прогона
(``services/remote_llm_service``) и интерфейс (``frontend/remote_llm_section``): порядок
пяти шагов (ключ, подпись, вопрос, вид проверки), подписи для таблицы и арифметика
сводки. Интерфейс берёт список шагов отсюда, а не сочиняет свой: иначе кнопка в UI и
сценарий в отчёте разошлись бы при первой же правке.

Сеть, клиенты и настройки сюда не попадают: шаг — это описание проверки, а не её
исполнение. Значений ``config`` тоже нет — предел ответа шага зависит от настроек
дня 30 и остаётся в службе.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from . import llm_provider

__all__ = ["DEMO_STEPS", "STEP_KEYS", "DemoStep", "STEP_CODE", "STEP_CONNECTION",
           "STEP_FACT", "STEP_LOGIC", "STEP_RATE_LIMIT", "step_question",
           "step_title", "summarize_rows"]

STEP_CONNECTION = "connection"
STEP_FACT = "fact"
STEP_LOGIC = "logic"
STEP_CODE = "code"
STEP_RATE_LIMIT = "rate_limit"

#: Виды проверок шага: проверка связи, вопрос к модели, предел частоты.
KIND_CHECK = "check"
KIND_ASK = "ask"
KIND_RATE = "rate"


@dataclass(frozen=True)
class DemoStep:
    """Шаг демо: ключ и подпись для интерфейса, вопрос и вид проверки."""

    key: str
    title: str
    question: str
    kind: str


#: Порядок шагов задан один раз здесь: интерфейс, скрипт и отчёт идут по нему же,
#: поэтому строки таблицы не могут разойтись в наборе или порядке.
DEMO_STEPS: tuple[DemoStep, ...] = (
    DemoStep(STEP_CONNECTION, "Проверка соединения", "GET /models", KIND_CHECK),
    DemoStep(STEP_FACT, "Простой вопрос", "Столица Франции?", KIND_ASK),
    DemoStep(STEP_LOGIC, "Логическая задача",
             "У Алисы 3 яблока, у Боба в 2 раза больше. Сколько всего яблок?", KIND_ASK),
    DemoStep(STEP_CODE, "Генерация кода",
             "Напиши функцию на Python для сортировки списка пузырьком", KIND_ASK),
    DemoStep(STEP_RATE_LIMIT, "Проверка rate limit",
             "N+1 запросов подряд при лимите N в минуту", KIND_RATE),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in DEMO_STEPS)
_STEPS_BY_KEY = {step.key: step for step in DEMO_STEPS}


def step_title(key: str) -> str:
    """Подпись шага для таблицы; незнакомый ключ остаётся собой."""
    step = _STEPS_BY_KEY.get(key)
    return step.title if step else key


def step_question(key: str) -> str:
    """Вопрос шага, как его увидит модель (подпись в интерфейсе и отчёте)."""
    step = _STEPS_BY_KEY.get(key)
    return step.question if step else ""


def summarize_rows(rows: Sequence[dict]) -> dict:
    """Сводка прогона: запросы, успешные шаги, ошибки, среднее время, провайдер.

    ``calls`` — реально ушедшие HTTP-запросы, ``blocked`` — отклонённые клиентом до
    отправки, ``requests`` — их сумма: без этого разделения шаг про частоту
    увеличивал бы «всего запросов» на запрос, которого модель не получала.

    ``remote_confirmed`` — подтверждение для видео: среди ответов таблицы нет ни
    одного не-remote, то есть все строки принёс удалённый сервис, а не облако.
    """
    rows = list(rows)
    calls = sum(int(row.get("calls") or 0) for row in rows)
    blocked = sum(int(row.get("blocked") or 0) for row in rows)
    times = [int(row.get("duration_ms") or 0) for row in rows]
    ok_times = [int(row.get("duration_ms") or 0) for row in rows
                if row.get("status") == "ok"]
    providers = sorted({str(row.get("provider") or "") for row in rows})
    errors = sum(1 for row in rows if row.get("status") != "ok")
    return {
        "steps": len(rows),
        "calls": calls,
        "blocked": blocked,
        "requests": calls + blocked,
        "success": len(rows) - errors,
        "errors": errors,
        "avg_ms": int(sum(times) / len(times)) if times else 0,
        "avg_ok_ms": int(sum(ok_times) / len(ok_times)) if ok_times else 0,
        "total_ms": sum(times),
        "provider": providers[0] if len(providers) == 1 else ",".join(providers),
        "remote_confirmed": providers == [llm_provider.PROVIDER_REMOTE],
    }
