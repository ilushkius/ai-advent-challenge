"""ORM-строка запуска релиза → словарь для API/UI (день 35).

Преобразование живёт здесь, а не в хранилище: ``ReleaseStore``, служба, роутер и
раздел интерфейса видят одну и ту же форму записи (та же причина, что у
``file_assistant_rows.py`` дня 34). Метки времени приводятся к UTC-aware, JSON-поля —
к виду, который переживает запись в колонку (``as_utc`` и ``jsonable``
переиспользуются из ``scheduler_rows``: пятый экземпляр тех же помощников был бы
копированием).

Две формы, а не одна, потому что тексты релиза — самые объёмные поля строки.
``run_dict`` отдаёт запуск БЕЗ ``changelog``/``release_notes``: список истории
(``GET /release/history``) их не показывает, и тащить в него десятки килобайт
разметки незачем. ``run_dict_full`` добавляет оба текста — его читают выгрузка
(``POST /release/export``) и diff одного запуска.
"""
from __future__ import annotations

from typing import Any

from ..models.release import ReleaseRun
from .scheduler_rows import as_utc, jsonable


def run_dict(row: ReleaseRun) -> dict[str, Any]:
    """Запуск релиза для списка истории: версия, причина, статус, файлы и метки времени."""
    started = as_utc(row.started_at)
    finished = as_utc(row.finished_at)
    return {
        "id": row.id,
        "from_tag": row.from_tag,
        "to_tag": row.to_tag,
        "version": row.version,
        "version_reason": row.version_reason or "",
        "checks_passed": bool(row.checks_passed),
        "files_modified": [str(path) for path in (row.files_modified or [])],
        "status": row.status,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
    }


def run_dict_full(row: ReleaseRun) -> dict[str, Any]:
    """Запуск релиза вместе с текстами разделов (выгрузка и diff одного запуска)."""
    return {**run_dict(row), "changelog": str(row.changelog or ""),
            "release_notes": str(row.release_notes or "")}
