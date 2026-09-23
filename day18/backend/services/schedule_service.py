"""Операции с задачами планировщика (день 18): ``ScheduleService``.

Слой, которым пользуются роутер API и интерфейс: он знает домен (что за
инструмент, какие у него аргументы, какое расписание), хранилище (строки задач,
напоминаний, сводок и уведомлений) и планировщик (когда ставить job), но не знает
HTTP и не знает Streamlit.

Один код-путь для двух входов. Задачу создают и MCP-инструмент (через
``POST /scheduler/tasks``), и человек в интерфейсе, и оба попадают в
``create_task``: проверка аргументов → расписание → строка ``scheduled_tasks`` →
немедленное действие инструмента (``prepare``) → постановка в APScheduler. Отсюда
же собирается подтверждение (``message``), которое видят и модель, и пользователь.

Отказ — это ``ScheduleRejected`` с кодом причины: роутер переводит его в HTTP-статус
(400 для аргументов и расписания, 404 для отсутствующей задачи, 409 для неверного
состояния). Никаких «тихих» ``None`` наружу: если действие не состоялось, об этом
говорит код.

Немедленное действие может упасть (источник сбора недоступен) — это не отказ
запроса: задача уже зарегистрирована и повторит попытку по расписанию, а причина
видна в ``result.error`` и в уведомлении.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from shared.logging_utils import get_logger

from ..core import config
from ..domain.schedule_spec import (
    COLLECT_DATA,
    SCHEDULE_REMINDER,
    ScheduleRejected,
    default_task_name,
    require_tool_spec,
    schedule_for,
    tool_specs,
    validate_arguments,
)
from ..domain.schedule_timing import normalize_schedule
from ..domain.scheduler_values import (
    REASON_NOT_ACTIVE,
    REASON_NOT_FOUND,
    RUN_PHASE_PREPARE,
    RunStatus,
    ScheduledTaskState,
)
from ..storage.scheduler_data_store import (
    NotificationNotFoundError,
    SchedulerDataStore,
)
from ..storage.scheduler_rows import jsonable
from ..storage.scheduler_store import SchedulerStore
from . import scheduled_jobs
from .scheduler import TaskScheduler, get_scheduler
from .source_fetch import fetch_json

__all__ = ["ScheduleService", "get_schedule_service"]

logger = get_logger(__name__)


class ScheduleService:
    """Создание задач, управление ими и чтение накопленных данных планировщика."""

    def __init__(self, scheduler: Optional[TaskScheduler] = None,
                 store: Optional[SchedulerStore] = None,
                 data: Optional[SchedulerDataStore] = None,
                 fetch: Callable[..., Any] = fetch_json) -> None:
        self._scheduler = scheduler
        self._store = store or SchedulerStore()
        self._data = data or SchedulerDataStore()
        self._fetch = fetch

    @property
    def scheduler(self) -> TaskScheduler:
        """Планировщик процесса (переданный в конструктор или singleton)."""
        if self._scheduler is None:
            self._scheduler = get_scheduler()
        return self._scheduler

    # --- каталог инструментов ---
    def tools(self) -> list[dict[str, Any]]:
        """Каталог трёх инструментов дня (``GET /scheduler/tools``)."""
        return tool_specs()

    # --- задачи ---
    def create_task(self, *, tool: str, arguments: dict[str, Any],
                    name: Optional[str] = None, run_now: bool = True,
                    schedule_type: Optional[str] = None,
                    schedule_value: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Создаёт задачу планировщика: валидация, запись, немедленный шаг, постановка."""
        validate_arguments(tool, arguments)
        require_tool_spec(tool)
        args = dict(arguments or {})
        kind, value = self._schedule_of(tool, args, schedule_type, schedule_value)
        task = self._store.create_task(
            name=(name or default_task_name(tool, args)),
            tool_name=tool, arguments=args,
            schedule_type=kind.value, schedule_value=value,
        )
        outcome = self._immediate(tool, task) if run_now else _silent()
        if outcome["result"] is not None:
            args = self._link_reminder(task, tool, args, outcome["result"])
        task = self._store.task(task["id"])
        task = self.scheduler.register(task)
        return {
            "task": task,
            "result": outcome["result"],
            "immediate": bool(run_now),
            "message": _confirmation(tool, task, outcome["result"], outcome["error"]),
            "error": outcome["error"],
        }

    def list_tasks(self, status: Optional[str] = None) -> dict[str, Any]:
        """Задачи планировщика и состояние самого планировщика."""
        tasks = self._store.list_tasks(status=status, limit=config.SCHEDULER_LIST_LIMIT)
        return {"tasks": tasks, "count": len(tasks), "scheduler": self.scheduler.status()}

    def task(self, task_id: int) -> dict[str, Any]:
        """Задача по id или ``ScheduleRejected(REASON_NOT_FOUND)``."""
        task = self._store.task(task_id)
        if task is None:
            raise ScheduleRejected(
                REASON_NOT_FOUND, f"Задача планировщика {task_id} не найдена"
            )
        return task

    def delete_task(self, task_id: int) -> bool:
        """Снимает задачу с обслуживания и удаляет её строку (вместе с запусками)."""
        self.task(task_id)
        self.scheduler.unregister(task_id)
        return self._store.delete_task(task_id)

    def pause_task(self, task_id: int) -> dict[str, Any]:
        """Пауза задачи (``ScheduleRejected(REASON_NOT_ACTIVE)`` — если не активна)."""
        return self.scheduler.pause(task_id)

    def resume_task(self, task_id: int) -> dict[str, Any]:
        """Возобновление задачи (``REASON_NOT_PAUSED`` — если не на паузе)."""
        return self.scheduler.resume(task_id)

    def run_task_now(self, task_id: int) -> dict[str, Any]:
        """Внеочередной запуск (запись в журнал — как у запуска по расписанию)."""
        task = self.task(task_id)
        if task["status"] == ScheduledTaskState.COMPLETED.value:
            raise ScheduleRejected(
                REASON_NOT_ACTIVE,
                f"Задача {task_id} уже выполнена и повторно не запускается",
            )
        return self.scheduler.run_tick(task_id)

    def task_history(self, task_id: int,
                     limit: int = config.SCHEDULER_RUNS_LIMIT) -> dict[str, Any]:
        """Задача и её запуски по убыванию времени (история тиков и подготовки)."""
        task = self.task(task_id)
        runs = self._store.runs(task_id, limit=limit)
        return {"task": task, "runs": runs, "count": len(runs)}

    # --- данные, которые накопили инструменты ---
    def reminders(self, status: Optional[str] = None,
                  limit: int = config.SCHEDULER_LIST_LIMIT) -> dict[str, Any]:
        """Напоминания (ближайшие — первыми)."""
        rows = self._data.reminders(status=status, limit=limit)
        return {"reminders": rows, "count": len(rows)}

    def collected(self, name: Optional[str] = None,
                  limit: int = config.SCHEDULER_LIST_LIMIT) -> dict[str, Any]:
        """Накопленные записи сбора (свежие — последними) и их число."""
        rows = self._data.collected(name=name, limit=limit)
        return {
            "records": rows,
            "count": len(rows),
            "total": self._data.collected_count(name=name),
            "name": name,
        }

    def summaries(self, name: Optional[str] = None,
                  limit: int = config.SCHEDULER_LIST_LIMIT) -> dict[str, Any]:
        """Регулярные сводки (свежие — первыми)."""
        rows = self._data.summaries(name=name, limit=limit)
        return {"summaries": rows, "count": len(rows)}

    def notifications(self, unread_only: bool = False,
                      limit: int = config.SCHEDULER_LIST_LIMIT) -> dict[str, Any]:
        """Очередь уведомлений и число непрочитанных."""
        rows = self._data.notifications(unread_only=unread_only, limit=limit)
        return {
            "notifications": rows,
            "count": len(rows),
            "unread": self._data.unread_count(),
        }

    def mark_notification_read(self, notification_id: int) -> dict[str, Any]:
        """Отмечает уведомление прочитанным (404-класс отказа — если его нет)."""
        try:
            return self._data.mark_read(notification_id,
                                        read_at=datetime.now(timezone.utc))
        except NotificationNotFoundError as exc:
            raise ScheduleRejected(REASON_NOT_FOUND, str(exc)) from exc

    # --- внутреннее ---
    def _schedule_of(self, tool: str, args: dict[str, Any],
                     schedule_type: Optional[str],
                     schedule_value: Optional[dict[str, Any]]):
        """Расписание задачи: выведенное из аргументов или переопределённое вручную."""
        default_kind, default_value = schedule_for(tool, args)
        if schedule_type is None and schedule_value is None:
            return default_kind, default_value
        kind = default_kind if schedule_type is None else schedule_type
        value = default_value if schedule_value is None else schedule_value
        return normalize_schedule(kind, value)

    def _immediate(self, tool: str, task: dict[str, Any]) -> dict[str, Any]:
        """Немедленное действие инструмента с записью в журнал (``phase="prepare"``)."""
        started = datetime.now(timezone.utc)
        status = RunStatus.OK.value
        error: Optional[str] = None
        detail: Any = None
        try:
            detail = scheduled_jobs.prepare(
                tool, task["arguments"], data=self._data, task_id=task["id"],
                fetch=self._fetch, now=started,
            )
        except Exception as exc:  # noqa: BLE001 — задача остаётся и повторит попытку
            status = RunStatus.ERROR.value
            error = str(exc)
            logger.warning("Планировщик: подготовка задачи %s не удалась: %s",
                           task["id"], exc)
        finished = datetime.now(timezone.utc)
        self._store.record_run(
            task["id"], phase=RUN_PHASE_PREPARE, status=status,
            started_at=started, finished_at=finished,
            duration_ms=int((finished - started).total_seconds() * 1000),
            detail=jsonable(detail), error=error,
            last_run_at=started if status == RunStatus.OK.value else None,
        )
        return {"result": detail, "error": error}

    def _link_reminder(self, task: dict[str, Any], tool: str, args: dict[str, Any],
                       detail: Optional[dict[str, Any]]) -> dict[str, Any]:
        """Дописывает номер напоминания в аргументы задачи (его читает тик)."""
        if detail is None:
            return args
        reminder_id = detail.get("reminder_id") if tool == SCHEDULE_REMINDER else None
        if reminder_id is None:
            return args
        args = {**args, "reminder_id": int(reminder_id)}
        self._store.set_arguments(task["id"], args)
        return args


