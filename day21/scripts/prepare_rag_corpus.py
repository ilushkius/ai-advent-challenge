"""Сборка корпуса RAG дня 22: ``documents/rag_corpus`` плюс манифест.

Скрипт — тонкая обёртка над ``RagCorpusLoader``: сборка, манифест и чтение живут
в сервисе (его же использует служба RAG), а здесь только вывод для человека —
сколько документов собрано, сколько в них символов и «страниц», набрал ли корпус
минимум и сколько чанков даст каждая стратегия. Чанки считаются без эмбеддингов:
важна только нарезка текста, а векторы строит ``scripts/index_rag_corpus.py``.

Запуск из папки day21/::

    uv run python scripts/prepare_rag_corpus.py --list      # показать манифест
    uv run python scripts/prepare_rag_corpus.py --validate  # проверить источники
    uv run python scripts/prepare_rag_corpus.py             # собрать, если папки нет
    uv run python scripts/prepare_rag_corpus.py --force     # пересобрать заново
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня
# и в корне репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.domain import rag_corpus_spec  # noqa: E402
from backend.domain.rag_mode import RAG_STRATEGIES  # noqa: E402
from backend.services.chunker import chunk_document  # noqa: E402
from backend.services.document_loader import CHARS_PER_PAGE  # noqa: E402
from backend.services.rag_corpus_loader import RagCorpusLoader  # noqa: E402
from backend.services.rag_service import CHUNK_STRATEGIES  # noqa: E402

#: Сколько «страниц» (по 1800 символов) в корпусе — привычная мера объёма текста.
PAGE = CHARS_PER_PAGE

#: Подписи видов источников (значения домена: скрипт не импортирует их имена).
KIND_LABELS = {
    "readme": "README дней",
    "docs": "документация устройства",
    "code": "исходники",
    "guide": "правила проекта",
}


def main(argv=None) -> int:
    """Собирает корпус и печатает сводку; код возврата — «корпус готов»."""
    args = _parse_args(argv)
    loader = RagCorpusLoader()
    if args.validate:
        return _report_problems(loader.validate())
    if args.list:
        manifest = loader.manifest()
        if not manifest["documents"]:
            print(f"манифеста нет ({loader.documents_dir / 'manifest.json'}): "
                  "соберите корпус без ключа --list")
            return 1
    elif args.force or not loader.manifest()["documents"]:
        manifest = loader.collect()
    else:
        manifest = loader.manifest()
        print("корпус уже собран (ключ --force пересоберёт его заново)")
    documents = loader.load_documents()
    chunks = {strategy: sum(len(chunk_document(document, CHUNK_STRATEGIES[strategy]))
                            for document in documents)
              for strategy in RAG_STRATEGIES}
    _print_report(manifest, loader.documents_dir, chunks)
    return 0 if _is_ready(chunks) else 1


def _parse_args(argv):
    """Разбирает аргументы: пересборка, просмотр манифеста, проверка источников."""
    parser = argparse.ArgumentParser(
        description="Корпус RAG дня 22: сборка в documents/rag_corpus и манифест",
    )
    parser.add_argument("--force", action="store_true",
                        help="пересобрать документы и манифест заново")
    parser.add_argument("--list", action="store_true",
                        help="только показать текущий манифест, ничего не собирая")
    parser.add_argument("--validate", action="store_true",
                        help="только проверить состав источников корпуса")
    return parser.parse_args(argv)


def _report_problems(problems: list) -> int:
    """Печатает проблемы состава источников: их нет — 0, иначе 1."""
    if not problems:
        print(f"источников: {len(rag_corpus_spec.RAG_CORPUS_SOURCES)} — все на месте, "
              "суффиксы допустимы для загрузчика")
        return 0
    print(f"проблем в составе корпуса: {len(problems)}")
    for problem in problems:
        print(f"- {problem}")
    return 1


def _is_ready(chunks: dict) -> bool:
    """Готов ли корпус: страниц и чанков хватает на обе стратегии."""
    return all(count >= rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS for count in chunks.values())


def _print_report(manifest: dict, documents_dir: Path, chunks: dict) -> None:
    """Печатает сводку: документы, объём, минимум, таблицу и чанки стратегий."""
    documents = list(manifest.get("documents") or [])
    total_chars = int(manifest.get("total_chars") or 0)
    pages = rag_corpus_spec.corpus_pages(total_chars, PAGE)
    minimum = rag_corpus_spec.RAG_CORPUS_MIN_PAGES
    print(f"документов: {len(documents)}")
    print(f"символов: {total_chars} (~{pages} страниц по {PAGE})")
    print(f"минимум: {minimum} страниц — {'хватает' if pages >= minimum else 'НЕ ХВАТАЕТ'}")
    print(f"папка: {documents_dir}")
    if not documents:
        print("документов нет: проверьте источники корпуса ключом --validate")
        return
    print("")
    print("| документ | вид | язык | символов | усечён | заголовок |")
    print("|---|---|---|---|---|---|")
    for item in documents:
        print(f"| {item.get('source')} | {KIND_LABELS.get(item.get('kind'), item.get('kind'))} "
              f"| {item.get('language')} | {item.get('chars')} "
              f"| {'да' if item.get('truncated') else 'нет'} "
              f"| {str(item.get('title') or '')[:60]} |")
    print("")
    print("по видам: " + ", ".join(
        f"{KIND_LABELS.get(kind, kind)} — {count}"
        for kind, count in sorted(_counts(documents, "kind").items())
    ))
    print("по языкам: " + ", ".join(
        f"{language} — {count}"
        for language, count in sorted(_counts(documents, "language").items())
    ))
    truncated = [item["source"] for item in documents if item.get("truncated")]
    print(f"обрезаны пределом max_chars: {len(truncated)}"
          + (f" ({', '.join(truncated[:5])}…)" if truncated else ""))
    print("")
    _print_chunks(chunks)


def _print_chunks(chunks: dict) -> None:
    """Печатает ожидаемое число чанков по стратегиям (без эмбеддингов)."""
    minimum = rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS
    for strategy, count in chunks.items():
        verdict = "хватает" if count >= minimum else "НЕ ХВАТАЕТ"
        print(f"{strategy}: чанков {count} (минимум {minimum} — {verdict})")
    if not _is_ready(chunks):
        print("корпуса мало для отчёта: увеличьте окна max_chars или добавьте источники")


def _counts(documents: list, field: str) -> dict:
    """Сколько документов на каждое значение поля (вид, язык)."""
    counts: dict = {}
    for item in documents:
        value = str(item.get(field) or "—")
        counts[value] = counts.get(value, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
