"""Маппинг данных между шагами пайплайна: ссылки ``$steps.``, ``{имя}`` и условия (день 19).

Проверяется главное свойство декларативного пайплайна: аргументы шага — это шаблон,
в котором ссылки на выход предыдущего шага заменяются настоящими значениями (список
остаётся списком, число — числом), а не строковым представлением. Отдельно
проверяются условия перехода: четыре оператора, сообщение условия и его попадание
в итог прогона, а также то, что невыполненное условие — это ``False``, а не ошибка.
"""
import pytest

from backend.domain.pipeline_mapping import (
    PipelineMappingError,
    evaluate_guard,
    resolve_mapping,
    resolve_path,
)
from backend.domain.pipeline_spec import (
    DEFAULT_GUARD_MESSAGE,
    GUARD_CONTAINS,
    GUARD_EMPTY,
    GUARD_EQUALS,
    GUARD_NON_EMPTY,
    GUARD_OPS,
    MSG_NO_DATA,
)


def _context():
    """Контекст прогона: аргументы запуска и выходы двух шагов."""
    return {
        "initial": {"query": "RAG", "limit": 7, "style": "short", "tags": ["a", "b"]},
        "steps": [
            {
                "structured": {
                    "query": "RAG",
                    "source_kind": "file",
                    "count": 3,
                    "items": [{"title": "Что такое RAG", "id": "file:notes.md#1"}],
                    "meta": {"path": "mcp_server/data/notes.md"},
                    "deep": {"level": {"value": 42}},
                },
                "text": "",
                "reason_code": None,
            },
            {
                "structured": {"summary_text": "Сводка", "key_points": ["RAG", "FSM"]},
                "text": "Сводка",
                "reason_code": None,
            },
        ],
    }


@pytest.mark.parametrize("path,expected", [
    ("$steps.0.structured.items", [{"title": "Что такое RAG", "id": "file:notes.md#1"}]),
    ("$steps.0.structured.count", 3),
    ("$steps.0.structured.meta", {"path": "mcp_server/data/notes.md"}),
    ("$steps.0.structured.query", "RAG"),
    ("$steps.1.structured.key_points", ["RAG", "FSM"]),
])
def test_exact_step_reference_returns_raw_value(path, expected):
    """Ссылка на поле шага целиком в строке возвращает значение без приведения к строке."""
    assert resolve_mapping(path, _context()) == expected


def test_exact_step_reference_keeps_container_types():
    """Список из выхода шага остаётся списком, словарь — словарём, число — числом."""
    items = resolve_mapping("$steps.0.structured.items", _context())
    count = resolve_mapping("$steps.0.structured.count", _context())
    meta = resolve_mapping("$steps.0.structured.meta", _context())
    assert isinstance(items, list) and isinstance(items[0], dict)
    assert isinstance(count, int) and not isinstance(count, bool)
    assert isinstance(meta, dict)


@pytest.mark.parametrize("path,expected", [
    ("$steps.0.structured.meta.path", "mcp_server/data/notes.md"),
    ("$steps.0.structured.items.0.title", "Что такое RAG"),
    ("$steps.0.structured.deep.level.value", 42),
    ("$steps.1.structured.key_points.1", "FSM"),
])
def test_paths_walk_nested_dicts_and_list_indexes(path, expected):
    """Числовой сегмент пути читается как индекс списка, остальные — как ключи словаря."""
    assert resolve_path(path, _context()) == expected


def test_reference_inside_text_is_substituted_as_string():
    """Ссылка внутри текста заменяется строковым представлением значения."""
    assert resolve_mapping("шаг: $steps.0.structured.query!",
                           _context()) == "шаг: RAG!"
    assert resolve_mapping("найдено $steps.0.structured.count элементов",
                           _context()) == "найдено 3 элементов"


def test_several_references_in_one_string_are_all_substituted():
    """Несколько ссылок внутри одной строки подставляются все, а не только первая."""
    resolved = resolve_mapping(
        "$steps.0.structured.source_kind:$steps.0.structured.query "
        "($steps.0.structured.count)",
        _context(),
    )
    assert resolved == "file:RAG (3)"


