"""Распознавание реплики «собери пайплайн» (день 19).

Проверяется эвристика целиком: пайплайном реплика считается только когда в ней
есть фразы ВСЕХ ТРЁХ действий (поиск, сводка, сохранение), а из самой реплики
достаются аргументы запуска — запрос, источник, стиль, формат и имя файла. Вторая
половина ценности — негативные случаи: «найди статьи про RAG» остаётся одиночным
вызовом инструмента дня 17, а не запуском пайплайна с побочным эффектом (файл в
``output/`` и запись в истории запусков).
"""
import copy

import pytest

from backend.domain.pipeline_intent import (
    DEFAULT_FILE_NAME,
    DEFAULT_LIMIT,
    DEFAULT_MAX_LENGTH,
    SAVE_PHRASES,
    SEARCH_PHRASES,
    SUMMARY_PHRASES,
    classify_pipeline_intent,
    pipeline_filename,
    pipeline_query,
)
from backend.domain.pipeline_spec import DEFAULT_PIPELINE, FILE_SOURCE_DEFAULT

#: Реплика задания: три действия и предмет поиска в обороте «про …».
TASK_UTTERANCE = "найди статьи про RAG, сделай сводку и сохрани в файл"


def _group_of(phrase: str) -> int:
    """Номер группы действия для сработавшей фразы (``-1`` — фразы нет ни в одной)."""
    for index, group in enumerate((SEARCH_PHRASES, SUMMARY_PHRASES, SAVE_PHRASES)):
        if phrase in group:
            return index
    return -1


def test_task_utterance_gives_arguments_and_pipeline():
    """Реплика задания даёт запрос RAG, заметки дня, файл rag.md и встроенный пайплайн."""
    intent = classify_pipeline_intent(TASK_UTTERANCE)

    assert intent is not None
    assert set(intent.arguments) == {"query", "source", "limit", "style",
                                     "max_length", "filename", "format"}
    assert intent.arguments["query"] == "RAG"
    assert intent.arguments["source"] == FILE_SOURCE_DEFAULT
    assert intent.arguments["limit"] == DEFAULT_LIMIT
    assert intent.arguments["style"] == "short"
    assert intent.arguments["max_length"] == DEFAULT_MAX_LENGTH
    assert intent.arguments["filename"] == "rag.md"
    assert intent.arguments["format"] == "md"
    assert intent.pipeline == DEFAULT_PIPELINE


def test_phrases_cover_all_three_action_groups_once():
    """Сработавшие фразы — по одной из каждой группы действий: поиск, сводка, сохранение."""
    intent = classify_pipeline_intent(TASK_UTTERANCE)

    assert intent is not None
    assert len(intent.phrases) == 3
    assert sorted(_group_of(phrase) for phrase in intent.phrases) == [0, 1, 2]


def test_intent_pipeline_is_a_detached_copy():
    """Правка конфигурации внутри намерения не меняет встроенный пайплайн дня."""
    snapshot = copy.deepcopy(DEFAULT_PIPELINE)
    intent = classify_pipeline_intent(TASK_UTTERANCE)

    assert intent is not None
    intent.pipeline["name"] = "чужой пайплайн"
    intent.pipeline["steps"][0]["args"]["query"] = "чужой запрос"
    intent.pipeline["steps"].clear()

    assert DEFAULT_PIPELINE == snapshot


@pytest.mark.parametrize("text", [
    "найди статьи про RAG и сделай сводку",
    "найди статьи про RAG и сохрани в файл",
    "сделай сводку и сохрани в файл",
    "найди статьи про RAG",
])
def test_two_actions_are_not_enough(text):
    """Фразы двух действий из трёх (или одного) — не пайплайн, а обычная реплика."""
    assert classify_pipeline_intent(text) is None


@pytest.mark.parametrize("text", ["", "   ", "\n\t  "])
def test_blank_utterance_is_not_an_intent(text):
    """Пустая реплика и одни пробелы не дают намерения пайплайна."""
    assert classify_pipeline_intent(text) is None


@pytest.mark.parametrize("text", [
    "поищи про FSM и сделай краткий конспект, запиши в файл",
    "найти материалы про FSM, суммируй и сохрани",
    "собери данные про FSM, сделай итог, в файл",
    "ищи про FSM, нужна краткая сводка, сохранить",
    "Найди статьи про RAG, Сделай сводку и Сохрани в файл",
])
def test_trigger_words_match_with_endings(text):
    """Окончания и регистр фраз не мешают распознаванию всех трёх действий."""
    intent = classify_pipeline_intent(text)

    assert intent is not None
    assert sorted(_group_of(phrase) for phrase in intent.phrases) == [0, 1, 2]


