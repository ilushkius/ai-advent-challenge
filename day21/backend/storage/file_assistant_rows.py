"""ORM-строка запуска ассистента файлов → словарь для API/UI (день 34).

Преобразование живёт здесь, а не в хранилище: ``FileAssistantStore``, служба,
роутер, раздел интерфейса и отчёт прогона видят одну и ту же форму записи (та же
причина, что у ``orchestration_rows.py`` дня 20). Метки времени приводятся к
UTC-aware, JSON-поля — к виду, который переживает запись в колонку (``as_utc`` и
``jsonable`` переиспользуются из ``scheduler_rows``: четвёртый экземпляр тех же
помощников был бы копированием).

Колонка ``diff`` в словарь НЕ входит намеренно: diff — самый объёмный текст строки,
и в списке истории (``GET /file-assistant/history``) он не нужен. Его отдаёт
отдельный эндпоинт ``GET /file-assistant/diff/{run_id}``.
"""
from __future__ import annotations

from typing import Any

from ..models.file_assistant import FileAssistantRun
from .scheduler_rows import as_utc, jsonable


def run_dict(row: FileAssistantRun) -> dict[str, Any]:
    """Запуск ассистента файлов для API/UI: цель, план, журнал, файлы и метки времени."""
    started = as_utc(row.started_at)
    finished = as_utc(row.finished_at)
    return {
        "id": row.id,
        "goal": row.goal,
        "plan": jsonable(list(row.plan or [])),
        "steps": jsonable(list(row.steps or [])),
        "files_read": [str(path) for path in (row.files_read or [])],
        "files_modified": [str(path) for path in (row.files_modified or [])],
        "files_created": [str(path) for path in (row.files_created or [])],
        "status": row.status,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
    }
