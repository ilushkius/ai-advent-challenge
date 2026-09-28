"""Источники документов дня 21: что именно индексируется и как это описано данными.

Набор документов — это ДАННЫЕ, а не код: таблица ``DOCUMENT_SOURCES`` перечисляет
файлы репозитория (путь от корня, вид, предел символов), а ``DocumentLoader``
собирает из них папку ``documents/`` папки дня. Поэтому «что мы индексируем»
видно в одном месте, а добавление источника — правка строки таблицы.

Почему источники именно такие: PDF-генерация потянула бы новую зависимость, а
внешние статьи — сеть и лицензии. Роль «статей» играют собственные документы
репозитория: README дней, `docs/architecture.md` трёх дней, четыре исходника
(конспект FSM, политика сжатия, граф переходов, маппинг пайплайна) и корневые
`AGENTS.md` + `README.md`. Пределы ``max_chars`` подобраны так, чтобы в индекс
попали осмысленные начала файлов (README дня 20 весит 285 КБ — целиком он бы
задавил остальные источники).

Модуль чистый: только стандартная библиотека и ``pathlib``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Виды источников (они же — группы в отчёте).
KIND_README = "readme"
KIND_DOCS = "docs"
KIND_CODE = "code"
KIND_GUIDE = "guide"

#: Доля кириллицы, выше которой текст считается русскоязычным.
CYRILLIC_RATIO = 0.15

#: Расширения, которые документ-загрузчик принимает за документы.
DOCUMENT_SUFFIXES = (".md", ".txt", ".py")

#: Маркер усечения: дописывается в конец обрезанного документа.
TRUNCATION_MARKER = "\n\n<!-- документ усечён -->"


@dataclass(frozen=True)
class DocumentSource:
    """Описание одного источника: путь от корня репозитория и предел символов."""

    path: str
    kind: str
    max_chars: int


@dataclass(frozen=True)
class Document:
    """Собранный документ папки ``documents/`` — вход чанкинга и эмбеддингов."""

    source: str
    path: Path
    title: str
    kind: str
    language: str
    text: str
    chars: int
    truncated: bool


def _readme(path: str, max_chars: int) -> DocumentSource:
    """Источник-README дня."""
    return DocumentSource(path=path, kind=KIND_README, max_chars=max_chars)


def _docs(path: str, max_chars: int = 6000) -> DocumentSource:
    """Источник из ``docs/`` дня."""
    return DocumentSource(path=path, kind=KIND_DOCS, max_chars=max_chars)


def _code(path: str, max_chars: int = 12000) -> DocumentSource:
    """Источник-исходник дня (структурный чанкинг проверяется на нём)."""
    return DocumentSource(path=path, kind=KIND_CODE, max_chars=max_chars)


#: Таблица источников: 25 записей (шестнадцать README, три docs, четыре кода, два guide).
DOCUMENT_SOURCES: tuple[DocumentSource, ...] = (
    # README дней 5–12: короткие снимки, целиком по 2000 символов.
    *(_readme(f"day{day}/README.md", 2000) for day in range(5, 13)),
    # README дней 13–17: разложенные по слоям дни, по 4000 символов.
    *(_readme(f"day{day}/README.md", 4000) for day in range(13, 18)),
    # README дней 18–20: планировщик, пайплайн и оркестрация, по 8000 символов.
    *(_readme(f"day{day}/README.md", 8000) for day in range(18, 21)),
    # Документация устройства: конспект дня 9, слои дня 13, оркестрация дня 20.
    _docs("day9/docs/architecture.md"),
    _docs("day13/docs/architecture.md"),
    _docs("day20/docs/architecture.md"),
    # Исходники, на которых структурный чанкинг режет по `ast`-секциям.
    _code("day9/backend/context_fsm.py"),
    _code("day9/backend/context_policy.py"),
    _code("day15/backend/domain/task_state_machine.py"),
    _code("day20/backend/domain/pipeline_mapping.py"),
    # Корневые документы проекта: правила и обзор челленджа.
    DocumentSource(path="AGENTS.md", kind=KIND_GUIDE, max_chars=8000),
    DocumentSource(path="README.md", kind=KIND_GUIDE, max_chars=5000),
)


def source_slug(path: str) -> str:
    """Имя файла-документа в ``documents/`` по пути источника.

    ``day9/backend/context_fsm.py`` → ``day9-backend-context_fsm.py``: слэши
    заменяются дефисами, регистр приводится к нижнему — имя документа остаётся
    читаемым и однозначным (``day20/README.md`` → ``day20-readme.md``).
    """
    return path.strip().lower().replace("/", "-")


def detect_language(text: str) -> str:
    """Язык текста по доле кириллицы: ``"ru"`` или ``"en"``."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "en"
    cyrillic = sum(1 for char in letters if "\u0400" <= char <= "\u04ff")
    return "ru" if cyrillic / len(letters) > CYRILLIC_RATIO else "en"


def detect_title(text: str, kind: str, slug: str) -> str:
    """Заголовок документа: первый заголовок markdown или докстринг модуля.

    Запасной вариант — имя файла без расширения (``slug``): заголовок нужен
    каждому чанку, и «пусто» в этой колонке было бы дырой в метаданных. У кода
    заголовок берётся ТОЛЬКО из докстринга: строка-комментарий ``# ...`` в Python
    к заголовку документа отношения не имеет.
    """
    stripped = text.lstrip()
    if kind == KIND_CODE:
        return _module_docstring_line(stripped) or Path(slug).stem
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate.startswith("#"):
            continue
        heading = candidate.lstrip("#").strip()
        if heading:
            return heading
    return Path(slug).stem


def _module_docstring_line(text: str) -> str:
    """Первая строка модульного докстринга Python-файла (``""`` — докстринга нет)."""
    for quote in ('"""', "'''"):
        if not text.startswith(quote):
            continue
        end = text.find(quote, len(quote))
        if end < 0:
            continue
        body = text[len(quote):end].strip()
        return body.splitlines()[0].strip() if body else ""
    return ""


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Обрезает текст до ``max_chars`` и сообщает, резали ли.

    Маркер усечения остаётся в тексте: по нему видно в индексе и отчёте, что
    документ попал не целиком (иначе «документ на 2 КБ» выглядел бы полным).
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars] + TRUNCATION_MARKER, True
