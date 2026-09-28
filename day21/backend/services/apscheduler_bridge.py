"""Мост к APScheduler (день 18): единственное место, знающее про его классы.

``TaskScheduler`` описывает ПРАВИЛА дня (что считать активной задачей, когда
догонять пропущенный запуск, что писать в журнал), а знание «как это выражается в
API APScheduler» живёт здесь: триггеры по типу расписания, имена job'ов, создание
и остановка планировщика. Так ``scheduler.py`` читается как логика, а не как
обвязка библиотеки, и версия APScheduler меняет ровно этот файл.

Соглашения об именах:

* job задачи — ``scheduled-task-<номер строки в БД>``: по id видно, какую строку
  ``scheduled_tasks`` он обслуживает, а ``job_task_id`` разбирает её обратно;
* служебный job сверки — ``scheduler-reconcile``: у него номера нет, поэтому
  разбор возвращает ``None`` (сверка не задача дня).

Отдельная тонкость — ``next_run_time``: у cron расписание знает только триггер
APScheduler, поэтому его нельзя переписать «пустым» значением. Поэтому
``add_task_job`` вообще не передаёт аргумент, когда момента нет, — иначе job
создался бы на паузе (``next_run_time=None`` в APScheduler значит «не запускать»).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import SchedulerNotRunningError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.logging_utils import get_logger

from ..core import config
from ..domain.scheduler_values import ScheduleType

__all__ = [
    "RECONCILE_JOB_ID",
    "TASK_JOB_PREFIX",
    "add_reconcile_job",
    "add_task_job",
    "job_next_run_time",
    "job_task_id",
    "make_scheduler",
    "pause_job",
    "remove_task_job",
    "reschedule_job_now",
    "resume_job",
    "shutdown_scheduler",
    "task_job_id",
]

logger = get_logger(__name__)

#: Префикс id задачи APScheduler: по нему видно, какая строка БД за job'ом.
TASK_JOB_PREFIX = "scheduled-task-"

#: id служебной задачи сверки БД и планировщика.
RECONCILE_JOB_ID = "scheduler-reconcile"

#: Настройки по умолчанию для задач дня: один запуск за раз, пропуски
#: сворачиваются, у пропущенного запуска есть окно прощения (config).
JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": config.SCHEDULER_MISFIRE_GRACE,
}


def task_job_id(task_id: int) -> str:
    """id задачи APScheduler по номеру строки в БД."""
    return f"{TASK_JOB_PREFIX}{int(task_id)}"


def job_task_id(job_id: str) -> Optional[int]:
    """Номер строки БД по id задачи APScheduler (``None`` — это не наша задача)."""
    if not job_id.startswith(TASK_JOB_PREFIX):
        return None
    tail = job_id[len(TASK_JOB_PREFIX):]
    return int(tail) if tail.isdigit() else None


def make_scheduler() -> AsyncIOScheduler:
    """Планировщик в цикле событий процесса (запускается ``lifespan`` FastAPI)."""
    return AsyncIOScheduler(timezone=config.SCHEDULER_TIMEZONE, job_defaults=dict(JOB_DEFAULTS))


def add_reconcile_job(scheduler: AsyncIOScheduler, callback: Callable[[], None],
                      seconds: int) -> None:
    """Ставит служебную задачу сверки БД и планировщика."""
    scheduler.add_job(callback, "interval", seconds=seconds, id=RECONCILE_JOB_ID,
                      replace_existing=True)


def add_task_job(scheduler: AsyncIOScheduler, task: dict[str, Any],
                moment: Optional[datetime], func: Callable[[], None]):
    """Ставит job задачи с триггером по её расписанию.

    ``moment`` — расчётный момент первого запуска; без него (cron) расписание
    определяет триггер, и аргумент не передаётся вовсе (см. докстринг модуля).
    """
    kwargs: dict[str, Any] = {
        "id": task_job_id(task["id"]),
        "replace_existing": True,
    }
    if moment is not None:
        kwargs["next_run_time"] = moment
    return scheduler.add_job(func, trigger_for(task, moment), **kwargs)


def trigger_for(task: dict[str, Any], moment: Optional[datetime]):
    """Триггер APScheduler по расписанию из БД (``date`` | ``interval`` | ``cron``)."""
    kind = ScheduleType(task["schedule_type"])
    value = dict(task["schedule_value"] or {})
    if kind is ScheduleType.DATE:
        return DateTrigger(run_date=moment or datetime.now(timezone.utc))
    if kind is ScheduleType.INTERVAL:
        return IntervalTrigger(seconds=int(value["seconds"]))
    return CronTrigger.from_crontab(str(value["cron"]))


def remove_task_job(scheduler: AsyncIOScheduler, task_id: int) -> None:
    """Снимает job задачи (его отсутствие — не ошибка)."""
    try:
        scheduler.remove_job(task_job_id(task_id))
    except JobLookupError:
        pass


def job_next_run_time(job) -> Optional[datetime]:
    """Момент следующего запуска job'а (``None`` — job на паузе или его нет)."""
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time


def pause_job(job) -> None:
    """Ставит job на паузу (расписание остаётся у триггера)."""
    job.pause()


def resume_job(job) -> None:
    """Возвращает job к работе, пересчитав ближайший запуск от триггера."""
    job.resume()


def reschedule_job_now(job, moment: datetime) -> None:
    """Переносит ближайший запуск job'а на заданный момент (догон пропуска)."""
    job.modify(next_run_time=moment)


def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Останавливает планировщик, не роняя выход приложения."""
    try:
        scheduler.shutdown(wait=False)
    except SchedulerNotRunningError:
        pass
    except Exception as exc:  # noqa: BLE001 — остановка не должна ронять выход
        logger.warning("Планировщик: остановка завершилась ошибкой: %s", exc)
