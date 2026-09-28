"""Учёт непиковых часов DeepSeek планировщиком (день 21).

Проверяем связку «флаг ``prefer_off_peak`` → сдвиг первого запуска в непиковое
окно»: задачу создаём через ``ScheduleService`` (тот же код-путь, что у API и
MCP), а моменты задаём явными ``run_date`` в будущем — в тесте нет ни одного
обращения к «сейчас» кроме поиска ближайшего буднего дня, поэтому результат
детерминирован. Подмена времени видна прямо в тесте: ``scheduler.is_off_peak`` и
``peak_status`` принимают ``moment=`` и на одних и тех же константах дают
одинаковый ответ в любом прогоне.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.domain import peak_hours
from backend.services.schedule_service import ScheduleService
from backend.services.scheduler import TaskScheduler

UTC = timezone.utc
REMINDER_ARGS = {"text": "тест непиковых часов", "delay_seconds": 60}


def future_weekday(hour: int) -> datetime:
    """Ближайший момент на буднем дне в заданный час UTC, строго в будущем.

    Будний день нужен, чтобы момент гарантированно попадал в недельное расписание
    окон (у выходных непик круглые сутки, и «пик» там не найти).
    """
    now = datetime.now(UTC)
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    while candidate <= now or candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def create_reminder(service: ScheduleService, run_date: datetime,
                    prefer_off_peak: bool = False) -> dict:
    """Разовая задача-напоминание на конкретный момент (без немедленного действия)."""
    return service.create_task(
        tool="schedule_reminder",
        arguments=dict(REMINDER_ARGS),
        run_now=False,
        schedule_type="date",
        schedule_value={"run_date": run_date.isoformat()},
        prefer_off_peak=prefer_off_peak,
    )["task"]


def test_flag_moves_task_out_of_peak(schedule_service: ScheduleService,
                                     scheduler: TaskScheduler) -> None:
    """Задача с флагом, поставленная в пик, получает ``next_run_at`` в непике."""
    peak = future_weekday(2)
    assert scheduler.is_off_peak(peak) is False
    task = create_reminder(schedule_service, peak, prefer_off_peak=True)
    assert task["prefer_off_peak"] is True
    assert scheduler.is_off_peak(task["next_run_at"]) is True
    assert task["next_run_at"] == peak_hours.next_off_peak(peak)
    assert task["next_run_at"] == peak.replace(hour=4)


def test_without_flag_time_is_unchanged(schedule_service: ScheduleService,
                                        scheduler: TaskScheduler) -> None:
    """Без флага планировщик не трогает расчётное время (даже если это пик)."""
    peak = future_weekday(2)
    task = create_reminder(schedule_service, peak)
    assert task["prefer_off_peak"] is False
    assert task["next_run_at"] == peak


def test_flag_outside_peak_keeps_time(schedule_service: ScheduleService,
                                      scheduler: TaskScheduler) -> None:
    """Флаг при непиковом времени ничего не меняет: сдвигать некуда."""
    off_peak = future_weekday(11)
    assert scheduler.is_off_peak(off_peak) is True
    task = create_reminder(schedule_service, off_peak, prefer_off_peak=True)
    assert task["prefer_off_peak"] is True
    assert task["next_run_at"] == off_peak


def test_flag_survives_restart(schedule_service: ScheduleService,
                               scheduler: TaskScheduler, scheduler_store) -> None:
    """После перезапуска (пере-постановка из БД) флаг цел и задача в непике."""
    peak = future_weekday(2)
    created = create_reminder(schedule_service, peak, prefer_off_peak=True)
    stored = scheduler_store.task(created["id"])
    assert stored["prefer_off_peak"] is True

    # Перезапуск: задача перечитывается из БД и ставится заново, как в sync_from_db.
    again = scheduler.register(stored)
    assert again["prefer_off_peak"] is True
    assert scheduler.is_off_peak(again["next_run_at"]) is True
    assert again["next_run_at"] == created["next_run_at"]


def test_peak_status_is_deterministic(scheduler: TaskScheduler) -> None:
    """``peak_status(moment=...)`` даёт тот же ответ, что чистый домен: подмена видна."""
    peak = future_weekday(2)
    status = scheduler.peak_status(peak)
    assert status == peak_hours.peak_status(peak)
    assert status["peak"] is True and status["off_peak"] is False

    off_peak = future_weekday(11)
    assert scheduler.peak_status(off_peak)["off_peak"] is True
    assert scheduler.is_off_peak(off_peak) is True
    assert scheduler.get_next_off_peak_time(peak) == peak_hours.next_off_peak(peak)


def test_scheduler_status_reports_off_peak(scheduler: TaskScheduler) -> None:
    """``GET /scheduler/status`` несёт блок непиковых часов (флаг, окно, скидка)."""
    status = scheduler.status()
    assert isinstance(status["off_peak"], bool)
    assert datetime.fromisoformat(status["next_off_peak"]).tzinfo is not None
    assert status["discount_percent"] > 0
