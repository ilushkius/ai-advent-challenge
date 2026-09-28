"""Тесты распознавания реплики «выполни флоу по нескольким серверам» (день 20).

Правило узкое намеренно, и это главное, что здесь проверяется: реплика дня 19
«найди статьи про RAG, сделай сводку и сохрани в файл» ОБЯЗАНА остаться пайплайном
(её контракт закреплён тестом дня 19), а требование дня 20 «найди данные и сохрани в
БД» — попадать в оркестрацию, потому что пайплайн умеет писать только файл. Отсюда
два набора случаев: фразы-триггеры (сохранение в базу/БД/sqlite и явное упоминание
оркестрации) и реплики, которые триггером не являются.
"""
import pytest

from backend.domain.orchestration_intent import (
    DEFAULT_FORMAT,
    DEFAULT_LIMIT,
    ORCH_PHRASES,
    classify_orchestration_intent,
    orchestration_arguments,
    orchestration_filename,
    orchestration_query,
)

#: Реплики, которые распознаются как оркестрация (фраза видна в ``phrases``).
DETECTED = (
    ("найди данные и сохрани в базу", "в базу"),
    ("найди данные и сохрани в БД", "в бд"),
    ("запиши в базу знание", "в базу"),
    ("собери отчёт, сохрани в базу данных и пришли ссылку", "в базу"),
    ("найди записи и сохрани в sqlite", "в sqlite"),
    ("запусти оркестрацию серверов", "оркестрац"),
    ("нужны данные с нескольких серверов", "нескольких серверов"),
    ("собери данные с нескольких серверов", "нескольких серверов"),
    ("собери данные из флота серверов", "флота серверов"),
    ("собери цепочку инструментов", "цепочк"),
)

#: Реплики, которые оркестрацией НЕ являются (в том числе пайплайн дня 19).
NOT_DETECTED = (
    None,
    "",
    "   ",
    "сколько будет 2+2?",
    # Контракт дня 19: эта реплика — пайплайн (файл, а не база).
    "найди статьи про RAG, сделай сводку и сохрани в файл",
    "найди пользователей и сохрани в файл",
    "сделай сводку по постам",
)


@pytest.mark.parametrize("text,phrase", DETECTED)
def test_orchestration_replies_are_detected(text, phrase):
    """Реплика с триггером распознаётся, и сработавшая фраза видна в отчёте."""
    intent = classify_orchestration_intent(text)
    assert intent is not None
    assert phrase in intent.phrases
    payload = intent.to_dict()
    assert payload["query"] == intent.query
    assert payload["arguments"] == intent.arguments
    assert payload["phrases"] == list(intent.phrases)


@pytest.mark.parametrize("text", NOT_DETECTED)
def test_other_replies_are_not_orchestration(text):
    """Прочие реплики не распознаются: их разбирают прежние пути (пайплайн, MCP)."""
    assert classify_orchestration_intent(text) is None


def test_phrases_are_declared():
    """Все объявленные триггеры действительно ловят свои реплики."""
    for phrase in ORCH_PHRASES:
        assert classify_orchestration_intent(f"сделай это {phrase}") is not None


def test_arguments_have_everything_the_plan_uses():
    """Аргументы запуска закрывают все заглушки плана: query, limit, filename, format."""
    args = orchestration_arguments("найди данные про RAG и сохрани в базу")
    assert set(args) == {"query", "limit", "filename", "format"}
    assert args["limit"] == DEFAULT_LIMIT >= 1
    assert args["format"] == DEFAULT_FORMAT
    assert args["filename"].endswith(f".{DEFAULT_FORMAT}")
    assert "rag" in args["filename"], "имя файла выводится из запроса"


def test_query_and_filename_helpers():
    """Запрос берётся из оборота «про …», имя файла чистится до машинного вида."""
    assert orchestration_query("найди статьи про RAG, сохрани в базу") == "RAG"
    assert orchestration_filename("Про RAG", "md") == "про-rag.md"
    assert orchestration_filename("", "json") == "orchestration.json"


def test_filename_is_stable_for_the_same_reply():
    """Имя файла не зависит от повторных вызовов: прогон не плодит разные файлы."""
    text = "найди данные и сохрани в базу"
    first = classify_orchestration_intent(text)
    second = classify_orchestration_intent(text)
    assert first.arguments == second.arguments
