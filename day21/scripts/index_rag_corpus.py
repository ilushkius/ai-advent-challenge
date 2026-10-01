"""Построение обоих индексов корпуса RAG дня 22.

Скрипт — обёртка над ``RAGService.prepare_corpus()``: служба собирает корпус (если
он ещё не собран), режет документы обеими стратегиями, чистит прежние чанки
стратегии, считает векторы и пишет файлы ``index/rag_corpus_*.index``. Здесь только
вывод и проверка минимумов: без данных о размере корпуса и о числе чанков не
понять, годится ли индекс для отчёта.

Запуск из папки day21/::

    uv run python scripts/index_rag_corpus.py
"""
from __future__ import annotations

import sys
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import rag_corpus_spec  # noqa: E402
from backend.domain.rag_mode import RAG_STRATEGIES  # noqa: E402
from backend.services.document_loader import CHARS_PER_PAGE  # noqa: E402
from backend.services.rag_errors import RAGError  # noqa: E402
from backend.services.rag_service import RAGService  # noqa: E402


def main(argv=None) -> int:
    """Собирает корпус, строит оба индекса и печатает отчёт; 0 — всё достаточно."""
    del argv
    service = RAGService()
    try:
        result = service.prepare_corpus()
    except RAGError as exc:
        print(f"индексация не выполнена: {exc}")
        return 1
    corpus = result["corpus"]
    minimum = rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS
    print(f"корпус: {corpus['documents']} документов, {corpus['chars']} символов "
          f"(~{corpus['pages']} страниц по {CHARS_PER_PAGE}), "
          f"минимум {corpus['min_pages']} страниц")
    print(f"папка: {corpus['corpus_dir']}")
    ready = bool(corpus["ready"])
    for strategy in RAG_STRATEGIES:
        stats = result["indexes"][strategy]
        count = int(result["chunks"][strategy])
        enough = count >= minimum
        ready = ready and enough
        print(f"{strategy}: чанков {count} (минимум {minimum} — "
              f"{'хватает' if enough else 'НЕ ХВАТАЕТ'}), "
              f"векторов {stats['embeddings']}, размерность {stats['dimension']}, "
              f"эмбеддинги {stats['embed_ms']} мс, индекс {stats['index_ms']} мс")
        path = service.index_service.path_for(strategy)
        print(f"  файл: {path} ({'есть' if path.exists() else 'НЕТ'})")
    config = service.config()
    ready = ready and bool(config["ready"])
    print(f"готово к отчёту: {'да' if ready else 'НЕТ'} "
          f"(чанков всего {config['chunks_total']})")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
