"""Тесты распознавания запроса к инструменту (день 17).

Эвристика — единственное место, где реплика пользователя превращается в вызов:
здесь фиксируются приоритет правил («посты пользователя» — это не ``get_user``),
морфология («пользователя/пользователю/пользователям» — одно правило, а
«пользовательский» — уже нет), номер аргумента и то, что чужие инструменты
каталога не обещаются.
"""
import pytest

from backend.domain.mcp_intent import (
    TOOL_GET_POST,
    TOOL_GET_USER,
    TOOL_LIST_USER_POSTS,
    classify_tool_call,
)

ALL_TOOLS = (TOOL_GET_USER, TOOL_GET_POST, TOOL_LIST_USER_POSTS)


@pytest.mark.parametrize("text,tool,arguments", [
    ("Найди информацию о пользователе с ID 1", TOOL_GET_USER, {"user_id": 1}),
    ("Покажи пост 3", TOOL_GET_POST, {"post_id": 3}),
    ("Какие посты у пользователя 2", TOOL_LIST_USER_POSTS, {"user_id": 2}),
    ("Посты пользователя 2", TOOL_LIST_USER_POSTS, {"user_id": 2}),
    ("публикации пользователя 5", TOOL_LIST_USER_POSTS, {"user_id": 5}),
    ("Расскажи про юзер 4", TOOL_GET_USER, {"user_id": 4}),
    ("что за статья 7", TOOL_GET_POST, {"post_id": 7}),
])
def test_recognizes_tool_and_argument(text, tool, arguments):
    """Реплика даёт инструмент и номер аргумента из первого числа в тексте."""
    plan = classify_tool_call(text, ALL_TOOLS)
    assert plan is not None
    assert plan.tool == tool
    assert plan.arguments == arguments
    assert plan.phrase


def test_posts_of_user_wins_over_get_user():
    """Приоритет правил: «посты … пользователя» — список постов, а не пользователь."""
    plan = classify_tool_call("Какие посты у пользователя 2", ALL_TOOLS)
    assert plan.tool == TOOL_LIST_USER_POSTS
    assert classify_tool_call("Покажи пользователя 2", ALL_TOOLS).tool == TOOL_GET_USER


@pytest.mark.parametrize("text", [
    "Расскажи про пользователя",
    "Что нового у пользователей?",
])
def test_missing_number_leaves_arguments_empty(text):
    """Номера нет — план без аргументов: причину отказа назовут правила допуска."""
    plan = classify_tool_call(text, ALL_TOOLS)
    assert plan is not None and plan.arguments == {}


@pytest.mark.parametrize("text,tool", [
    ("пользователям нужен совет", TOOL_GET_USER),
    ("пользователя зовут Иван", TOOL_GET_USER),
    ("юзер 4", TOOL_GET_USER),
])
def test_morphology_tail_matches(text, tool):
    """До трёх букв окончания — то же правило: «пользователя», «пользователям», «юзер»."""
    assert classify_tool_call(text, ALL_TOOLS).tool == tool


def test_morphology_does_not_match_other_words():
    """«пользовательский» — другое слово, а не форма «пользователь»."""
    assert classify_tool_call("Сделай пользовательский отчёт", ALL_TOOLS) is None


def test_case_insensitive():
    """Регистр реплики не влияет на распознавание."""
    assert classify_tool_call("ПОКАЖИ ПОСТ 3", ALL_TOOLS).tool == TOOL_GET_POST


@pytest.mark.parametrize("text", ["", "   ", "Сколько будет 2+2?"])
def test_no_intent_returns_none(text):
    """Без ключевых слов и на пустой реплике плана нет."""
    assert classify_tool_call(text, ALL_TOOLS) is None


def test_tool_absent_from_catalog_is_ignored():
    """Правило пропускается, если сервер такого инструмента не предлагает.

    У чужого сервера с одним ``get_post`` реплика про пост плана не даёт вовсе:
    обещать вызов инструмента, которого у сервера нет, нельзя.
    """
    assert classify_tool_call("Покажи пост 3", (TOOL_GET_USER,)) is None
    assert classify_tool_call("Найди пользователя 1", (TOOL_GET_POST,)) is None
    assert classify_tool_call("Покажи пост 3", (TOOL_GET_POST,)).arguments == {"post_id": 3}


def test_first_number_wins():
    """Берётся первое число: «пользователь 3 из списка 10» — это id 3."""
    plan = classify_tool_call("Найди пользователя 3 из списка 10", ALL_TOOLS)
    assert plan.arguments == {"user_id": 3}


def test_plan_to_dict_is_a_copy():
    """Словарь плана копирует аргументы: правка отчёта не меняет план."""
    plan = classify_tool_call("Покажи пост 3", ALL_TOOLS)
    payload = plan.to_dict()
    payload["arguments"]["post_id"] = 99
    assert plan.arguments == {"post_id": 3}
