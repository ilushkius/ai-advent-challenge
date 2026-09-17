"""Значения профиля пользователя дня 14: перечисления и нормализация.

Модуль намеренно не знает ни про SQLAlchemy, ни про FastAPI, ни про Streamlit:
здесь только данные и чистые функции, поэтому вся валидация персонализации
проверяется модульными тестами без БД и без сети (конвенция AGENTS.md).

Что здесь есть:

- ``Tone`` / ``Verbosity`` / ``Language`` / ``ResponseFormat`` — допустимые
  значения полей профиля (``enum.Enum``, значения — человекочитаемые строки:
  они же попадают в UI, в промпт и в отчёт без дополнительного маппинга);
- ``PREFERENCE_ENUMS`` / ``PREFERENCE_OPTIONS`` / ``CONSTRAINT_FIELDS`` /
  ``DEFAULT_*`` — состав полей и их значения по умолчанию («не задано»);
- тексты инструкций (``TONE_INSTRUCTIONS`` … ``LANGUAGE_INSTRUCTIONS``),
  подписи полей (``PROFILE_FIELD_LABELS``), заголовок блока персонализации
  (``PROFILE_HEADER``) и пример произвольной инструкции;
- ``normalize_preferences`` / ``normalize_constraints`` /
  ``normalize_instructions`` / ``instructions_text`` — валидация и приведение
  значений к каноническому виду (неизвестное значение → ``ProfileValueError``,
  а не «тихое» игнорирование).

Сборка блока персонализации для системного промпта живёт в
``backend/profiles.py``; этот модуль реэкспортируется им, поэтому остальной код
дня импортирует имена по-прежнему из ``backend.domain.profiles``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core import config


class ProfileValueError(Exception):
    """Невалидное поле профиля (неизвестное значение перечисления, границы)."""


# ---------- допустимые значения полей профиля ----------
class Tone(str, Enum):
    """Стиль общения (preferences.tone)."""

    FORMAL = "формальный"
    FRIENDLY = "дружелюбный"
    TECHNICAL = "технический"


class Verbosity(str, Enum):
    """Длина ответа (preferences.verbosity)."""

    BRIEF = "кратко"
    DETAILED = "подробно"
    BALANCED = "сбалансировано"


class Language(str, Enum):
    """Язык ответа (preferences.language)."""

    RU = "русский"
    EN = "английский"


class ResponseFormat(str, Enum):
    """Формат ответа (preferences.format)."""

    MARKDOWN = "markdown"
    PLAIN = "plain text"
    STRUCTURED = "структурированный"


# Поля preferences и их допустимые значения (Enum). Порядок ключей — порядок
# отображения в интерфейсе и порядок блоков в промпте.
PREFERENCE_ENUMS: Dict[str, type] = {
    "tone": Tone,
    "format": ResponseFormat,
    "verbosity": Verbosity,
    "language": Language,
}

# Готовые списки вариантов для селекторов интерфейса (значения Enum строками).
PREFERENCE_OPTIONS: Dict[str, List[str]] = {
    key: [member.value for member in enum_cls]
    for key, enum_cls in PREFERENCE_ENUMS.items()
}

# Поля constraints и их обработчики (см. normalize_constraints).
CONSTRAINT_FIELDS: Tuple[str, ...] = (
    "max_response_length", "forbidden_topics", "required_disclaimers",
)

# Пустые значения по умолчанию: «не задано» — значит «не персонализировать».
DEFAULT_PREFERENCES: Dict[str, Optional[str]] = {
    key: None for key in PREFERENCE_ENUMS
}
DEFAULT_CONSTRAINTS: Dict[str, Any] = {
    "max_response_length": None,
    "forbidden_topics": [],
    "required_disclaimers": [],
}

# Инструкции, которые уходят в промпт для каждого значения поля.
TONE_INSTRUCTIONS = {
    Tone.FORMAL.value: (
        "Стиль общения: формальный — на «Вы», без сленга и эмодзи, "
        "официальные формулировки."
    ),
    Tone.FRIENDLY.value: (
        "Стиль общения: дружелюбный — тепло и просто, уместны эмодзи и "
        "обращение к собеседнику напрямую."
    ),
    Tone.TECHNICAL.value: (
        "Стиль общения: технический — точные термины и конкретика, "
        "без вводных фраз, эмодзи и «воды»."
    ),
}
FORMAT_INSTRUCTIONS = {
    ResponseFormat.MARKDOWN.value: (
        "Формат ответа: markdown — заголовки, списки, блоки кода."
    ),
    ResponseFormat.STRUCTURED.value: (
        "Формат ответа: структурированный — нумерованные разделы с подписями "
        "(например: 1. Анализ, 2. Решение, 3. Проверка)."
    ),
    ResponseFormat.PLAIN.value: (
        "Формат ответа: plain text — простой текст без markdown-разметки."
    ),
}
VERBOSITY_INSTRUCTIONS = {
    Verbosity.BRIEF.value: (
        "Длина ответа: кратко — только суть, без прелюдий и повторов."
    ),
    Verbosity.DETAILED.value: (
        "Длина ответа: подробно — с пояснениями, примерами и обоснованием."
    ),
    Verbosity.BALANCED.value: (
        "Длина ответа: сбалансированно — суть плюс короткое пояснение "
        "ключевых мест."
    ),
}
LANGUAGE_INSTRUCTIONS = {
    Language.RU.value: "Язык ответа: русский.",
    Language.EN.value: "Язык ответа: английский — отвечай на английском.",
}

# Человекочитаемые подписи полей (UI, отчёт, ответ API).
PROFILE_FIELD_LABELS = {
    "name": "обращение",
    "preferences.tone": "стиль (tone)",
    "preferences.format": "формат (format)",
    "preferences.verbosity": "длина (verbosity)",
    "preferences.language": "язык (language)",
    "constraints.max_response_length": "ограничение длины",
    "constraints.forbidden_topics": "запрещённые темы",
    "constraints.required_disclaimers": "обязательные дисклеймеры",
    "custom_instructions": "инструкции пользователя",
}

# Заголовок блока персонализации в системном промпте.
PROFILE_HEADER = "Профиль пользователя (персонализация; соблюдай в каждом ответе):"

# Подсказка-пример для UI: как выглядит произвольная инструкция.
CUSTOM_INSTRUCTION_EXAMPLE = (
    "При запросе «напиши фичу» следуй порядку: аналитик → разработчик → "
    "тестировщик"
)


# ---------- нормализация данных профиля ----------
def _coerce_enum(field_name: str, enum_cls: type, value: Any) -> Optional[str]:
    """Проверяет значение перечисления; None/"" → «не задано»."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProfileValueError(
            f"{field_name}: ожидалась строка, получено {type(value).__name__}"
        )
    value = value.strip()
    if not value:
        return None
    allowed = [member.value for member in enum_cls]
    if value not in allowed:
        raise ProfileValueError(
            f"{field_name}: неизвестное значение {value!r}; допустимые: "
            f"{', '.join(allowed)}"
        )
    return value


