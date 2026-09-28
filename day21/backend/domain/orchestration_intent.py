"""Распознавание реплики «выполни флоу по нескольким серверам» (день 20).

Правило узкое намеренно. Реплика дня 19 «найди статьи про RAG, сделай сводку и
сохрани в файл» ОБЯЗАНА остаться пайплайном (её контракт закреплён тестом), а
требование дня 20 — «найди данные и сохрани в БД» — должно попадать в оркестрацию,
потому что пайплайн умеет писать только файл. Поэтому оркестрация срабатывает
только на явный признак:

- сохранение именно в базу/БД/sqlite (``в базу``, ``в бд``, ``в sqlite``), или
- прямое упоминание оркестрации как таковой (``оркестрац``, ``несколько серверов``,
  ``разными серверами``, ``цепочк``).

Во всех остальных случаях классификатор возвращает ``None``, и ход идёт прежними
путями (пайплайн → шаг MCP).

Запрос и имя файла берутся у пайплайна (``pipeline_query``, ``pipeline_filename``):
эвристика этих значений одна на день, и расходиться ей незачем — иначе одна и та же
реплика давала бы разные имена файлов в двух механизмах.

Модуль чистый: ``re`` и стандартная библиотека.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .orchestration_spec import DEFAULT_FILENAME, filename_for, launch_arguments
from .pipeline_intent import pipeline_query
from .schedule_intent import _pattern  # шаблон фразы: граница слова + окончание

#: Фразы-триггеры оркестрации: сохранение в базу или явное упоминание флоу.
ORCH_PHRASES: tuple[str, ...] = (
    "в базу",
    "в бд",
    "в базу данных",
    "в sqlite",
    "оркестрац",
    "несколько серверов",
    "нескольких серверов",
    "разными серверами",
    "разных серверов",
    "флот серверов",
    "флота серверов",
    "цепочк",
)

#: Шаблоны фраз (по одному на фразу: сработавшая фраза уходит в отчёт).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (phrase, _pattern(phrase)) for phrase in ORCH_PHRASES
)

#: Границы аргументов запуска: те же значения, что у инструментов флота.
DEFAULT_LIMIT = 5
DEFAULT_FORMAT = "md"
DEFAULT_FILE_NAME = DEFAULT_FILENAME


@dataclass(frozen=True, slots=True)
class OrchestrationIntent:
    """Что решила эвристика: запрос, аргументы запуска и сработавшие фразы."""

    query: str
    arguments: dict
    phrases: tuple[str, ...]

    def to_dict(self) -> dict:
        """Отчёт для API/UI: запрос, аргументы и сработавшие фразы."""
        return {
            "query": self.query,
            "arguments": dict(self.arguments),
            "phrases": list(self.phrases),
        }


def classify_orchestration_intent(text: str) -> Optional[OrchestrationIntent]:
    """Намерение оркестрации по реплике (``None`` — это не про флот серверов)."""
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    found = tuple(phrase for phrase, pattern in _PATTERNS if pattern.search(lowered))
    if not found:
        return None
    query = orchestration_query(text or "")
    return OrchestrationIntent(
        query=query,
        arguments=orchestration_arguments(query),
        phrases=found,
    )


def orchestration_query(text: str) -> str:
    """Запрос поиска из реплики (та же эвристика, что у пайплайна)."""
    return pipeline_query(text)


def orchestration_filename(query: str, fmt: str = DEFAULT_FORMAT) -> str:
    """Имя файла по запросу: «RAG» → ``rag.md`` (умолчание дня — ``filename_for``)."""
    return filename_for(query, fmt)


def orchestration_arguments(query: str) -> dict:
    """Аргументы запуска плана: запрос, предел выборки, имя файла и формат.

    Умолчания живут в домене плана (``launch_arguments``): служба оркестрации
    подставляет их и для реплики из чата, и для запроса без аргументов, поэтому
    второй набор умолчаний здесь разошёлся бы с первым.
    """
    return launch_arguments(query)
