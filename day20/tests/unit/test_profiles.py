"""Тесты чистых правил профиля (день 13, ``backend/profiles.py``).

Проверяется то, от чего зависит персонализация: какие значения допустимы,
что попадает в системный промпт и в каком порядке, и что пустой профиль не
добавляет в промпт ничего (агент отвечает как обычно).
"""
import pytest

from backend.domain.profiles import (
    CUSTOM_INSTRUCTION_EXAMPLE, PROFILE_HEADER, ProfileValueError, ResponseFormat,
    Tone, Verbosity, build_profile_prompt, describe_profile,
    normalize_constraints, normalize_instructions, normalize_preferences,
    preference_options,
)


# ---------- нормализация preferences ----------
def test_empty_preferences_are_all_unset():
    """Профиль без настроек: все поля None, промпт пустой."""
    assert normalize_preferences(None) == {
        "tone": None, "format": None, "verbosity": None, "language": None,
    }
    prompt = build_profile_prompt()
    assert prompt.text == ""
    assert prompt.elements == ()
    assert prompt.personalized is False


def test_blank_values_are_treated_as_unset():
    """Пробелы вместо значения — это «не задано», а не ошибка."""
    prefs = normalize_preferences({"tone": "  ", "format": None})
    assert prefs["tone"] is None
    assert prefs["format"] is None


@pytest.mark.parametrize("tone,needle", [
    (Tone.FORMAL.value, "формальный"),
    (Tone.FRIENDLY.value, "дружелюбный"),
    (Tone.TECHNICAL.value, "технический"),
])
def test_every_tone_value_renders_its_own_block(tone, needle):
    """Каждое значение tone даёт свой блок промпта (Enum → текст без маппинга)."""
    prompt = build_profile_prompt(preferences={"tone": tone})
    assert prompt.personalized
    assert needle in prompt.text
    assert [element.field for element in prompt.elements] == ["preferences.tone"]


@pytest.mark.parametrize("verbosity", [item.value for item in Verbosity])
def test_every_verbosity_value_is_accepted(verbosity):
    prompt = build_profile_prompt(preferences={"verbosity": verbosity})
    assert len(prompt.elements) == 1
    assert prompt.elements[0].value == verbosity


@pytest.mark.parametrize("response_format", [item.value for item in ResponseFormat])
def test_every_format_value_is_accepted(response_format):
    prompt = build_profile_prompt(preferences={"format": response_format})
    assert prompt.elements[0].value == response_format


@pytest.mark.parametrize("bad", [
    {"tone": "токсичный"},
    {"format": "yaml"},
    {"verbosity": "средне"},
    {"language": "немецкий"},
    {"скорость": "быстро"},
    {"tone": 5},
])
def test_invalid_preferences_rejected(bad):
    """Неизвестное значение или поле — явная ошибка, а не тихий игнор."""
    with pytest.raises(ProfileValueError):
        normalize_preferences(bad)


# ---------- нормализация constraints ----------
def test_empty_constraints_have_no_limits():
    assert normalize_constraints(None) == {
        "max_response_length": None, "forbidden_topics": [],
        "required_disclaimers": [],
    }


def test_constraint_lists_are_deduplicated_and_trimmed():
    """Список тем: пробелы срезаны, дубликаты убраны, порядок сохранён."""
    cons = normalize_constraints({
        "forbidden_topics": [" политика ", "религия", "политика", ""],
    })
    assert cons["forbidden_topics"] == ["политика", "религия"]


def test_constraint_string_is_split_by_commas():
    """Строку «политика, религия» можно передать вместо списка."""
    cons = normalize_constraints({"forbidden_topics": "политика, религия"})
    assert cons["forbidden_topics"] == ["политика", "религия"]


@pytest.mark.parametrize("limit", [0, 19, 100000, True, 12.5, "600"])
def test_max_response_length_outside_bounds_rejected(limit):
    """Границы длины ответа — из config; строка/bool/drob — не число символов."""
    with pytest.raises(ProfileValueError):
        normalize_constraints({"max_response_length": limit})


def test_constraints_unknown_field_rejected():
    with pytest.raises(ProfileValueError):
        normalize_constraints({"max_words": 100})


def test_too_many_topics_rejected():
    with pytest.raises(ProfileValueError):
        normalize_constraints({
            "forbidden_topics": [f"тема-{index}" for index in range(25)],
        })


