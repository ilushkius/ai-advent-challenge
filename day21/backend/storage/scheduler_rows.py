"""ORM-строки планировщика → словари для API/UI (день 18).

Преобразования живут здесь, а не в хранилищах: и ``SchedulerStore``, и
``SchedulerDataStore``, и роутер, и скрипт отчёта видят одну и ту же форму записи,
поэтому колонку не приходится переименовывать в трёх местах (та же причина, что у
``memory_rows.py`` дня 11).

Метки времени нормализуются: пишем в БД aware-значения, а SQLite возвращает naive —
без приведения одна и та же задача отдавалась бы в API то с ``+00:00``, то без
него (та же логика, что у ``task_store._as_utc``).

У задачи, кроме колонок, есть два производных поля: ``schedule_label``
(человекочитаемое расписание) и ``allowed_events`` (события FSM, допустимые в её
состоянии). Они считаются здесь, поэтому интерфейс и тесты видят граф допуска из
одного источника — ``scheduler_fsm``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..domain.schedule_timing import schedule_label
from ..domain.scheduler_fsm import reminder_allowed_events, task_allowed_events
from ..domain.scheduler_values import ReminderState, ScheduledTaskState
from ..models.scheduler import (
    CollectedRecord,
    PeriodicSummary,
    Reminder,
    ScheduledTask,
    SchedulerNotification,
    SchedulerTaskRun,
)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Приводит метку времени к UTC-aware (naive из SQLite считаем UTC)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def jsonable(value: Any) -> Any:
    """Приводит значение к виду, который переживает запись в JSON-колонку.

    Детали запуска собирает сервис, и в них попадают метки времени (когда собрана
    запись, за какой период сводка): ``json.dumps`` внутри SQLAlchemy их не умеет,
    а терять детали запуска нельзя — по ним читают историю. Поэтому метки времени
    становятся строками ISO-8601, а словари и списки обходятся рекурсивно.
    """
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def task_dict(row: ScheduledTask) -> dict[str, Any]:
    """Задача планировщика для API/UI (с расписанием и допустимыми событиями)."""
    kind = _schedule_type(row)
    value = dict(row.schedule_value or {})
    state = _task_state(row.status)
    return {
        "id": row.id,
        "name": row.name,
        "schedule_type": kind,
        "schedule_value": value,
        "schedule_label": _label(kind, value),
        "tool_name": row.tool_name,
        "arguments": dict(row.arguments or {}),
        "status": state.value,
        "last_run_at": as_utc(row.last_run_at),
        "next_run_at": as_utc(row.next_run_at),
        "created_at": as_utc(row.created_at),
        "allowed_events": [item.value for item in task_allowed_events(state)],
    }


def run_dict(row: SchedulerTaskRun) -> dict[str, Any]:
    """Один запуск задачи для истории (``GET /scheduler/tasks/{id}/history``)."""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "phase": row.phase,
        "status": row.status,
        "started_at": as_utc(row.started_at),
        "finished_at": as_utc(row.finished_at),
        "duration_ms": row.duration_ms,
        "detail": dict(row.detail) if isinstance(row.detail, dict) else row.detail,
        "error": row.error,
    }


def reminder_dict(row: Reminder) -> dict[str, Any]:
    """Напоминание для API/UI (состояние — значение ``ReminderState``)."""
    return {
        "id": row.id,
        "text": row.text,
        "remind_at": as_utc(row.remind_at),
        "status": row.status,
        "created_at": as_utc(row.created_at),
        "task_id": row.task_id,
        "allowed_events": [item.value for item in reminder_allowed_events(_reminder_state(row.status))],
    }


def notification_dict(row: SchedulerNotification) -> dict[str, Any]:
    """Уведомление очереди для API/UI (``read_at is None`` — непрочитанное)."""
    return {
        "id": row.id,
        "kind": row.kind,
        "text": row.text,
        "task_id": row.task_id,
        "payload": dict(row.payload) if isinstance(row.payload, dict) else row.payload,
        "created_at": as_utc(row.created_at),
        "read_at": as_utc(row.read_at),
        "unread": row.read_at is None,
    }


def collected_dict(row: CollectedRecord) -> dict[str, Any]:
    """Собранная запись для API/UI."""
    return {
        "id": row.id,
        "name": row.name,
        "source_url": row.source_url,
        "payload": row.payload,
        "collected_at": as_utc(row.collected_at),
    }


def summary_dict(row: PeriodicSummary) -> dict[str, Any]:
    """Регулярная сводка для API/UI (текст, период, метрики)."""
    return {
        "id": row.id,
        "name": row.name,
        "content": row.content,
        "period_start": as_utc(row.period_start),
        "period_end": as_utc(row.period_end),
        "total_records": row.total_records,
        "key_metrics": dict(row.key_metrics or {}),
        "task_id": row.task_id,
        "created_at": as_utc(row.created_at),
    }


def _schedule_type(row: ScheduledTask) -> str:
    """Тип расписания строки (пустое значение — считаем разовой задачей)."""
    return str(row.schedule_type or "")


def _label(kind: str, value: dict[str, Any]) -> str:
    """Подпись расписания; неизвестный тип отдаётся как есть, а не падает."""
    try:
        return schedule_label(kind, value)
    except Exception:  # noqa: BLE001 — испорченное расписание не должно ломать список
        return kind or "—"


def _task_state(value: str) -> ScheduledTaskState:
    """Состояние задачи из строки БД (непонятное значение — ``active``)."""
    try:
        return ScheduledTaskState(str(value))
    except ValueError:
        return ScheduledTaskState.ACTIVE


def _reminder_state(value: str) -> ReminderState:
    """Состояние напоминания из строки БД (непонятное значение — ``scheduled``)."""
    try:
        return ReminderState(str(value))
    except ValueError:
        return ReminderState.SCHEDULED
