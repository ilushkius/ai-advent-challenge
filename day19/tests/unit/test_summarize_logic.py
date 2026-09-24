"""Логика инструмента ``summarize`` (день 19): стиль, промпт, разбор ответа и агрегация.

Модуль чистый, поэтому проверяется целиком офлайн: границы стиля и длины,
содержимое промпта для DeepSeek, разбор ключевых пунктов по маркеру и сводка
агрегацией — движок, на который инструмент переходит, когда LLM недоступна.
Проверяются значения и границы, а не наличие полей.
"""
import re

import pytest

from mcp_server import config
from mcp_server.summarize_logic import (
    KEY_POINTS_MARKER,
    PROMPT_BODY_MAX,
    SummarizeError,
    aggregate_summary,
    build_prompt,
    clamp_max_length,
    item_body,
    item_title,
    items_payload,
    llm_summary,
    normalize_style,
    parse_key_points,
    summary_text_of,
)

#: Стиль → подпись, которая попадает в системное сообщение промпта.
STYLE_LABELS = {
    "short": "одна короткая сводка",
    "detailed": "подробная сводка",
    "bullets": "сводка списком пунктов",
}


def _items(count, title_prefix="заметка", body="текст заметки"):
    """Элементы с предсказуемыми заголовками: нумерация в сводке читается глазами."""
    return [{"title": f"{title_prefix} {index}", "content": body}
            for index in range(count)]


@pytest.mark.parametrize("style", ["", "   ", "\t\n"])
def test_blank_style_falls_back_to_default(style):
    """Пустая строка стиля — это не ошибка: берётся стиль по умолчанию дня."""
    assert normalize_style(style) == config.SUMMARY_STYLE_DEFAULT


@pytest.mark.parametrize("style", ["short", "SHORT", " Short ", "bullets", "DETAILED"])
def test_style_is_normalized_case_insensitively(style):
    """Стиль принимается в любом регистре и с пробелами вокруг."""
    assert normalize_style(style) == style.strip().lower()


def test_unknown_style_error_lists_allowed_values():
    """Чужой стиль отклоняется, а текст ошибки перечисляет допустимые стили."""
    with pytest.raises(SummarizeError) as exc:
        normalize_style("exotic")
    text = str(exc.value)
    assert "exotic" in text
    for style in config.SUMMARY_STYLES:
        assert style in text


@pytest.mark.parametrize("value,expected", [
    (10, config.SUMMARY_MAX_LENGTH_MIN),
    (config.SUMMARY_MAX_LENGTH_MIN, config.SUMMARY_MAX_LENGTH_MIN),
    (600, 600),
    (config.SUMMARY_MAX_LENGTH_MAX, config.SUMMARY_MAX_LENGTH_MAX),
    (99999, config.SUMMARY_MAX_LENGTH_MAX),
    ("450", 450),
    ("abc", config.SUMMARY_DEFAULT_MAX_LENGTH),
    (None, config.SUMMARY_DEFAULT_MAX_LENGTH),
])
def test_max_length_is_clamped(value, expected):
    """Длина сводки зажимается в границы дня, нечисловая — берётся по умолчанию."""
    assert clamp_max_length(value) == expected


def test_item_title_falls_back_to_first_line_of_content():
    """Без ``title`` заголовком становится первая строка ``content``."""
    assert item_title({"content": "Первая строка\nВторая"}) == "Первая строка"


def test_item_title_truncates_long_content():
    """Длинный ``content`` обрезается до границы заголовка элемента."""
    title = item_title({"content": "я" * 400})
    assert len(title) == config.SEARCH_TITLE_MAX


def test_item_title_without_known_fields_uses_dict_repr():
    """Элемент без заголовка и текста даёт свой словарь строкой, а не пустую строку."""
    item = {"id": "sqlite:steps:1", "url": "u"}
    assert item_title(item) == str(item)


def test_item_title_prefers_title_over_content():
    """Заголовок элемента важнее его текста: ``content`` для этого не читается."""
    assert item_title({"title": " RAG ", "content": "другое"}) == "RAG"


def test_item_body_falls_back_to_remaining_fields():
    """Без ``content`` тело собирается из остальных полей словаря."""
    item = {"title": "заголовок", "url": "https://example.test", "count": 2}
    assert item_body(item) == str({"url": "https://example.test", "count": 2})


