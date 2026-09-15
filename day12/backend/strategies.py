"""Стратегии управления контекстом (день 11): перечисление и вспомогатели.

Что это.
    Единый Enum для четырёх стратегий агента. Стратегия — это идентификатор
    (по конвенции `AGENTS.md` значения строковые/читаемые, чтобы попадать в UI
    и лог без маппинга), а поведение сборки контекста живёт в методах класса
    `Agent` (`prepare_context` и его `_prepare_*` ветки) — здесь только
    перечисление и его индексы.

    - `sliding_window` — только последние N сообщений + системный промпт;
    - `sticky_facts` — факты диалога (ключ-значение) + последние N сообщений;
    - `branching` — ветвление истории через чекпоинты (таблица `checkpoints`);
    - `summary` — сжатие истории из дня 9 (конспект вместо старых реплик).

    Enum не хранит логики: перевод «значение -> член» и проверка допустимости
    вынесены в словарь `STRATEGY_BY_VALUE` и функцию `strategy_from_value`.
    Неизвестное значение — явная `ValueError`, а не «тихое» значение по умолчанию.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Strategy",
    "AVAILABLE_STRATEGIES",
    "STRATEGY_BY_VALUE",
    "strategy_from_value",
]


class Strategy(Enum):
    """Четыре стратегии управления контекстом диалога."""

    SLIDING_WINDOW = "sliding_window"
    STICKY_FACTS = "sticky_facts"
    BRANCHING = "branching"
    SUMMARY = "summary"


# Список допустимых значений (для API/UI и валидации) в порядке объявления.
AVAILABLE_STRATEGIES: list[str] = [strategy.value for strategy in Strategy]

# Таблица «значение -> член Enum» для восстановления из API/БД.
STRATEGY_BY_VALUE: dict[str, Strategy] = {
    strategy.value: strategy for strategy in Strategy
}


def strategy_from_value(value: str) -> Strategy:
    """Возвращает член `Strategy` по строковому значению.

    Неизвестное значение — явная ошибка `ValueError` (а не «тихий» откат),
    как того требует `AGENTS.md`.
    """
    try:
        return STRATEGY_BY_VALUE[value]
    except KeyError:
        raise ValueError(
            f"Неизвестная стратегия управления контекстом: {value!r}. "
            f"Допустимые: {', '.join(AVAILABLE_STRATEGIES)}"
        ) from None
