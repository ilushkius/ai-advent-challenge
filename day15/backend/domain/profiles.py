"""Профиль пользователя дня 15: сборка системного промпта из профиля.

Что здесь есть:

- ``PromptElement`` / ``ProfilePrompt`` — элемент промпта и готовый блок
  персонализации с разбивкой по элементам (для интерфейса и отчёта);
- ``build_profile_prompt`` — сборка системного промпта из профиля: обращение,
  стиль (tone), формат (format), длина (verbosity), язык, ограничения и
  произвольные инструкции. Возвращает и текст, и разбивку по элементам, чтобы
  интерфейс и отчёт показали, ЧТО именно повлияло на ответ;
- ``describe_profile`` / ``preference_options`` — человекочитаемое описание
  профиля и варианты значений для селекторов интерфейса.

Пустое поле (``None``/``""``) означает «пользователь это не настраивал» и в
промпт не попадает: профиль без единого заполненного поля даёт пустой промпт,
то есть агент отвечает без персонализации.

Значения профиля и их нормализация (перечисления, ``normalize_*``, границы
constraints, тексты инструкций) вынесены в ``backend/profile_values.py`` и
реэкспортируются отсюда: ``profile_store.py``, схемы API, скрипт сравнения и
тесты импортируют их из ``backend.domain.profiles``. Модуль намеренно не знает ни про
SQLAlchemy, ни про FastAPI, ни про Streamlit: только чистые функции и
dataclass'ы.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..core import config
from .profile_values import (
    CUSTOM_INSTRUCTION_EXAMPLE, DEFAULT_CONSTRAINTS, DEFAULT_PREFERENCES,
    FORMAT_INSTRUCTIONS, LANGUAGE_INSTRUCTIONS, PREFERENCE_OPTIONS,
    PROFILE_FIELD_LABELS, PROFILE_HEADER, TONE_INSTRUCTIONS,
    VERBOSITY_INSTRUCTIONS, ProfileValueError, ResponseFormat, Tone, Verbosity,
    instructions_text, normalize_constraints, normalize_instructions,
    normalize_preferences,
)



# ---------- сборка промпта ----------
@dataclass(frozen=True)
class PromptElement:
    """Один элемент профиля, попавший в системный промпт.

    ``field`` — машинное имя (``preferences.tone``), ``label`` — подпись для
    интерфейса и отчёта, ``value`` — человекочитаемое значение, ``text`` —
    ровно та строка, которая ушла в промпт.
    """

    field: str
    label: str
    value: str
    text: str


@dataclass(frozen=True)
class ProfilePrompt:
    """Готовый блок персонализации: текст + разбивка по элементам."""

    text: str
    elements: Tuple[PromptElement, ...] = ()

    @property
    def personalized(self) -> bool:
        """True, если профиль дал хотя бы один блок промпта."""
        return bool(self.text)

    def elements_as_dicts(self) -> List[Dict[str, str]]:
        """Элементы для JSON-ответа API/панели Streamlit."""
        return [
            {"field": item.field, "label": item.label, "value": item.value,
             "text": item.text}
            for item in self.elements
        ]


def _element(field_name: str, value: str, text: str) -> PromptElement:
    """Собирает элемент с подписью из PROFILE_FIELD_LABELS."""
    return PromptElement(
        field=field_name,
        label=PROFILE_FIELD_LABELS.get(field_name, field_name),
        value=value,
        text=text,
    )


def build_profile_prompt(
    name: str = "",
    preferences: Optional[Dict[str, Any]] = None,
    constraints: Optional[Dict[str, Any]] = None,
    custom_instructions: Any = "",
) -> ProfilePrompt:
    """Собирает системный промпт персонализации из полей профиля.

    Порядок блоков — как в требованиях дня 12: обращение (name), стиль (tone),
    формат (format), длина (verbosity), язык (language), ограничения
    (max_response_length, forbidden_topics, required_disclaimers) и
    произвольные инструкции. Незаполненные поля пропускаются: профиль без
    настроек даёт пустой промпт и агент отвечает как обычно.
    """
    prefs = normalize_preferences(preferences)
    cons = normalize_constraints(constraints)
    instructions = normalize_instructions(custom_instructions)

    elements: List[PromptElement] = []

    clean_name = (name or "").strip()
    if clean_name:
        elements.append(_element(
            "name", clean_name,
            f"Обращайся к пользователю по имени: {clean_name}.",
        ))
    if prefs["tone"]:
        elements.append(_element(
            "preferences.tone", prefs["tone"],
            TONE_INSTRUCTIONS[prefs["tone"]],
        ))
    if prefs["format"]:
        elements.append(_element(
            "preferences.format", prefs["format"],
            FORMAT_INSTRUCTIONS[prefs["format"]],
        ))
    if prefs["verbosity"]:
        elements.append(_element(
            "preferences.verbosity", prefs["verbosity"],
            VERBOSITY_INSTRUCTIONS[prefs["verbosity"]],
        ))
    if prefs["language"]:
        elements.append(_element(
            "preferences.language", prefs["language"],
            LANGUAGE_INSTRUCTIONS[prefs["language"]],
        ))
    if cons["max_response_length"]:
        limit = cons["max_response_length"]
        elements.append(_element(
            "constraints.max_response_length", str(limit),
            f"Жёсткое ограничение: весь ответ не длиннее {limit} символов.",
        ))
    if cons["forbidden_topics"]:
        topics = cons["forbidden_topics"]
        elements.append(_element(
            "constraints.forbidden_topics", ", ".join(topics),
            "Не обсуждай темы: " + ", ".join(topics)
            + ". Если запрос про них — вежливо откажись и предложи "
              "другую формулировку.",
        ))
    if cons["required_disclaimers"]:
        disclaimers = cons["required_disclaimers"]
        elements.append(_element(
            "constraints.required_disclaimers", "; ".join(disclaimers),
            "Всегда добавляй в ответ: " + "; ".join(disclaimers) + ".",
        ))
    if instructions:
        elements.append(_element(
            "custom_instructions", " | ".join(instructions),
            "Дополнительные инструкции пользователя (выполняй буквально):\n"
            + "\n".join(f"- {item}" for item in instructions),
        ))

    if not elements:
        return ProfilePrompt(text="", elements=())

    text = "\n".join(
        [PROFILE_HEADER] + [item.text for item in elements]
    )
    return ProfilePrompt(text=text, elements=tuple(elements))


def describe_profile(
    name: str = "",
    preferences: Optional[Dict[str, Any]] = None,
    constraints: Optional[Dict[str, Any]] = None,
    custom_instructions: Any = "",
) -> str:
    """Однострочное описание профиля для селектора в интерфейсе и отчёта."""
    prefs = normalize_preferences(preferences)
    cons = normalize_constraints(constraints)
    instructions = normalize_instructions(custom_instructions)

    parts: List[str] = []
    if (name or "").strip():
        parts.append((name or "").strip())
    style = "/".join(
        str(prefs[key]) for key in ("tone", "verbosity", "language", "format")
        if prefs[key]
    )
    if style:
        parts.append(style)
    if cons["max_response_length"]:
        parts.append(f"≤{cons['max_response_length']} символов")
    if cons["forbidden_topics"]:
        parts.append("запреты: " + ", ".join(cons["forbidden_topics"]))
    if cons["required_disclaimers"]:
        parts.append(f"дисклеймеров: {len(cons['required_disclaimers'])}")
    if instructions:
        parts.append(f"инструкций: {len(instructions)}")
    return " · ".join(parts) if parts else "без настроек"


def preference_options() -> Dict[str, List[str]]:
    """Варианты значений полей preferences для интерфейса (порядок сохранён)."""
    return {
        key: list(values) for key, values in PREFERENCE_OPTIONS.items()
    }
