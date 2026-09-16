"""Распознавание намерения пользователя в реплике (день 13).

Что это.
    Чистая эвристика «по реплике»: по фразам в тексте сообщения определяется,
    просит ли пользователь приостановить задачу, продолжить её, откатиться на
    этап назад или подтверждает следующий шаг. Результат — ``TaskIntent`` или
    ``None``; сама реплика ничего в БД не пишет, переходы выполняет
    ``TaskStateMachine`` (``backend/task_state.py``).

    Намерения намеренно разделены на четыре группы, и группы просматриваются
    В ПОРЯДКЕ ОБЪЯВЛЕНИЯ — это и есть приоритет: «подтверждаю, продолжаем» —
    продолжение, а не «следующий шаг»; «готово, пауза» — пауза. Правило
    границы: совпадение обязано начинаться и заканчиваться на границе слова,
    поэтому «продолжительность сессии» — не намерение, а «продолжи» — намерение.

Как запустить.
    Модуль чистый: только ``enum`` и ``re``, никаких БД, сети и UI. Проверяется
    тестами:

        # из папки day13
        python -m pytest -q tests/unit/test_task_intent.py
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

__all__ = [
    "TaskIntent",
    "INTENT_PHRASES",
    "classify_task_intent",
]


class TaskIntent(Enum):
    """Намерение пользователя, меняющее состояние задачи."""

    PAUSE = "pause"
    RESUME = "resume"
    ROLLBACK = "rollback"
    ADVANCE = "advance"


# Таблица «намерение → фразы», ЕДИНСТВЕННЫЙ источник правды о распознавании.
# Порядок групп = приоритет: первая группа с совпадением выигрывает.
INTENT_PHRASES: tuple[tuple[TaskIntent, tuple[str, ...]], ...] = (
    (
        TaskIntent.PAUSE,
        ("пауза", "паузу", "поставь на паузу", "поставь задачу на паузу",
         "останови задачу", "приостанови"),
    ),
    (
        TaskIntent.RESUME,
        ("продолжи", "продолжить", "продолжаем", "возобнови", "с того же места"),
    ),
    (
        TaskIntent.ROLLBACK,
        ("откат", "откатись", "вернись на предыдущий", "вернись к предыдущему"),
    ),
    (
        TaskIntent.ADVANCE,
        ("подтверждаю", "подтверждаю план", "шаг выполнен", "выполнено", "готово",
         "следующий шаг", "дальше"),
    ),
)

# Шаблоны компилируются один раз на импорт: \b с обеих сторон — совпадение
# должно быть отдельным словом (или фразой), а не началом другого слова.
_INTENT_PATTERNS: tuple[tuple[TaskIntent, tuple[re.Pattern[str], ...]], ...] = tuple(
    (
        intent,
        tuple(re.compile(r"\b" + re.escape(phrase) + r"\b") for phrase in phrases),
    )
    for intent, phrases in INTENT_PHRASES
)


def classify_task_intent(text: str) -> Optional[TaskIntent]:
    """Намерение пользователя по реплике (``None`` — намерения нет)."""
    lowered = text.lower()
    if not lowered.strip():
        return None
    for intent, patterns in _INTENT_PATTERNS:
        for pattern in patterns:
            if pattern.search(lowered):
                return intent
    return None
