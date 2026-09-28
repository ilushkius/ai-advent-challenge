"""ORM-строки оркестрации → словари для API/UI (день 20).

Преобразования живут здесь, а не в хранилище: ``OrchestrationStore``, сервис,
роутер и отчёт прогона видят одну и ту же форму записи (та же причина, что у
``pipeline_rows.py`` дня 19). Метки времени приводятся к UTC-aware, JSON-поля — к
виду, который переживает запись в колонку (``as_utc`` и ``jsonable``
переиспользуются из ``scheduler_rows``: третий экземпляр тех же помощников был бы
копированием).

У запуска и шага — ровно те поля, что описаны в схемах API
(``backend/schemas/orchestration.py``) и таблицах отчёта: ``status`` — значение
``OrchestrationState`` строкой, у шага есть ``server_name`` — имя сервера флота,
который получил вызов.
"""
from __future__ import annotations

from typing import Any

from ..models.orchestration import OrchestrationRun, OrchestrationStep
from .scheduler_rows import as_utc, jsonable


def run_dict(row: OrchestrationRun) -> dict[str, Any]:
    """Запуск оркестрации для API/UI: запрос, план, статус, метки времени, серверы."""
    started = as_utc(row.started_at)
    finished = as_utc(row.finished_at)
    return {
        "id": row.id,
        "query": row.query,
        "plan": jsonable(dict(row.plan or {})),
        "status": row.status,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "total_duration_ms": int(row.total_duration_ms or 0),
        "servers_used": [str(name) for name in (row.servers_used or [])],
    }


def step_dict(row: OrchestrationStep) -> dict[str, Any]:
    """Шаг запуска для API/UI: сервер, инструмент, вход, выход, время и статус."""
    return {
        "id": row.id,
        "run_id": row.run_id,
        "step_index": int(row.step_index),
        "server_name": row.server_name,
        "tool_name": row.tool_name,
        "input_args": jsonable(dict(row.input_args or {})),
        "output_result": jsonable(row.output_result),
        "duration_ms": int(row.duration_ms or 0),
        "status": row.status,
        "error_message": row.error_message,
    }