def normalize_preferences(raw: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Приводит preferences к каноническому виду (4 ключа, значения или None)."""
    if raw is None:
        return dict(DEFAULT_PREFERENCES)
    if not isinstance(raw, dict):
        raise ProfileValueError(
            f"preferences: ожидался объект, получено {type(raw).__name__}"
        )
    unknown = sorted(set(raw) - set(PREFERENCE_ENUMS))
    if unknown:
        raise ProfileValueError(
            f"preferences: неизвестные поля {', '.join(unknown)}; допустимые: "
            f"{', '.join(PREFERENCE_ENUMS)}"
        )
    return {
        key: _coerce_enum(f"preferences.{key}", enum_cls, raw.get(key))
        for key, enum_cls in PREFERENCE_ENUMS.items()
    }


def _normalize_string_list(field_name: str, value: Any, max_items: int,
                           item_max: int) -> List[str]:
    """Список непустых строк без дублей (порядок сохраняется), с границами."""
    if value is None:
        return []
    if isinstance(value, str):
        # Одиночная строка допустима: «политика, религия» → два значения.
        items: Iterable[Any] = [part for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise ProfileValueError(
            f"{field_name}: ожидался список строк, получено "
            f"{type(value).__name__}"
        )
    result: List[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ProfileValueError(f"{field_name}: элементы должны быть строками")
        text = item.strip()
        if not text:
            continue
        if len(text) > item_max:
            raise ProfileValueError(
                f"{field_name}: значение длиннее {item_max} символов"
            )
        if text not in result:
            result.append(text)
    if len(result) > max_items:
        raise ProfileValueError(
            f"{field_name}: не больше {max_items} значений"
        )
    return result


def normalize_constraints(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Приводит constraints к каноническому виду (3 ключа с валидацией)."""
    if raw is None:
        return {
            "max_response_length": None,
            "forbidden_topics": [],
            "required_disclaimers": [],
        }
    if not isinstance(raw, dict):
        raise ProfileValueError(
            f"constraints: ожидался объект, получено {type(raw).__name__}"
        )
    unknown = sorted(set(raw) - set(CONSTRAINT_FIELDS))
    if unknown:
        raise ProfileValueError(
            f"constraints: неизвестные поля {', '.join(unknown)}; допустимые: "
            f"{', '.join(CONSTRAINT_FIELDS)}"
        )

    limit = raw.get("max_response_length")
    if limit is None or (isinstance(limit, str) and not limit.strip()):
        limit = None
    else:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ProfileValueError(
                "constraints.max_response_length: ожидалось целое число символов"
            )
        if not (config.MAX_RESPONSE_LENGTH_MIN <= limit
                <= config.MAX_RESPONSE_LENGTH_MAX):
            raise ProfileValueError(
                "constraints.max_response_length: допустимо "
                f"{config.MAX_RESPONSE_LENGTH_MIN}.."
                f"{config.MAX_RESPONSE_LENGTH_MAX} символов"
            )

    return {
        "max_response_length": limit,
        "forbidden_topics": _normalize_string_list(
            "constraints.forbidden_topics", raw.get("forbidden_topics"),
            config.FORBIDDEN_TOPICS_MAX, config.TOPIC_MAX,
        ),
        "required_disclaimers": _normalize_string_list(
            "constraints.required_disclaimers", raw.get("required_disclaimers"),
            config.DISCLAIMERS_MAX, config.DISCLAIMER_MAX,
        ),
    }


def normalize_instructions(raw: Any) -> List[str]:
    """Превращает текст ``custom_instructions`` в список инструкций.

    Одна инструкция — одна строка текста; маркеры списка («-», «*», «1.») и
    пустые строки отбрасываются, дубликаты схлопываются. Так одна и та же
    запись профиля читается и человеком в интерфейсе, и агентом.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        lines: Iterable[Any] = raw
    elif isinstance(raw, str):
        lines = raw.splitlines()
    else:
        raise ProfileValueError(
            "custom_instructions: ожидалась строка или список строк, получено "
            f"{type(raw).__name__}"
        )
    result: List[str] = []
    for line in lines:
        if not isinstance(line, str):
            raise ProfileValueError(
                "custom_instructions: элементы должны быть строками"
            )
        text = line.strip().lstrip("-*•").strip()
        if len(text) > 1 and text[0].isdigit() and text[1] in ".)":
            text = text[2:].strip()
        if not text:
            continue
        if len(text) > config.INSTRUCTION_MAX:
            raise ProfileValueError(
                f"custom_instructions: инструкция длиннее "
                f"{config.INSTRUCTION_MAX} символов"
            )
        if text not in result:
            result.append(text)
    if len(result) > config.CUSTOM_INSTRUCTIONS_MAX_ITEMS:
        raise ProfileValueError(
            "custom_instructions: не больше "
            f"{config.CUSTOM_INSTRUCTIONS_MAX_ITEMS} инструкций"
        )
    return result


def instructions_text(instructions: Sequence[str]) -> str:
    """Список инструкций → текст для поля ``custom_instructions`` (по строке)."""
    return "\n".join(instructions)
