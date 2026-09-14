"""Тесты эвристического извлечения фактов (backend/fact_extractor.py).

Проверяется чистая функция `extract_facts` и её помощники: распознавание
форматов «ключ: значение», «ключ = значение», «ключ — значение», разбивка по
«;», нормализация ключей, обрезка кавычек, игнор строк без разделителя и
слияние словарей. Никаких побочных эффектов: только стандартная библиотека.
"""
import pytest

from backend.fact_extractor import extract_facts, merge_facts, normalize_key


def test_colon_equals_dash_formats():
    assert extract_facts("Имя: Иван") == {"имя": "Иван"}
    assert extract_facts("бюджет = 5000 рублей") == {"бюджет": "5000 рублей"}
    assert extract_facts("Срок — 3 месяца") == {"срок": "3 месяца"}


def test_multiple_facts_per_line_by_semicolon():
    facts = extract_facts("Стек: Python; БД = PostgreSQL; Срок — 3 месяца")
    assert facts == {
        "стек": "Python",
        "бд": "PostgreSQL",
        "срок": "3 месяца",
    }


def test_multiline_input():
    facts = extract_facts("Название: портал\nБюджет: 5000")
    assert facts == {"название": "портал", "бюджет": "5000"}


def test_key_normalization_case_and_spaces():
    # «Бюджет», «бюджет» и «  БЮДЖЕТ  » — один ключ после нормализации.
    assert normalize_key("  БЮДЖЕТ  ") == "бюджет"
    assert extract_facts("Бюджет: 100") == {"бюджет": "100"}
    assert extract_facts("бюджет: 200") == {"бюджет": "200"}


def test_quoted_value_is_unwrapped():
    assert extract_facts("Название: 'Портал'") == {"название": "Портал"}
    assert extract_facts('Название: "Портал"') == {"название": "Портал"}


def test_lines_without_separator_are_ignored():
    assert extract_facts("просто текст без разделителя") == {}
    assert extract_facts("Имя: Иван\nпросто текст\nБюджет: 5") == {
        "имя": "Иван",
        "бюджет": "5",
    }


def test_empty_and_non_string_input():
    assert extract_facts("") == {}
    assert extract_facts("   ") == {}
    assert extract_facts(None) == {}


def test_merge_facts_new_overrides_existing():
    merged = merge_facts({"имя": "Иван", "бюджет": "100"}, {"бюджет": "200"})
    assert merged == {"имя": "Иван", "бюджет": "200"}


def test_merge_facts_keeps_unrelated_keys():
    merged = merge_facts({"имя": "Иван"}, {"срок": "3 месяца"})
    assert merged == {"имя": "Иван", "срок": "3 месяца"}
