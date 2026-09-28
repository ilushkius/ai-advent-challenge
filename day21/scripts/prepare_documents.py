"""Сборка набора документов дня 21: `documents/` плюс манифест.

Скрипт — тонкая обёртка над ``DocumentLoader.collect()``: логика сборки живёт в
сервисе (его же используют демо-прогон и API), а здесь только вывод для человека —
сколько документов собрано, сколько в них символов и «страниц», как они
распределены по видам и языкам и что именно обрезано пределом ``max_chars``.

Запуск из папки day21/::

    uv run python scripts/prepare_documents.py --list     # показать текущий манифест
    uv run python scripts/prepare_documents.py            # собрать, если папки нет
    uv run python scripts/prepare_documents.py --force    # пересобрать заново
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

from backend.services.document_loader import (  # noqa: E402
    CHARS_PER_PAGE,
    DocumentLoader,
)

#: Сколько «страниц» (по 1800 символов) в наборе — привычная мера объёма текста.
PAGE = CHARS_PER_PAGE

#: Подписи видов источников (значения домена: скрипт не импортирует их имена).
KIND_LABELS = {
    "readme": "README дней",
    "docs": "документация устройства",
    "code": "исходники",
    "guide": "правила проекта",
}


def main(argv=None) -> int:
    """Собирает или показывает набор документов и печатает сводку."""
    args = _parse_args(argv)
    loader = DocumentLoader()
    if args.list:
        manifest = loader.manifest()
        if not manifest["documents"]:
            print(f"манифеста нет ({loader.documents_dir / 'manifest.json'}): "
                  "соберите набор без ключа --list")
            return 0
    else:
        if args.force or not loader.manifest()["documents"]:
            manifest = loader.collect()
        else:
            manifest = loader.manifest()
            print("набор уже собран (ключ --force пересоберёт его заново)")
    _print_report(manifest, loader.documents_dir)
    return 0


def _parse_args(argv):
    """Разбирает аргументы: пересборка и просмотр манифеста."""
    parser = argparse.ArgumentParser(
        description="Набор документов дня 21: сборка в documents/ и манифест",
    )
    parser.add_argument("--force", action="store_true",
                        help="пересобрать документы и манифест заново")
    parser.add_argument("--list", action="store_true",
                        help="только показать текущий манифест, ничего не собирая")
    return parser.parse_args(argv)


def _print_report(manifest: dict, documents_dir: Path) -> None:
    """Печатает сводку: документы, объём, страницы и разбивки."""
    documents = list(manifest.get("documents") or [])
    total_chars = int(manifest.get("total_chars") or 0)
    print(f"документов: {len(documents)}")
    print(f"символов: {total_chars} (~{total_chars // PAGE} страниц по {PAGE})")
    print(f"папка: {documents_dir}")
    if not documents:
        print("документов нет: проверьте источники дня")
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


def _counts(documents: list[dict], field: str) -> dict:
    """Сколько документов на каждое значение поля (вид, язык)."""
    counts: dict = {}
    for item in documents:
        value = str(item.get(field) or "—")
        counts[value] = counts.get(value, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
