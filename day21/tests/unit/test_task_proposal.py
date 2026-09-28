"""Тесты распознавания предложения модели перейти в другой этап (день 15).

Что здесь проверяется: по фразам в ответе модели определяется, в какой этап
она предлагает перейти («задача завершена» → done, «перехожу к тестам» →
validation). Результат — член ``TaskStage`` или ``None``; сам ответ ничего не
меняет, решение о допуске перехода принимает домен
(``backend/domain/task_state_machine.py``), а отказ формирует агент.

Тесты идут без БД, сети и UI: модуль знает только про ``enum``-члены
``backend/domain/task_fsm.py`` и ``re``.
"""

from __future__ import annotations

import pytest

from backend.domain.task_fsm import STAGE_ORDER, TaskStage
from backend.domain.task_proposal import STAGE_PROPOSAL_PHRASES, detect_stage_proposal

# Все пары «этап → фраза» из таблицы STAGE_PROPOSAL_PHRASES.
ALL_PHRASES = tuple(
    (stage, phrase) for stage, phrases in STAGE_PROPOSAL_PHRASES for phrase in phrases
)


def test_phrases_are_declared_for_stages_of_the_forward_path() -> None:
    """Таблица знает только этапы прямого хода: paused из ответа не предлагают."""
    assert [stage for stage, _ in STAGE_PROPOSAL_PHRASES] == [
        TaskStage.DONE,
        TaskStage.VALIDATION,
        TaskStage.EXECUTION,
        TaskStage.PLANNING,
    ]
    assert all(stage in STAGE_ORDER for stage, _ in STAGE_PROPOSAL_PHRASES)
    assert all(phrases for _, phrases in STAGE_PROPOSAL_PHRASES)
    assert all(phrase for _, phrase in ALL_PHRASES)


@pytest.mark.parametrize("stage, phrase", ALL_PHRASES, ids=lambda x: str(x))
def test_every_phrase_is_recognized(stage: TaskStage, phrase: str) -> None:
    """Каждая объявленная фраза распознаётся внутри ответа модели."""
    assert detect_stage_proposal(f"Хорошо. {phrase}.") == stage


@pytest.mark.parametrize("stage, phrase", ALL_PHRASES, ids=lambda x: str(x))
def test_recognition_is_case_insensitive(stage: TaskStage, phrase: str) -> None:
    """Регистр ответа не важен."""
    assert detect_stage_proposal(phrase.upper()) == stage
    assert detect_stage_proposal(phrase.capitalize()) == stage


def test_phrase_is_matched_by_word_boundaries() -> None:
    """Совпадение обязано быть отдельной фразой, а не началом другого слова."""
    assert detect_stage_proposal("Перехожу к реализации плана") == TaskStage.EXECUTION
    assert detect_stage_proposal("Запускаю тестирование модуля") is None
    assert detect_stage_proposal("Составляю планшеты для отчёта") is None


def test_farthest_stage_wins_on_several_matches() -> None:
    """Несколько совпадений — берётся самый дальний этап прямого хода."""
    assert detect_stage_proposal("Перехожу к тестам — задача выполнена") == TaskStage.DONE
    assert detect_stage_proposal("Начинаю писать код и запускаю тесты") == \
        TaskStage.VALIDATION
    assert detect_stage_proposal("Составляю план, приступаю к реализации") == \
        TaskStage.EXECUTION


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "Расскажи, как устроено сжатие контекста",
        "Готово, но нужно уточнить требования",
        "Могу показать пример кода",
    ],
)
def test_no_proposal_returns_none(text: str) -> None:
    """Обычный ответ модели перехода не предлагает."""
    assert detect_stage_proposal(text) is None


def test_detection_has_no_side_effects() -> None:
    """Распознавание чистое: повторный вызов даёт то же и таблицу не меняет."""
    before = tuple(STAGE_PROPOSAL_PHRASES)
    first = detect_stage_proposal("задача завершена")
    second = detect_stage_proposal("задача завершена")
    assert first is second is TaskStage.DONE
    assert tuple(STAGE_PROPOSAL_PHRASES) == before