def _silent() -> dict[str, Any]:
    """Пустой итог подготовки: задачу создали без немедленного действия."""
    return {"result": None, "error": None}


def _confirmation(tool: str, task: dict[str, Any], detail: Optional[dict[str, Any]],
                  error: Optional[str]) -> str:
    """Подтверждение создания задачи: что запланировано и что уже сделано."""
    sentences: list[str] = []
    if detail is not None and tool == SCHEDULE_REMINDER:
        sentences.append(
            "Напоминание запланировано на "
            + _moment(detail.get("reminder"), "remind_at")
        )
    elif detail is not None and tool == COLLECT_DATA:
        collection = detail.get("collection") or {}
        sentences.append(
            f"Сбор «{collection.get('name') or task['name']}» запущен: "
            "первая запись собрана"
        )
    elif detail is not None:
        summary = detail.get("summary") or {}
        sentences.append(
            f"Сводка «{summary.get('name') or task['name']}» сформирована: "
            f"записей за период {summary.get('total_records', 0)}"
        )
    else:
        sentences.append("Немедленный шаг выключен")
    sentences.append(f"Задача №{task['id']}: {task['schedule_label']}")
    if error:
        sentences.append(f"Немедленный шаг не удался: {error}")
    return ". ".join(sentences)


def _moment(payload: Optional[dict[str, Any]], key: str) -> str:
    """Момент времени из деталей подготовки строкой (``—`` — его нет)."""
    value = (payload or {}).get(key)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%d.%m %H:%M:%S UTC")
    return str(value or "—")


_service: Optional[ScheduleService] = None


def get_schedule_service() -> ScheduleService:
    """Единственный сервис расписаний процесса (ленивый singleton)."""
    global _service
    if _service is None:
        _service = ScheduleService()
    return _service