@pytest.mark.parametrize("text", [
    "найди статьи про RAG, сделай суммирование и сохрани в файл",
    "найди статьи про RAG, оцени краткость изложения и сохрани в файл",
])
def test_longer_word_with_trigger_root_is_not_a_match(text):
    """Слово с корнем-фразой, но длинным окончанием действием не считается."""
    assert classify_pipeline_intent(text) is None


@pytest.mark.parametrize("text,style", [
    ("найди статьи про RAG, сделай подробную сводку и сохрани в файл", "detailed"),
    ("найди статьи про RAG, сделай подробный конспект, сохрани в файл", "detailed"),
    (TASK_UTTERANCE, "short"),
    ("найди статьи про RAG, сделай краткую сводку и сохрани в файл", "short"),
])
def test_style_flag(text, style):
    """«Подробн» в реплике включает подробную сводку, иначе выбирается краткая."""
    intent = classify_pipeline_intent(text)

    assert intent is not None
    assert intent.arguments["style"] == style


@pytest.mark.parametrize("tail,fmt,filename", [
    ("сохрани в json", "json", "rag.json"),
    ("сохрани в txt", "txt", "rag.txt"),
    ("сохрани в текст", "txt", "rag.txt"),
    ("сохрани в файл", "md", "rag.md"),
])
def test_format_defines_file_extension(tail, fmt, filename):
    """Формат из реплики задаёт и поле format, и расширение имени файла."""
    intent = classify_pipeline_intent(f"найди статьи про RAG, сделай сводку и {tail}")

    assert intent is not None
    assert intent.arguments["format"] == fmt
    assert intent.arguments["filename"] == filename


@pytest.mark.parametrize("text,source", [
    ("найди пользователей про RAG, сделай сводку и сохрани в файл", "users"),
    ("найди юзеров про RAG, сделай сводку и сохрани в файл", "users"),
    ("найди посты про RAG, сделай сводку и сохрани в файл", "posts"),
    ("найди данные из внешнего источника про RAG, сделай сводку и сохрани файл",
     "posts"),
    (TASK_UTTERANCE, FILE_SOURCE_DEFAULT),
    ("найди посты пользователя про RAG, сделай сводку и сохрани в файл", "users"),
])
def test_source_recognition(text, source):
    """Источник выбирается по словам реплики; слова про пользователей приоритетнее."""
    intent = classify_pipeline_intent(text)

    assert intent is not None
    assert intent.arguments["source"] == source


@pytest.mark.parametrize("text,query", [
    ("Про RAG, найди и сделай сводку, сохрани в файл", "RAG"),
    ("найди статьи про FSM, сделай сводку и сохрани в файл", "FSM"),
])
def test_query_comes_from_the_about_turn(text, query):
    """Оборот «про …» даёт запрос и сохраняет его регистр."""
    assert pipeline_query(text) == query


@pytest.mark.parametrize("text,query", [
    ("собери заметки rag, суммируй, сохрани", "заметки rag"),
    ("собери один два три четыре пять шесть семь, суммируй, сохрани",
     "один два три четыре пять"),
    ("найди сводку сохрани", "данные"),
    ("", "данные"),
])
def test_query_fallback_without_about_turn(text, query):
    """Без оборота «про …» запрос — первые пять слов реплики без служебных фраз."""
    assert pipeline_query(text) == query


@pytest.mark.parametrize("raw,fmt,filename", [
    ("RAG", "md", "rag.md"),
    ("машинное обучение", "txt", "машинное-обучение.txt"),
    ("Что такое RAG?", "md", "что-такое-rag.md"),
    ("", "md", f"{DEFAULT_FILE_NAME}.md"),
    ("!!!", "json", f"{DEFAULT_FILE_NAME}.json"),
])
def test_filename_is_a_slug_with_format_suffix(raw, fmt, filename):
    """Имя файла — нижний регистр, знаки в дефис, пустая основа — заглушка."""
    assert pipeline_filename(raw, fmt) == filename


def test_to_dict_returns_a_detached_report():
    """``to_dict`` даёт плоский отчёт, правка которого не меняет намерение."""
    intent = classify_pipeline_intent(TASK_UTTERANCE)

    assert intent is not None
    report = intent.to_dict()

    assert set(report) == {"pipeline", "arguments", "phrases"}
    assert report["pipeline"] == DEFAULT_PIPELINE
    assert report["arguments"] == intent.arguments
    assert report["phrases"] == list(intent.phrases)
    assert isinstance(report["phrases"], list)

    report["pipeline"]["steps"].clear()
    report["arguments"]["query"] = "подмена"
    report["phrases"].append("подмена")

    assert intent.pipeline == DEFAULT_PIPELINE
    assert intent.arguments["query"] == "RAG"
    assert len(intent.phrases) == 3