def test_placeholder_alone_returns_raw_argument():
    """Заглушка целиком в строке возвращает аргумент запуска как есть."""
    assert resolve_mapping("{limit}", _context()) == 7
    assert isinstance(resolve_mapping("{limit}", _context()), int)
    assert resolve_mapping("{tags}", _context()) == ["a", "b"]


def test_placeholder_inside_text_is_stringified():
    """Заглушки внутри текста подставляются через str; несколько — все."""
    assert resolve_mapping("лимит {limit}, запрос «{query}»",
                           _context()) == "лимит 7, запрос «RAG»"


def test_nested_structures_are_resolved_recursively():
    """Словари и списки в шаблоне обходятся рекурсивно, вложенные ссылки работают."""
    spec = {
        "items": "$steps.0.structured.items",
        "limit": "{limit}",
        "nested": {"query": "{query}", "list": ["{style}", 5,
                                                "$steps.0.structured.count"]},
    }
    resolved = resolve_mapping(spec, _context())
    assert resolved == {
        "items": [{"title": "Что такое RAG", "id": "file:notes.md#1"}],
        "limit": 7,
        "nested": {"query": "RAG", "list": ["short", 5, 3]},
    }
    assert isinstance(resolved["items"], list)
    assert isinstance(resolved["nested"]["list"][2], int)


@pytest.mark.parametrize("value", [5, None, True, 3.5])
def test_non_string_values_pass_through(value):
    """Не строки (числа, None, логические) возвращаются без изменений."""
    resolved = resolve_mapping(value, _context())
    assert resolved == value and type(resolved) is type(value)


@pytest.mark.parametrize("path", [
    "$steps.9.structured.items",
    "$steps.0.structured.absent",
    "$steps.0.structured.items.5",
    "$steps.0.structured.count.extra",
    "$steps.x.structured",
    "$steps.0.structured.items.0.absent",
])
def test_missing_path_raises_error_with_path_in_message(path):
    """Отсутствующий шаг, ключ или индекс — ошибка с упоминанием самого пути."""
    with pytest.raises(PipelineMappingError) as excinfo:
        resolve_mapping(path, _context())
    assert path in str(excinfo.value)


@pytest.mark.parametrize("spec", ["{absent}", "текст {absent}", "{absent} и хвост"])
def test_missing_argument_placeholder_raises_error_with_name(spec):
    """Незаполненная заглушка — ошибка с именем непереданного аргумента запуска."""
    with pytest.raises(PipelineMappingError) as excinfo:
        resolve_mapping(spec, _context())
    assert "absent" in str(excinfo.value)


@pytest.mark.parametrize("value,expected", [
    ([1], True),
    ([], False),
    ({"a": 1}, True),
    ({}, False),
    ("заметка", True),
    ("", False),
    (None, False),
    (0, True),
    (False, True),
    ([0], True),
])
def test_non_empty_guard(value, expected):
    """Условие non_empty: пустые контейнеры и None — «нет данных», 0 остаётся данными."""
    guard = {"path": "$steps.0.structured.value", "op": GUARD_NON_EMPTY}
    context = {"initial": {}, "steps": [{"structured": {"value": value}}]}
    passed, message = evaluate_guard(guard, context)
    assert passed is expected
    assert message == DEFAULT_GUARD_MESSAGE


@pytest.mark.parametrize("value,expected", [
    ([1], False),
    ([], True),
    ({"a": 1}, False),
    ({}, True),
    ("заметка", False),
    ("", True),
    (None, True),
    (0, False),
])
def test_empty_guard_is_negation_of_non_empty(value, expected):
    """Условие empty — отрицание non_empty для тех же значений."""
    guard = {"path": "$steps.0.structured.value", "op": GUARD_EMPTY}
    context = {"initial": {}, "steps": [{"structured": {"value": value}}]}
    assert evaluate_guard(guard, context)[0] is expected


@pytest.mark.parametrize("needle,expected", [
    (3, True),
    ("3", False),
    (4, False),
    (None, False),
])
def test_equals_guard_compares_exactly(needle, expected):
    """Условие equals сравнивает значение шага с ключом value точно, без приведения типов."""
    guard = {"path": "$steps.0.structured.count", "op": GUARD_EQUALS, "value": needle}
    assert evaluate_guard(guard, _context())[0] is expected