@pytest.mark.parametrize("style,label", sorted(STYLE_LABELS.items()))
def test_build_prompt_has_system_and_user_roles(style, label):
    """Промпт — два сообщения: системная роль-редактор и список элементов."""
    prompt = build_prompt(_items(2), style, 600)
    assert [message["role"] for message in prompt] == ["system", "user"]
    system = prompt[0]["content"]
    assert label in system
    assert KEY_POINTS_MARKER in system
    assert "до 600 символов" in system


def test_build_prompt_reports_clamped_length():
    """В промпте стоит уже зажатая длина, а не запрошенная моделью."""
    system = build_prompt(_items(1), "short", 5)[0]["content"]
    assert f"до {config.SUMMARY_MAX_LENGTH_MIN} символов" in system


def test_build_prompt_numbers_items_and_caps_their_number():
    """Список в промпте нумеруется с единицы и не длиннее ``SUMMARY_ITEMS_MAX``."""
    prompt = build_prompt(_items(config.SUMMARY_ITEMS_MAX + 5), "short", 600)
    user = prompt[1]["content"]
    numbered = re.findall(r"^\d+\. ", user, flags=re.MULTILINE)
    assert len(numbered) == config.SUMMARY_ITEMS_MAX
    assert user.startswith("1. заметка 0")


def test_build_prompt_truncates_long_body():
    """Тело элемента в промпте обрезается: полные посты модели не нужны."""
    user = build_prompt([{"title": "t", "content": "я" * 1000}], "short", 600)[1]["content"]
    assert "я" * PROMPT_BODY_MAX in user
    assert "я" * (PROMPT_BODY_MAX + 1) not in user


@pytest.mark.parametrize("text,expected", [
    (f"Сводка.\n{KEY_POINTS_MARKER}\n- первый\n- второй", ["первый", "второй"]),
    (f"{KEY_POINTS_MARKER}\n* звёздочка", ["звёздочка"]),
    (f"{KEY_POINTS_MARKER}\n1. нумерованный\n2) скобка", ["нумерованный", "скобка"]),
])
def test_parse_key_points_reads_list_markers(text, expected):
    """Пункты после маркера читаются с любым маркером списка, в порядке строк."""
    assert parse_key_points(text) == expected


@pytest.mark.parametrize("text", ["", "просто текст без маркера", "- пункт без маркера"])
def test_parse_key_points_without_marker_is_empty(text):
    """Без маркера пунктов нет: случайные строки ответа за пункты не считаются."""
    assert parse_key_points(text) == []


def test_parse_key_points_ignores_text_before_marker_and_plain_lines():
    """До маркера — текст сводки, после него учитываются только строки списка."""
    text = f"- это ещё сводка\n{KEY_POINTS_MARKER}\nвводная строка\n- настоящий пункт"
    assert parse_key_points(text) == ["настоящий пункт"]


def test_parse_key_points_respects_limit():
    """Число пунктов ограничивается аргументом ``limit``."""
    text = KEY_POINTS_MARKER + "\n" + "\n".join(f"- пункт {index}" for index in range(5))
    assert parse_key_points(text, limit=2) == ["пункт 0", "пункт 1"]


def test_summary_text_of_keeps_text_before_marker():
    """Текст сводки — часть ответа LLM до маркера ключевых пунктов."""
    text = f"Главное про RAG.\n{KEY_POINTS_MARKER}\n- пункт"
    assert summary_text_of(text, 600) == "Главное про RAG."


def test_summary_text_of_truncates_to_clamped_length():
    """Текст сводки обрезается до запрошенной длины (с зажимом снизу)."""
    text = "я" * 200
    assert len(summary_text_of(text, 10)) == config.SUMMARY_MAX_LENGTH_MIN
    assert summary_text_of(text, 10) == text[:config.SUMMARY_MAX_LENGTH_MIN]


def test_aggregate_summary_short_joins_first_three_titles():
    """Стиль ``short`` — одна строка: число элементов и первые три заголовка."""
    result = aggregate_summary(_items(5), "short", 600)
    assert result["summary_text"] == "Найдено 5 элементов. Первые: заметка 0; заметка 1; заметка 2"
    assert result["engine"] == "aggregation"
    assert result["total_items"] == 5
    assert result["style_used"] == "short"


