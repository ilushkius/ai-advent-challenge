"""Тесты распознавания намерения в реплике пользователя (день 13).

Проверяется, что состояние задачи обновляется по обычной реплике: «пауза»,
«продолжи», «вернись на предыдущий этап», «подтверждаю». Тесты идут без БД и
без сети — модуль ``task_intent`` чистый.
"""

from __future__ import annotations

import pytest

from backend.domain.task_intent import INTENT_PHRASES, TaskIntent, classify_task_intent

# Все пары «фраза → намерение» из таблицы INTENT_PHRASES.
ALL_PHRASES = tuple(
    (intent, phrase) for intent, phrases in INTENT_PHRASES for phrase in phrases
)


def test_intent_phrases_are_declared_in_priority_order() -> None:
    """Пауза важнее продолжения, продолжение — важнее отката и подтверждения."""
    assert [intent for intent, _ in INTENT_PHRASES] == [
        TaskIntent.PAUSE,
        TaskIntent.RESUME,
        TaskIntent.ROLLBACK,
        TaskIntent.ADVANCE,
    ]
    assert TaskIntent.PAUSE.value == "pause"
    assert TaskIntent.RESUME.value == "resume"
    assert TaskIntent.ROLLBACK.value == "rollback"
    assert TaskIntent.ADVANCE.value == "advance"


@pytest.mark.parametrize("intent, phrase", ALL_PHRASES, ids=lambda x: str(x))
def test_every_phrase_is_recognized(intent: TaskIntent, phrase: str) -> None:
    """Каждая объявленная фраза распознаётся внутри предложения."""
    assert classify_task_intent(f"ок, {phrase} пожалуйста") == intent


@pytest.mark.parametrize("intent, phrase", ALL_PHRASES, ids=lambda x: str(x))
def test_recognition_is_case_insensitive(intent: TaskIntent, phrase: str) -> None:
    """Регистр реплики не важен."""
    assert classify_task_intent(phrase.upper()) == intent
    assert classify_task_intent(phrase.capitalize()) == intent


def test_resume_wins_over_advance() -> None:
    """«подтверждаю, продолжаем» — это продолжение, а не следующий шаг."""
    assert classify_task_intent("подтверждаю, продолжаем") == TaskIntent.RESUME


def test_pause_wins_over_advance() -> None:
    """«готово, пауза» — это пауза: остановка приоритетнее подтверждения."""
    assert classify_task_intent("готово, пауза") == TaskIntent.PAUSE


def test_rollback_wins_over_advance() -> None:
    """«готово, откатись» — это откат."""
    assert classify_task_intent("готово, откатись") == TaskIntent.ROLLBACK


@pytest.mark.parametrize(
    "text",
    [
        "поставь задачу на паузу",
        "Поставь задачу на паузу и сохрани состояние",
        "пауза",
    ],
)
def test_pause_phrases_from_the_task_specification(text: str) -> None:
    """Реплики паузы из задания и демонстрации распознаются."""
    assert classify_task_intent(text) == TaskIntent.PAUSE


@pytest.mark.parametrize(
    "text, expected",
    [
        ("продолжи", TaskIntent.RESUME),
        ("продолжаем с того же места", TaskIntent.RESUME),
        ("подтверждаю", TaskIntent.ADVANCE),
        ("готово", TaskIntent.ADVANCE),
        ("вернись на предыдущий этап", TaskIntent.ROLLBACK),
    ],
)
def test_phrases_from_the_task_specification(text: str, expected: TaskIntent) -> None:
    """Реплики из задания (панель, демонстрация) дают ожидаемое намерение."""
    assert classify_task_intent(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "расскажи про токены и контекст",
        "продолжительность сессии",
        "откатывать историю в базе",
        "паузальная конструкция",
    ],
)
def test_no_intent_returns_none(text: str) -> None:
    """Обычная реплика не меняет состояние задачи.

    «продолжительность», «откатывать» и «паузальная» — проверка границы слова:
    совпадение обязано начинаться и заканчиваться на границе слова, иначе
    рассуждение про токены переводило бы задачу в паузу.
    """
    assert classify_task_intent(text) is None


def test_phrase_at_the_very_start_and_very_end() -> None:
    """Фраза работает и без окружения словами: «пауза», «продолжи»."""
    assert classify_task_intent("пауза") == TaskIntent.PAUSE
    assert classify_task_intent("пауза!") == TaskIntent.PAUSE
    assert classify_task_intent("ок, продолжи") == TaskIntent.RESUME
