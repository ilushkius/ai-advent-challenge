"""Распознавание реплики «собери пайплайн» (день 19).

Эвристика по ключевым словам — тот же приём, что в днях 17/18
(``mcp_intent.py``, ``schedule_intent.py``): решение об инструменте принимается
детерминированно и проверяется офлайн. Причина та же: вызов инструментов оставляет
побочные эффекты (у пайплайна — файл в ``output/`` и запись в истории запусков), и
делать это по догадке модели нельзя.

Намерение считается пайплайном только когда в реплике есть фразы ВСЕХ ТРЁХ групп:
поиск, сводка и сохранение. «Найди статьи про RAG» — это одиночный вызов
инструмента (день 17), «найди, сделай сводку и сохрани в файл» — пайплайн.

Из реплики достаются аргументы запуска: запрос (оборот «про …»), источник (слова
про пользователей/посты, иначе — заметки дня), стиль (подробный конспект или
краткий), формат файла (json/txt/md) и имя файла по запросу.

Модуль чистый: домен и стандартная библиотека.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Optional

from .pipeline_spec import DEFAULT_PIPELINE, FILE_SOURCE_DEFAULT
from .schedule_intent import _pattern  # шаблон фразы: граница слова + окончание

#: Фразы трёх действий пайплайна. Хвосты окончаний допускает шаблон, а не список
#: словоформ: «сводк» ловит «сводка/сводку/сводке».
SEARCH_PHRASES = ("найди", "поищи", "найти", "ищи", "собери")
SUMMARY_PHRASES = ("сводк", "суммир", "кратк", "конспект", "итог")
SAVE_PHRASES = ("сохрани", "сохранить", "запиши", "в файл", "файл")

_PATTERNS: tuple[tuple[tuple[str, ...], tuple[re.Pattern[str], ...]], ...] = tuple(
    (phrases, tuple(_pattern(phrase) for phrase in phrases))
    for phrases in (SEARCH_PHRASES, SUMMARY_PHRASES, SAVE_PHRASES)
)

#: Оборот, из которого берётся запрос: «найди статьи про RAG» → «RAG».
_QUERY = re.compile(r"(?<![а-яёa-z])(?:про|о|об|по теме|на тему)\s+([^,.!?;:]{2,60})",
                   re.IGNORECASE)

#: Границы аргументов запуска: те же значения, что у инструментов сервера.
DEFAULT_LIMIT = 5
DEFAULT_MAX_LENGTH = 600
DEFAULT_FILE_NAME = "pipeline"

#: Признаки источника в реплике.
_USER_WORDS = ("пользовател", "юзер")
_API_WORDS = ("пост", "jsonplaceholder", "внешн")


@dataclass(frozen=True, slots=True)
class PipelineIntent:
    """Что решила эвристика: конфигурация пайплайна, аргументы запуска и фразы."""

    pipeline: dict
    arguments: dict
    phrases: tuple[str, ...]

    def to_dict(self) -> dict:
        """Отчёт для API/UI: конфигурация, аргументы и сработавшие фразы."""
        return {
            "pipeline": copy.deepcopy(self.pipeline),
            "arguments": dict(self.arguments),
            "phrases": list(self.phrases),
        }


def classify_pipeline_intent(text: str) -> Optional[PipelineIntent]:
    """Намерение пайплайна по реплике (``None`` — реплика говорит не о композиции)."""
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    found: list[str] = []
    for phrases, patterns in _PATTERNS:
        hit = _first_hit(lowered, phrases, patterns)
        if hit is None:
            return None
        found.append(hit)
    query = pipeline_query(text or "")
    fmt = pipeline_format(lowered)
    arguments = {
        "query": query,
        "source": pipeline_source(lowered),
        "limit": DEFAULT_LIMIT,
        "style": pipeline_style(lowered),
        "max_length": DEFAULT_MAX_LENGTH,
        "filename": pipeline_filename(query, fmt),
        "format": fmt,
    }
    return PipelineIntent(
        pipeline=copy.deepcopy(DEFAULT_PIPELINE),
        arguments=arguments,
        phrases=tuple(found),
    )


def _first_hit(text: str, phrases: tuple[str, ...],
               patterns: tuple[re.Pattern[str], ...]) -> Optional[str]:
    """Первая сработавшая фраза группы (в порядке объявления группы)."""
    for phrase, pattern in zip(phrases, patterns):
        if pattern.search(text):
            return phrase
    return None


def pipeline_query(text: str) -> str:
    """Запрос поиска из реплики.

    Сначала — оборот «про …» (он и есть предмет поиска; регистр сохраняется: «Про
    RAG» даёт запрос ``RAG``), иначе реплика без сработавших фраз, первые пять слов.
    Пустой результат — «данные»: инструменту нужно что-то осмысленное, а «» означало
    бы «верни всё».
    """
    match = _QUERY.search(text or "")
    if match:
        value = match.group(1).strip()
        if value:
            return value
    words = [
        word for word in re.split(r"[\s,;:.!?]+", (text or "").lower())
        if word and not _is_trigger(word)
    ]
    return " ".join(words[:5]) or "данные"


def _is_trigger(word: str) -> bool:
    """Служебное слово пайплайна: в запрос поиска оно не попадает."""
    return any(
        pattern.fullmatch(word)
        for phrases, patterns in _PATTERNS
        for pattern in patterns
    )


def pipeline_source(text: str) -> str:
    """Источник: пользователи, посты внешнего API или заметки дня (по умолчанию)."""
    for word in _USER_WORDS:
        if _pattern(word).search(text or ""):
            return "users"
    for word in _API_WORDS:
        if _pattern(word).search(text or ""):
            return "posts"
    return FILE_SOURCE_DEFAULT


def pipeline_style(text: str) -> str:
    """Стиль сводки: «подробн» в реплике — подробная сводка, иначе краткая."""
    return "detailed" if _pattern("подробн").search(text or "") else "short"


def pipeline_format(text: str) -> str:
    """Формат файла: json, txt («текст») или md по умолчанию."""
    lowered = (text or "").lower()
    # Слово «json» целиком: подстрока поймала бы «jsonplaceholder» — источник постов
    # молча менял бы формат вывода на json.
    if _pattern("json").search(lowered):
        return "json"
    if _pattern("txt").search(lowered) or _pattern("текст").search(lowered):
        return "txt"
    return "md"


def pipeline_filename(query: str, fmt: str) -> str:
    """Имя файла по запросу: «RAG» + ``md`` → ``rag.md``.

    Имя чистит ``file_writer`` (путь и ``..`` там запрещены), здесь оно только
    приводится к машинному виду: пробелы и знаки — в дефис, регистр — нижний.
    """
    stem = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", query or "").strip("-").lower()
    return f"{stem or DEFAULT_FILE_NAME}.{fmt}"