def test_aggregate_summary_detailed_is_numbered_list():
    """Стиль ``detailed`` — нумерованные строки, не длиннее ``SUMMARY_LINES_MAX``."""
    text = aggregate_summary(_items(8), "detailed", 600)["summary_text"]
    assert text.splitlines() == [f"{index}. заметка {index - 1}" for index in range(1, 6)]


def test_aggregate_summary_bullets_is_marker_list():
    """Стиль ``bullets`` — строки с маркером ``-``."""
    text = aggregate_summary(_items(7), "bullets", 600)["summary_text"]
    assert text.splitlines()[0] == "- заметка 0"
    assert len(text.splitlines()) == config.SUMMARY_LINES_MAX


def test_aggregate_summary_truncates_text_to_requested_length():
    """Сводка обрезается до запрошенной длины, сохраняя начало."""
    items = [{"title": "заголовок " * 5} for _ in range(5)]
    full = aggregate_summary(items, "detailed", config.SUMMARY_MAX_LENGTH_MAX)["summary_text"]
    short = aggregate_summary(items, "detailed", config.SUMMARY_MAX_LENGTH_MIN)["summary_text"]
    assert len(short) == config.SUMMARY_MAX_LENGTH_MIN
    assert full.startswith(short)


def test_aggregate_summary_key_points_are_titles_capped():
    """Ключевые пункты агрегации — заголовки элементов, не больше семи."""
    result = aggregate_summary(_items(10, title_prefix="t"), "short", 600)
    assert result["key_points"] == [f"t {index}" for index in range(config.SUMMARY_KEY_POINTS_MAX)]


def test_aggregate_summary_normalizes_style():
    """Стиль сводки нормализуется: в ``style_used`` попадает каноническое значение."""
    result = aggregate_summary(_items(3), " DETAILED ", 600)
    assert result["style_used"] == "detailed"
    assert result["summary_text"].startswith("1. заметка 0")


def test_aggregate_summary_of_empty_list_says_zero():
    """Пустой список — сводка из нуля элементов, а не падение агрегации."""
    result = aggregate_summary([], "short", 600)
    assert result["total_items"] == 0
    assert result["key_points"] == []
    assert result["summary_text"] == "Найдено 0 элементов. Первые: "


def test_llm_summary_splits_text_and_points():
    """Ветка LLM: текст до маркера, пункты после него, движок ``llm``."""
    text = f"RAG объединяет поиск и генерацию.\n{KEY_POINTS_MARKER}\n- chunking\n- эмбеддинги"
    result = llm_summary(text, _items(4), "detailed", 600)
    assert result["engine"] == "llm"
    assert result["summary_text"] == "RAG объединяет поиск и генерацию."
    assert result["key_points"] == ["chunking", "эмбеддинги"]
    assert result["total_items"] == 4
    assert result["style_used"] == "detailed"


@pytest.mark.parametrize("payload", ["строка", {"title": "объект"}, None, 42])
def test_items_payload_rejects_non_list(payload):
    """Аргумент ``items`` не массив — ошибка с понятным текстом, а не молчаливый пропуск."""
    with pytest.raises(SummarizeError):
        items_payload(payload)


def test_items_payload_wraps_foreign_values_as_titles():
    """Элементы не-словари становятся словарями с заголовком из строкового вида."""
    assert items_payload([1, "текст", {"title": "готовый"}]) == [
        {"title": "1"}, {"title": "текст"}, {"title": "готовый"},
    ]


def test_items_payload_cuts_extra_items():
    """Лишние элементы отбрасываются: сводка не растёт вместе с входом."""
    payload = items_payload(list(range(config.SUMMARY_ITEMS_MAX + 50)))
    assert len(payload) == config.SUMMARY_ITEMS_MAX
    assert payload[0] == {"title": "0"}
    assert payload[-1] == {"title": str(config.SUMMARY_ITEMS_MAX - 1)}


def test_style_error_propagates_from_prompt_and_aggregation():
    """Неизвестный стиль одинаково отклоняется и промптом, и агрегацией."""
    with pytest.raises(SummarizeError):
        build_prompt(_items(1), "exotic", 600)
    with pytest.raises(SummarizeError):
        aggregate_summary(_items(1), "exotic", 600)


def test_llm_branch_truncates_text_like_aggregation():
    """Ветка LLM обрезает текст той же границей длины, что и агрегация."""
    text = "я" * 5000
    result = llm_summary(text, _items(1), "short", 100)
    assert result["summary_text"] == text[:100]
