"""Действия трёх инструментов планировщика (день 18).

Модуль отвечает на вопрос «что делает инструмент», а планировщик — «когда».
Разделение важное: одна и та же функция обслуживает оба повода запуска —

* ``prepare`` — НЕМЕДЛЕННОЕ действие в момент регистрации задачи: напоминание
  сохраняется (чтобы не потерялось), сбор делает первый запрос, сводка считается
  сразу за прошедший интервал. Пользователь видит результат в ответе
  ``POST /scheduler/tasks``, а не «через N секунд»;
* ``tick`` — действие по расписанию: напоминание выдаётся (уведомление в очередь),
  сбор добавляет новую запись, сводка пересчитывает период.

Почему тик не вызывает MCP-инструмент заново: MCP-соединение принадлежит
пользователю и держит блокировку клиента, поэтому вызов инструмента из фонового
потока был бы дедлоком. Тик работает с DOMEN-функциями напрямую, а инструмент —
лишь тонкая обёртка над ``POST /scheduler/tasks`` (``mcp_server/backend_api.py``).

Ошибка сбора — это данные, а не падение: причина уходит уведомлением
(``kind="error"``), а исключение пробрасывается дальше, чтобы ``TaskScheduler``
записал запуск со ``status="error"``. Задача при этом остаётся активной: сбор
повторится на следующем тике.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ..domain.aggregation import aggregate_records
from ..domain.schedule_spec import (
    COLLECT_DATA,
    GENERATE_SUMMARY,
    SCHEDULE_REMINDER,
    TOOL_NAMES,
)
from ..domain.scheduler_values import (
    NOTIFICATION_ERROR,
    NOTIFICATION_REMINDER,
    NOTIFICATION_SUMMARY,
)
from ..storage.scheduler_data_store import SchedulerDataStore
from .source_fetch import SourceFetchError, fetch_json

__all__ = ["prepare", "tick", "tool_names"]

#: Сколько записей за период попадает в сводку: агрегация ограничена, чтобы тик
#: не рос бесконечно при долгой работе приложения.
SUMMARY_ROWS_LIMIT = 10000

#: Сколько символов текста сводки попадает в уведомление (в таблице — целиком).
NOTIFICATION_SUMMARY_MAX = 200


def tool_names() -> tuple[str, ...]:
    """Имена инструментов планировщика (каталог домена)."""
    return TOOL_NAMES


def prepare(tool_name: str, arguments: dict[str, Any], *,
            data: SchedulerDataStore, task_id: int,
            fetch: Callable[..., Any] = fetch_json,
            now: Optional[datetime] = None) -> dict[str, Any]:
    """Немедленное действие инструмента в момент регистрации задачи."""
    moment = _as_utc(now)
    args = dict(arguments or {})
    if tool_name == SCHEDULE_REMINDER:
        remind_at = moment + timedelta(seconds=int(args.get("delay_seconds", 60)))
        reminder = data.add_reminder(
            text=str(args.get("text", "")), remind_at=remind_at, task_id=task_id,
        )
        return {"reminder": reminder, "reminder_id": reminder["id"]}
    if tool_name == COLLECT_DATA:
        return {"collection": _collect(args, data=data, fetch=fetch, moment=moment)}
    if tool_name == GENERATE_SUMMARY:
        return _summarise(args, data=data, task_id=task_id, moment=moment)
    raise SourceFetchError(f"Инструмент {tool_name} не умеет немедленного действия")


def tick(tool_name: str, arguments: dict[str, Any], *,
         data: SchedulerDataStore, task: dict[str, Any],
         fetch: Callable[..., Any] = fetch_json,
         now: Optional[datetime] = None) -> dict[str, Any]:
    """Действие инструмента по расписанию (тик планировщика)."""
    moment = _as_utc(now)
    args = dict(arguments or {})
    task_id = task.get("id")
    if tool_name == SCHEDULE_REMINDER:
        return _fire_reminder(args, data=data, task_id=task_id, moment=moment)
    if tool_name == COLLECT_DATA:
        return {"collection": _collect(args, data=data, fetch=fetch, moment=moment,
                                       task_id=task_id)}
    if tool_name == GENERATE_SUMMARY:
        return _summarise(args, data=data, task_id=task_id, moment=moment)
    raise SourceFetchError(f"Инструмент {tool_name} не умеет запуска по расписанию")


def _fire_reminder(args: dict[str, Any], *, data: SchedulerDataStore,
                   task_id: Optional[int], moment: datetime) -> dict[str, Any]:
    """Выдаёт напоминание: помечает выполненным и кладёт уведомление в очередь.

    Номер напоминания лежит в ``arguments`` задачи (его дописала регистрация):
    тик обязан знать, какую именно строку помечать выполненной, иначе повторный
    запуск создал бы второе напоминание вместо выдачи первого.
    """
    reminder_id = args.get("reminder_id")
    if reminder_id is None:
        raise SourceFetchError(
            "В аргументах задачи нет reminder_id: напоминание не с чем связать"
        )
    reminder = data.complete_reminder(int(reminder_id), completed_at=moment)
    text = str(args.get("text") or reminder.get("text") or "")
    notification = data.add_notification(
        kind=NOTIFICATION_REMINDER,
        text=f"Напоминание: {text}"[:1000],
        task_id=task_id,
        payload={"reminder_id": reminder["id"]},
    )
    return {"reminder": reminder, "notification": notification}


def _collect(args: dict[str, Any], *, data: SchedulerDataStore,
             fetch: Callable[..., Any], moment: datetime,
             task_id: Optional[int] = None) -> dict[str, Any]:
    """Читает источник и сохраняет ответ одной записью ``collected_data``."""
    url = str(args.get("source_url", ""))
    name = str(args.get("name", ""))
    try:
        payload = fetch(url)
    except SourceFetchError as exc:
        if task_id is not None:
            data.add_notification(
                kind=NOTIFICATION_ERROR, text=f"Сбор «{name}»: {exc}"[:1000],
                task_id=task_id, payload={"source_url": url},
            )
        raise
    row = data.add_collected(name=name, source_url=url, payload=payload,
                             collected_at=moment)
    return {
        "name": name,
        "source_url": url,
        "records_saved": 1,
        "records_in_payload": len(payload) if isinstance(payload, list) else None,
        "last_collected_at": row["collected_at"],
        "collected_id": row["id"],
    }


def _summarise(args: dict[str, Any], *, data: SchedulerDataStore,
               task_id: Optional[int], moment: datetime) -> dict[str, Any]:
    """Считает сводку за прошедший интервал и сохраняет её в ``periodic_summaries``."""
    name = str(args.get("name", ""))
    seconds = int(args.get("interval_seconds", 3600))
    start = moment - timedelta(seconds=seconds)
    rows = data.collected(name=name, since=start, limit=SUMMARY_ROWS_LIMIT)
    result = aggregate_records(rows, start, moment, name=name)
    summary = data.add_summary(
        name=name, content=result.summary_text, period_start=result.period_start,
        period_end=result.period_end, total_records=result.total_records,
        key_metrics=result.key_metrics, task_id=task_id,
    )
    data.add_notification(
        kind=NOTIFICATION_SUMMARY,
        text=result.summary_text[:NOTIFICATION_SUMMARY_MAX],
        task_id=task_id,
        payload={"summary_id": summary["id"], "total_records": result.total_records},
    )
    return {"summary": summary, "aggregate": result.to_dict()}


def _as_utc(value: Optional[datetime]) -> datetime:
    """Момент времени в UTC (без аргумента — «сейчас»)."""
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
