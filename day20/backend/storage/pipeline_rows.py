"""ORM-строки пайплайна → словари для API/UI (день 19).

Преобразования живут здесь, а не в хранилище: и ``PipelineStore``, и сервис, и
роутер, и отчёт прогона видят одну и ту же форму записи (та же причина, что у
``scheduler_rows.py`` дня 18). Метки времени приводятся к UTC-aware, JSON-поля —
к виду, который переживает запись в колонку (``as_utc`` и ``jsonable``
переиспользуются из ``scheduler_rows``: третий экземпляр тех же помощников был бы
копированием).

У запуска и шага — ровно те поля, что описаны в схемах API
(``backend/schemas/pipeline.py``) и таблицах отчёта: ``status`` — значение
``PipelineState`` строкой, ``tool_name`` — имя MCP-инструмента пайплайна.
"""
from __future__ import annotations

from typing import Any

from ..models.pipeline import PipelineRun, PipelineStep
from .scheduler_rows import as_utc, jsonable


def run_dict(row: PipelineRun) -> dict[str, Any]:
    """Запуск пайплайна для API/UI (номер, имя, статус, метки времени, длительность)."""
    started = as_utc(row.started_at)
    finished = as_utc(row.finished_at)
    return {
        "id": row.id,
        "pipeline_name": row.pipeline_name,
        "status": row.status,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "total_duration_ms": int(row.total_duration_ms or 0),
    }


def step_dict(row: PipelineStep) -> dict[str, Any]:
    """Шаг запуска для API/UI: вход, выход, время, статус и текст ошибки."""
    return {
        "id": row.id,
        "run_id": row.run_id,
        "step_index": int(row.step_index),
        "tool_name": row.tool_name,
        "input_args": jsonable(dict(row.input_args or {})),
        "output_result": jsonable(row.output_result),
        "duration_ms": int(row.duration_ms or 0),
        "status": row.status,
        "error_message": row.error_message,
    }
