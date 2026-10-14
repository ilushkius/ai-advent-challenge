"""Пересборка корпуса RAG вместе с документацией поддержки (день 33).

Скрипт — обёртка над ``RAGService.prepare_corpus()`` плюс один дополнительный
отчёт: сколько чанков пришло из ДОКУМЕНТАЦИИ ПОДДЕРЖКИ (``support.SUPPORT_SOURCES``
— FAQ, разборы симптомов и справочник API). Он нужен потому, что полный корпус
отвечает на вопрос «сколько всего в индексе», а ассистент поддержки зависит ровно
от трёх файлов: если ``day21/docs/support/faq.md`` не попал в таблицу источников
``rag_corpus_spec.RAG_CORPUS_SOURCES``, ответы по FAQ будут пустыми при живом
корпусе, и без отдельного счётчика это не видно.

Почему готовой ``uv run python scripts/index_rag_corpus.py`` не хватает. Та
пересобирает корпус и говорит «чанков 387» — столько же, сколько было до правки
таблицы источников, если документация поддержки в таблицу не добавлена. Здесь те
же шаги (``prepare_corpus`` идемпотентен: очистка стратегии плюс запись чанков), но
минимум проверяется ПО ФАЙЛАМ ДОКУМЕНТАЦИИ ПОДДЕРЖКИ и по каждой стратегии.

Запуск из папки day21/::

    uv run python scripts/reindex_with_support.py

Код возврата 0 — документации поддержки хватает на обеих стратегиях и корпус не
ниже минимума; 1 — не хватает (тогда в разделе «🎧 Поддержка пользователей» ответы
будут неполными); 2 — пересборка не выполнена (``RAGError``).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня и в
# корне репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import rag_mode, support  # noqa: E402
from backend.domain.rag_corpus_spec import RAG_CORPUS_MIN_CHUNKS  # noqa: E402
from backend.services.document_loader import CHARS_PER_PAGE  # noqa: E402
from backend.services.rag_errors import RAGError  # noqa: E402
from backend.services.rag_service import RAGService  # noqa: E402
from backend.storage.chunk_store import ChunkStore  # noqa: E402


def doc_chunk_counts(store: ChunkStore, strategies) -> dict:
    """Чанков документации поддержки на каждую стратегию: по именам файлов корпуса.

    Имена берутся из ``support.SUPPORT_SLUGS`` (они же — имена документов в
    ``documents/rag_corpus/``), а не из путей: в таблице ``document_chunks``
    источник записан именем файла-документа.
    """
    counts = {}
    for strategy in strategies:
        by_source = store.counts_by_source(strategy)
        counts[strategy] = sum(int(by_source.get(slug) or 0)
                               for slug in support.SUPPORT_SLUGS)
    return counts


def main(argv=None) -> int:
    """Пересобирает корпус и печатает отчёт о документации поддержки; 0 — её хватает."""
    del argv
    service = RAGService()
    try:
        result = service.prepare_corpus()
    except RAGError as exc:
        print(f"пересборка не выполнена: {exc}")
        return 2
    corpus = result["corpus"]
    minimum = RAG_CORPUS_MIN_CHUNKS
    counts = doc_chunk_counts(ChunkStore(), rag_mode.RAG_STRATEGIES)
    total = sum(counts.values())
    doc_minimum = support.SUPPORT_MIN_CHUNKS
    enough = min(counts.values()) >= doc_minimum
    print(f"документация поддержки: файлов {len(support.SUPPORT_SOURCES)}, "
          f"чанков {total} "
          f"({rag_mode.RAG_STRATEGY_FIXED} {counts[rag_mode.RAG_STRATEGY_FIXED]}, "
          f"{rag_mode.RAG_STRATEGY_STRUCTURAL} "
          f"{counts[rag_mode.RAG_STRATEGY_STRUCTURAL]})")
    print(f"минимум — {doc_minimum} чанков на стратегию: "
          f"{'соблюдён' if enough else 'НЕ СОБЛЮДЁН'}")
    print(f"корпус: {corpus['documents']} документов, {corpus['chars']} символов "
          f"(~{corpus['pages']} страниц по {CHARS_PER_PAGE}), "
          f"минимум {corpus['min_pages']} страниц")
    print(f"папка: {corpus['corpus_dir']}")
    ready = bool(corpus["ready"]) and enough
    for strategy in rag_mode.RAG_STRATEGIES:
        stats = result["indexes"][strategy]
        count = int(result["chunks"][strategy])
        has_enough = count >= minimum
        ready = ready and has_enough
        print(f"{strategy}: чанков {count} (минимум {minimum} — "
              f"{'хватает' if has_enough else 'НЕ ХВАТАЕТ'}), "
              f"векторов {stats['embeddings']}, размерность {stats['dimension']}, "
              f"эмбеддинги {stats['embed_ms']} мс, индекс {stats['index_ms']} мс")
        path = service.index_service.path_for(strategy)
        print(f"  файл: {path} ({'есть' if path.exists() else 'НЕТ'})")
    print("индекс обновлён")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
