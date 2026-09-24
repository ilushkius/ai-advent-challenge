"""Инварианты демонстрации дня 14 — в одном месте для интерфейса, посева и отчёта.

Четыре инварианта по одному на каждую категорию: они показывают и блок в
системном промпте, и все три исхода проверки — «нарушений нет», «предупреждение»
и «отказ» (``invariants_demo.md``). Тем же списком пользуются кнопка в интерфейсе
и офлайн-скрипт посева ``scripts/seed_invariants.py``, поэтому значения в UI и в
отчёте не могут разойтись.

- ``Только FastAPI и Streamlit`` — архитектура, ``hard``: перечисляет запрещённые
  фреймворки (Flask, Django, Bottle, Tornado), поэтому запрос «перепишем бэкенд на
  Flask» даёт отказ;
- ``Состояние задачи в SQLite`` — технические решения, ``hard``: состояние задачи
  живёт в SQLite, внешние хранилища и брокеры (Redis, Memcached, MongoDB, Kafka)
  запрещены;
- ``Только Python`` — ограничения стека, ``hard``: без JavaScript, TypeScript и их
  фреймворков (Node.js, React, Vue, Angular);
- ``Платные API — только с согласия`` — бизнес-правила, ``soft``: платный вариант
  без согласия пользователя даёт предупреждение.

Описания перечисляют запрещённое явно: детерминированные правила привязываются к
описанию (``gate``), поэтому инвариант, не называющий средство, его и не ловит —
это защита от ложных срабатываний чужого по смыслу правила.

Модуль чистый: только данные (никаких импортов БД/LLM), поэтому его одинаково
импортируют Streamlit-приложение, менеджер инвариантов и скрипты дня.
"""
from typing import Any, Dict, List

__all__ = ["DEMO_INVARIANTS"]

DEMO_INVARIANTS: tuple[Dict[str, Any], ...] = (
    {
        "name": "Только FastAPI и Streamlit",
        "description": (
            "Используем только FastAPI и Streamlit; "
            "никаких Flask, Django, Bottle или Tornado"
        ),
        "category": "architecture",
        "severity": "hard",
    },
    {
        "name": "Состояние задачи в SQLite",
        "description": (
            "Состояние задачи хранится в SQLite, "
            "а не в Redis, Memcached, MongoDB или Kafka"
        ),
        "category": "tech_decisions",
        "severity": "hard",
    },
    {
        "name": "Только Python",
        "description": (
            "Только Python: без JavaScript, TypeScript "
            "и их фреймворков (Node.js, React, Vue, Angular)"
        ),
        "category": "stack_constraints",
        "severity": "hard",
    },
    {
        "name": "Платные API — только с согласия",
        "description": (
            "Агент не должен предлагать решения, которые требуют платных API "
            "без явного согласия пользователя"
        ),
        "category": "business_rules",
        "severity": "soft",
    },
)

# Список словарей для API-запросов посева: кортеж выше — неизменяемый источник.
DEMO_INVARIANT_PAYLOADS: List[Dict[str, Any]] = [dict(item) for item in DEMO_INVARIANTS]