def test_equals_guard_without_value_key_raises():
    """Условию equals нужен ключ value — иначе понятная ошибка вместо KeyError."""
    guard = {"path": "$steps.0.structured.count", "op": GUARD_EQUALS}
    with pytest.raises(PipelineMappingError) as excinfo:
        evaluate_guard(guard, _context())
    assert "value" in str(excinfo.value)


@pytest.mark.parametrize("path,needle,expected", [
    ("$steps.0.structured.query", "RAG", True),
    ("$steps.0.structured.query", "FSM", False),
    ("$steps.1.structured.key_points", "FSM", True),
    ("$steps.1.structured.key_points", "RAG-оценка", False),
    ("$steps.0.structured.meta", "username", False),
    ("$steps.0.structured.count", "3", False),
])
def test_contains_guard_checks_substring_or_element(path, needle, expected):
    """Условие contains ищет подстроку в строке и элемент в списке."""
    guard = {"path": path, "op": GUARD_CONTAINS, "value": needle}
    assert evaluate_guard(guard, _context())[0] is expected


def test_contains_guard_finds_key_in_mapping():
    """Для словаря contains проверяет наличие ключа."""
    guard = {"path": "$steps.0.structured.meta", "op": GUARD_CONTAINS, "value": "path"}
    assert evaluate_guard(guard, _context())[0] is True


def test_unknown_guard_op_lists_allowed_ops():
    """Неизвестный оператор условия — ошибка с перечнем четырёх допустимых."""
    guard = {"path": "$steps.0.structured.count", "op": "greater_than"}
    with pytest.raises(PipelineMappingError) as excinfo:
        evaluate_guard(guard, _context())
    text = str(excinfo.value)
    assert "greater_than" in text
    for op in GUARD_OPS:
        assert op in text


@pytest.mark.parametrize("guard", [
    {"op": GUARD_NON_EMPTY},
    {"path": "", "op": GUARD_NON_EMPTY},
])
def test_guard_without_path_raises(guard):
    """Условие без пути — ошибка с упоминанием ключа path."""
    with pytest.raises(PipelineMappingError) as excinfo:
        evaluate_guard(guard, _context())
    assert "path" in str(excinfo.value)


def test_guard_with_missing_path_in_steps_raises():
    """Путь условия на несуществующий шаг — ошибка с упоминанием пути."""
    guard = {"path": "$steps.7.structured.items", "op": GUARD_NON_EMPTY}
    with pytest.raises(PipelineMappingError) as excinfo:
        evaluate_guard(guard, _context())
    assert "$steps.7.structured.items" in str(excinfo.value)


def test_guard_returns_custom_message_when_condition_failed():
    """Невыполненное условие возвращает False и своё сообщение, не бросая исключение."""
    context = {"initial": {}, "steps": [{"structured": {"items": []}}]}
    guard = {"path": "$steps.0.structured.items", "op": GUARD_NON_EMPTY,
             "message": MSG_NO_DATA}
    result = evaluate_guard(guard, context)
    assert result == (False, MSG_NO_DATA)


def test_guard_returns_custom_message_when_condition_passed():
    """Выполненное условие тоже возвращает сообщение условия — кортеж (bool, str)."""
    guard = {"path": "$steps.0.structured.query", "op": GUARD_NON_EMPTY,
             "message": "данные есть"}
    assert evaluate_guard(guard, _context()) == (True, "данные есть")


def test_guard_uses_default_message_when_absent():
    """Без ключа message условие отдаёт сообщение по умолчанию."""
    guard = {"path": "$steps.0.structured.query", "op": GUARD_NON_EMPTY}
    assert evaluate_guard(guard, _context()) == (True, DEFAULT_GUARD_MESSAGE)
    empty_guard = {"path": "$steps.0.structured.items", "op": GUARD_EMPTY}
    assert evaluate_guard(empty_guard, _context()) == (False, DEFAULT_GUARD_MESSAGE)
