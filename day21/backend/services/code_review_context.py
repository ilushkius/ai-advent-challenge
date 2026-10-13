"""Контекст ревью: фрагменты документации проекта и кода изменённых файлов.

Вынесено из службы (расширение дня 32): служба упёрлась бы в предел 400 строк, а
поиск — отдельная обязанность. Здесь только то, как из корпуса дня 22 достаются два
источника контекста:

- **документация проекта** — один общий запрос (пути файлов плюс добавленные строки
  diff-а) с фильтром по slug-ам ``dev_assistant.DOCUMENTATION_SLUGS``;
- **код изменённых файлов** — по одному запросу на файл, потому что фильтра по
  источнику у поиска нет: фрагмент проверяется по полю ``source``, а файл находится по
  имени в запросе. Второй запрос — только путь: он нужен, когда добавленные строки
  нового кода увели выдачу к похожим чужим фрагментам.

Отказы приходят данными: нет индекса корпуса — ревью состоится по diff-у, причина
попадёт в ``warnings``; файла нет в корпусе (модули дня 32 в индекс не входят) —
предупреждение, а не поломка.
"""
from __future__ import annotations

from shared.logging_utils import get_logger

from ..domain import code_review, dev_assistant, rag_mode
from ..domain.document_sources import source_slug
from .index_service import IndexNotBuiltError

logger = get_logger(__name__)

__all__ = ["search_code", "search_docs"]


def search_docs(index_service, query: str, top_k: int, warnings: list) -> list:
    """Фрагменты документации проекта; пустой индекс — предупреждение, не отказ."""
    try:
        hits = index_service.search(query, top_k=top_k,
                                    strategy=rag_mode.RAG_DEFAULT_STRATEGY)
    except IndexNotBuiltError as exc:
        logger.warning("Ревью: индекс корпуса недоступен: %s", exc)
        warnings.append(code_review.WARN_INDEX_EMPTY.format(error=exc))
        return []
    allowed = set(dev_assistant.DOCUMENTATION_SLUGS)
    return [hit for hit in hits if hit.get("source") in allowed]


def search_code(index_service, changed_files: list, diff: str, top_k: int,
                warnings: list) -> list:
    """Фрагменты кода изменённых файлов: по одному запросу на файл, без дублей.

    Фильтра по источнику у поиска нет, поэтому фрагмент проверяется по полю
    ``source``, а файл находится по имени в запросе. Первый запрос — путь плюс
    добавленные строки diff-а (он описывает изменение), второй, если первый ничего
    не дал, — только путь: добавленные строки нового кода уводят поиск к похожим
    чужим фрагментам, а имя файла из пути тянет выдачу к самому файлу.
    """
    hits: list = []
    seen: set = set()
    for path in list(changed_files)[:code_review.MAX_CONTEXT_FILES]:
        detail = code_review.context_query([path], diff, code_review.FILE_QUERY_MAX_CHARS)
        try:
            matched = _file_hits(index_service, path, detail, top_k) or \
                _file_hits(index_service, path, path, top_k)
        except IndexNotBuiltError:
            # Индекс недоступен у всего процесса: причину уже записал search_docs.
            break
        if not matched:
            _warn(warnings, code_review.WARN_FILE_NOT_INDEXED.format(path=path))
            continue
        for hit in matched:
            key = str(hit.get("chunk_id") or "")
            if key not in seen:
                seen.add(key)
                hits.append(hit)
    return hits


def _file_hits(index_service, path: str, query: str, top_k: int) -> list:
    """Фрагменты одного файла по запросу: поиск по корпусу плюс фильтр по источнику."""
    found = index_service.search(query, top_k=top_k,
                                 strategy=rag_mode.RAG_DEFAULT_STRATEGY)
    return [hit for hit in found if hit.get("source") == source_slug(path)]


def _warn(warnings: list, message: str) -> None:
    """Добавляет предупреждение, если его ещё нет: файл может повториться в списке."""
    if message not in warnings:
        warnings.append(message)