# ---------- нормализация инструкций ----------
def test_instructions_accept_bullets_numbering_and_blank_lines():
    """Маркеры списка и нумерация снимаются, пустые строки и дубли — прочь."""
    instructions = normalize_instructions(
        "- Обращайся ко мне по имени\n"
        "\n"
        "1. Всегда предлагай два варианта решения\n"
        "* Обращайся ко мне по имени\n"
    )
    assert instructions == [
        "Обращайся ко мне по имени",
        "Всегда предлагай два варианта решения",
    ]


def test_instruction_too_long_rejected():
    with pytest.raises(ProfileValueError):
        normalize_instructions("а" * 600)


def test_instructions_list_accepted():
    """Инструкции можно передать списком (а не только текстом)."""
    assert normalize_instructions(["Первая", "Вторая"]) == ["Первая", "Вторая"]


# ---------- сборка системного промпта ----------
def test_prompt_order_and_fields():
    """Порядок блоков: обращение → стиль → формат → длина → язык → ограничения
    → произвольные инструкции."""
    prompt = build_profile_prompt(
        name="Илья",
        preferences={
            "tone": Tone.TECHNICAL.value, "format": ResponseFormat.PLAIN.value,
            "verbosity": Verbosity.BRIEF.value, "language": "русский",
        },
        constraints={
            "max_response_length": 600,
            "forbidden_topics": ["политика"],
            "required_disclaimers": ["Это оценка, а не гарантия"],
        },
        custom_instructions="Всегда предлагай два варианта решения",
    )
    assert [element.field for element in prompt.elements] == [
        "name", "preferences.tone", "preferences.format",
        "preferences.verbosity", "preferences.language",
        "constraints.max_response_length", "constraints.forbidden_topics",
        "constraints.required_disclaimers", "custom_instructions",
    ]
    lines = prompt.text.splitlines()
    assert lines[0] == PROFILE_HEADER
    assert lines[1] == "Обращайся к пользователю по имени: Илья."
    assert "600 символов" in prompt.text
    assert "политика" in prompt.text
    assert "Это оценка, а не гарантия" in prompt.text
    assert prompt.text.endswith("- Всегда предлагай два варианта решения")


def test_prompt_block_for_orchestrator_instruction():
    """Инструкция из задания дня 12 попадает в промпт дословно."""
    prompt = build_profile_prompt(
        custom_instructions=(
            "При запросе «напиши фичу» следуй порядку: аналитик → разработчик → "
            "тестировщик"
        ),
    )
    assert prompt.text.endswith(
        "- При запросе «напиши фичу» следуй порядку: аналитик → разработчик → "
        "тестировщик"
    )


def test_unnamed_profile_has_no_greeting_block():
    prompt = build_profile_prompt(name="   ", preferences={"tone": "формальный"})
    assert "по имени" not in prompt.text
    assert [element.field for element in prompt.elements] == ["preferences.tone"]


def test_elements_carry_label_value_and_text():
    """Разбивка по элементам нужна отчёту: подпись, значение и строка промпта."""
    prompt = build_profile_prompt(preferences={"verbosity": "кратко"})
    element = prompt.elements[0]
    assert element.label == "длина (verbosity)"
    assert element.value == "кратко"
    assert element.text == prompt.text.splitlines()[1]
    assert prompt.elements_as_dicts()[0]["field"] == "preferences.verbosity"


def test_describe_profile_skips_unset_fields():
    described = describe_profile(
        name="Илья", preferences={"tone": "технический", "verbosity": "кратко"},
        constraints={"max_response_length": 600},
        custom_instructions="Обращайся ко мне по имени",
    )
    assert described == "Илья · технический/кратко · ≤600 символов · инструкций: 1"
    assert describe_profile() == "без настроек"


def test_preference_options_match_enum_values():
    options = preference_options()
    assert options["tone"] == [item.value for item in Tone]
    assert options["format"] == [item.value for item in ResponseFormat]
    # Копия: правка возвращённого словаря не должна менять константу модуля.
    options["tone"].append("лишнее")
    assert "лишнее" not in preference_options()["tone"]


def test_custom_instruction_example_is_a_real_instruction():
    """Пример для подсказки в UI — валидная инструкция (её можно сохранить)."""
    assert normalize_instructions(CUSTOM_INSTRUCTION_EXAMPLE) == [
        CUSTOM_INSTRUCTION_EXAMPLE
    ]
