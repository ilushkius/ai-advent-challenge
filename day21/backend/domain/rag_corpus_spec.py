"""Состав корпуса RAG (день 22): источники дня 21 и их минимальный объём.

Корпус режима RAG собирается из файлов САМОГО дня 21 — это то, что агент должен
знать по документации и коду проекта. Таблица источников лежит в доменном слое
(как ``document_sources.DOCUMENT_SOURCES`` дня 21): её читают скрипт сборки, сервис
режима, отчёт и тесты, поэтому описание одно и не расходится.

Ограничения состава:

- пути — от корня репозитория (``day21/...``), как и у ``DOCUMENT_SOURCES``;
- суффиксы только ``.md`` и ``.py``: ``DocumentLoader.load_documents`` пропускает
  всё, чего нет в ``DOCUMENT_SUFFIXES``, поэтому ``.json``/``.ini`` в корпус не
  идут — молча пропущенный файл выглядел бы как отсутствующий чанк;
- ``max_chars`` — окно чтения файла: у небольших файлов оно больше размера, файл
  попадает в корпус целиком, у больших (документация, крупные модули) окно режет
  хвост — корпус нужен для поиска релевантных фрагментов, а не для их полноты.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from .document_sources import (
    DOCUMENT_SUFFIXES,
    DocumentSource,
    KIND_CODE,
    KIND_DOCS,
    KIND_GUIDE,
)

#: Подпапка корпуса внутри ``documents/``: ``documents/rag_corpus/``.
RAG_CORPUS_SUBDIR = "rag_corpus"

#: Минимумы корпуса: меньшее число означает, что состав источников сузился и
#: отчёт по 10 вопросам будет неполным (скрипты сообщают об этом неуспешным кодом).
RAG_CORPUS_MIN_PAGES = 25
RAG_CORPUS_MIN_CHUNKS = 50

#: Корень репозитория: ``day21/backend/domain/rag_corpus_spec.py`` → ``day21`` → корень.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Таблица источников корпуса: 36 файлов дня 21 — семь документов и правил проекта
#: (``AGENTS``, ``WORKFLOW``, ``STRUCTURE``, ``README``, два документа ``docs/`` и
#: отчёт дня 21) и двадцать девять модулей, скриптов и тестов. Порядок таблицы =
#: порядок записей в манифесте корпуса и в отчёте.

RAG_CORPUS_SOURCES: tuple[DocumentSource, ...] = (
    DocumentSource(path="day21/AGENTS.md", kind=KIND_GUIDE, max_chars=4000),
    DocumentSource(path="day21/WORKFLOW.md", kind=KIND_GUIDE, max_chars=1000),
    DocumentSource(path="day21/STRUCTURE.md", kind=KIND_DOCS, max_chars=12000),
    DocumentSource(path="day21/README.md", kind=KIND_DOCS, max_chars=12000),
    DocumentSource(path="day21/docs/architecture.md", kind=KIND_DOCS, max_chars=12000),
    DocumentSource(path="day21/docs/usage.md", kind=KIND_DOCS, max_chars=12000),
    DocumentSource(path="day21/docs/reports/indexing_demo.md", kind=KIND_DOCS, max_chars=12000),
    DocumentSource(path="day21/backend/core/config.py", kind=KIND_CODE, max_chars=18000),
    DocumentSource(path="day21/backend/core/dependencies.py", kind=KIND_CODE, max_chars=7000),
    DocumentSource(path="day21/backend/core/prompt_builder.py", kind=KIND_CODE, max_chars=16000),
    DocumentSource(path="day21/backend/core/mcp_server_config.py", kind=KIND_CODE, max_chars=4000),
    DocumentSource(path="day21/backend/api/main.py", kind=KIND_CODE, max_chars=3200),
    DocumentSource(path="day21/backend/api/lifespan.py", kind=KIND_CODE, max_chars=3800),
    DocumentSource(path="day21/backend/api/indexing.py", kind=KIND_CODE, max_chars=11000),
    DocumentSource(path="day21/backend/domain/chunking.py", kind=KIND_CODE, max_chars=10000),
    DocumentSource(path="day21/backend/domain/indexing_prompt.py", kind=KIND_CODE, max_chars=2500),
    DocumentSource(path="day21/backend/domain/index_scenarios.py", kind=KIND_CODE, max_chars=4200),
    DocumentSource(path="day21/backend/domain/index_metrics.py", kind=KIND_CODE, max_chars=11000),
    DocumentSource(path="day21/backend/domain/document_sources.py", kind=KIND_CODE, max_chars=6300),
    DocumentSource(path="day21/backend/services/index_service.py", kind=KIND_CODE, max_chars=15000),
    DocumentSource(path="day21/backend/services/indexing_service.py", kind=KIND_CODE, max_chars=12000),
    DocumentSource(path="day21/backend/services/index_runner.py", kind=KIND_CODE, max_chars=10000),
    DocumentSource(path="day21/backend/services/index_comparison.py", kind=KIND_CODE, max_chars=6500),
    DocumentSource(path="day21/backend/services/document_loader.py", kind=KIND_CODE, max_chars=9000),
    DocumentSource(path="day21/backend/services/chunker.py", kind=KIND_CODE, max_chars=12500),
    DocumentSource(path="day21/backend/services/embedding_service.py", kind=KIND_CODE, max_chars=8200),
    DocumentSource(path="day21/backend/services/llm_client.py", kind=KIND_CODE, max_chars=14000),
    DocumentSource(path="day21/backend/storage/chunk_store.py", kind=KIND_CODE, max_chars=7200),
    DocumentSource(path="day21/backend/models/indexing.py", kind=KIND_CODE, max_chars=5000),
    DocumentSource(path="day21/backend/schemas/indexing.py", kind=KIND_CODE, max_chars=10500),
    DocumentSource(path="day21/scripts/prepare_documents.py", kind=KIND_CODE, max_chars=4700),
    DocumentSource(path="day21/scripts/indexing_scenarios.py", kind=KIND_CODE, max_chars=17000),
    DocumentSource(path="day21/tests/conftest.py", kind=KIND_CODE, max_chars=10000),
    DocumentSource(path="day21/tests/fixtures_indexing.py", kind=KIND_CODE, max_chars=4400),
    DocumentSource(path="day21/frontend/indexing_api.py", kind=KIND_CODE, max_chars=3200),
    DocumentSource(path="day21/frontend/indexing_section.py", kind=KIND_CODE, max_chars=11000),
)


def corpus_pages(chars: int, chars_per_page: int) -> int:
    """Объём корпуса в «страницах»: та же мера, что у ``document_loader``."""
    chars_per_page = int(chars_per_page)
    if chars_per_page <= 0:
        raise ValueError(f"страница не может быть короче одного символа: {chars_per_page!r}")
    return int(chars) // chars_per_page


def validate_sources(sources: Optional[Iterable[DocumentSource]] = None,
                     suffixes: Optional[Sequence[str]] = None) -> list[str]:
    """Проблемы состава корпуса: пропавшие файлы и суффиксы, которых нет в загрузчике.

    Пустой список = состав пригоден к сборке. Файл, которого нет в репозитории,
    ``DocumentLoader.collect`` пропустит с записью в журнал, а ``load_documents``
    потом не найдёт — поэтому обе проверки делаются заранее и громко.
    """
    known = tuple(suffixes) if suffixes is not None else DOCUMENT_SUFFIXES
    problems = []
    for source in RAG_CORPUS_SOURCES if sources is None else sources:
        path = _REPO_ROOT / source.path
        if not path.is_file():
            problems.append(f"нет файла: {source.path}")
        if path.suffix not in known:
            problems.append(
                f"суффикс {path.suffix!r} вне DOCUMENT_SUFFIXES: {source.path}"
            )
    return problems


__all__ = [
    "RAG_CORPUS_MIN_CHUNKS",
    "RAG_CORPUS_MIN_PAGES",
    "RAG_CORPUS_SOURCES",
    "RAG_CORPUS_SUBDIR",
    "corpus_pages",
    "validate_sources",
]
