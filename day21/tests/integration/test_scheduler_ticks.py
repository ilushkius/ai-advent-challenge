"""Тики инструментов планировщика (день 18): что делает запуск по расписанию.

Тик проверяется напрямую (``scheduled_jobs.tick`` и ``TaskScheduler.run_tick``) —
без ожидания таймеров: важен не момент запуска, а след в БД. Проверяются три
инструмента и два пути отказа: выдача уже выданного напоминания (FSM говорит
«нельзя») и сбой источника сбора (задача остаётся активной).
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.domain.scheduler_fsm import UnknownSchedulerEvent
from backend.domain.schedule_spec import (
    COLLECT_DATA,
    GENERATE_SUMMARY,
    SCHEDULE_REMINDER,
    ScheduleRejected,
)
from backend.domain.scheduler_values import (
    NOTIFICATION_ERROR,
    NOTIFICATION_REMINDER,
    NOTIFICATION_SUMMARY,
    RUN_PHASE_TICK,
    ScheduledTaskState,
)
from backend.services import scheduled_jobs

NOW = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)


def _collect_arguments():
    return {"source_url": "https://example.test/posts", "interval_seconds": 10,
            "name": "posts"}


def test_reminder_tick_marks_done_and_queues_notification(schedule_service, scheduler_data,
                                                          scheduler_store):
    """Напоминание выдаётся: строка становится выполненной, уведомление — в очереди.

    Разовая задача после успешного тика завершается: срабатывает один раз.
    """
    created = schedule_service.create_task(
        tool=SCHEDULE_REMINDER, arguments={"text": "проверить почту", "delay_seconds": 30}
    )
    run = schedule_service.run_task_now(created["task"]["id"])
    assert run["phase"] == RUN_PHASE_TICK and run["status"] == "ok"
    assert scheduler_data.reminders()[0]["status"] == "done"
    notification = scheduler_data.notifications()[0]
    assert notification["kind"] == NOTIFICATION_REMINDER
    assert notification["text"] == "Напоминание: проверить почту"
    assert scheduler_store.task(created["task"]["id"])["status"] == ScheduledTaskState.COMPLETED.value


def test_second_reminder_tick_is_refused(schedule_service, scheduler_data):
    """Напоминание выдаётся один раз: служба отказывает, а тик — ошибка FSM.

    Два разных «нет»: эндпоинт ``run`` не запускает уже выполненную задачу (она
    ``completed``), а сам тик отказывается выдавать выданное напоминание — это
    страховка FSM на случай, если задача всё-таки сработает дважды.
    """
    created = schedule_service.create_task(
        tool=SCHEDULE_REMINDER, arguments={"text": "почта", "delay_seconds": 30}
    )
    task_id = created["task"]["id"]
    assert schedule_service.run_task_now(task_id)["status"] == "ok"
    with pytest.raises(ScheduleRejected):
        schedule_service.run_task_now(task_id)
    task = schedule_service.task(task_id)
    with pytest.raises(UnknownSchedulerEvent):
        scheduled_jobs.tick(SCHEDULE_REMINDER, task["arguments"], data=scheduler_data,
                            task=task, now=NOW)
    assert scheduler_data.reminders()[0]["status"] == "done"
    assert len(scheduler_data.reminders()) == 1
    assert len(scheduler_data.notifications()) == 1  # второго уведомления нет


def test_collect_tick_appends_a_new_record(schedule_service, scheduler_data, fetcher,
                                           scheduler_store):
    """Каждый тик сбора читает источник заново и добавляет новую запись."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=_collect_arguments())
    task_id = created["task"]["id"]
    first = scheduler_data.collected(name="posts")
    assert len(first) == 1  # первая запись — при регистрации задачи
    run = schedule_service.run_task_now(task_id)
    assert run["status"] == "ok"
    rows = scheduler_data.collected(name="posts")
    assert len(rows) == 2
    assert run["detail"]["collection"]["records_saved"] == 1
    assert len(rows[1]["payload"]) != len(rows[0]["payload"])  # источник читался снова
    assert scheduler_store.task(task_id)["status"] == ScheduledTaskState.ACTIVE.value
    assert scheduler_store.task(task_id)["next_run_at"] > datetime.now(timezone.utc)


def test_collect_failure_keeps_task_active_and_notifies(schedule_service, scheduler_data,
                                                        fetcher, scheduler_store):
    """Сбой источника: запуск со ``error``, уведомление и активная задача (повтор)."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=_collect_arguments())
    task_id = created["task"]["id"]
    fetcher.fail("источник недоступен")
    run = schedule_service.run_task_now(task_id)
    assert run["status"] == "error" and run["error"] == "источник недоступен"
    notification = scheduler_data.notifications()[0]
    assert notification["kind"] == NOTIFICATION_ERROR
    assert "Сбор «posts»" in notification["text"]
    assert scheduler_store.task(task_id)["status"] == ScheduledTaskState.ACTIVE.value


def test_summary_tick_aggregates_the_period(schedule_service, scheduler_data):
    """Сводка считает записи за прошедший интервал и сохраняет метрики."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=_collect_arguments())
    task = schedule_service.task(created["task"]["id"])
    collected = scheduler_data.collected(name="posts")[0]["collected_at"]
    moment = collected + timedelta(seconds=10)
    detail = scheduled_jobs.tick(
        GENERATE_SUMMARY, {"name": "posts", "interval_seconds": 60},
        data=scheduler_data, task=task, now=moment,
    )
    summary = detail["summary"]
    assert summary["total_records"] == 1
    assert summary["period_start"] == moment - timedelta(seconds=60)
    assert summary["period_end"] == moment
    numeric = summary["key_metrics"]["numeric"]
    assert {"count", "avg", "min", "max"} <= set(numeric["id"])
    assert summary["content"].startswith("Сводка «posts»")
    assert detail["aggregate"]["key_metrics"]["period_seconds"] == 60
    assert detail["aggregate"]["period_start"] == moment - timedelta(seconds=60)


def test_summary_tick_without_data_saves_empty_summary(schedule_service, scheduler_data):
    """Пустой период тоже даёт сводку: видно, что тик был, а данных не собралось."""
    created = schedule_service.create_task(
        tool=GENERATE_SUMMARY, arguments={"name": "пусто", "interval_seconds": 30},
        run_now=False,
    )
    task = schedule_service.task(created["task"]["id"])
    detail = scheduled_jobs.tick(GENERATE_SUMMARY, task["arguments"], data=scheduler_data,
                                 task=task, now=NOW)
    assert detail["summary"]["total_records"] == 0
    assert "записей не собрано" in detail["summary"]["content"]
    assert scheduler_data.notifications()[0]["kind"] == NOTIFICATION_SUMMARY


def test_tick_of_missing_task_is_rejected(schedule_service):
    """Тик удалённой задачи — отказ ``not_found``, а не запись в пустоту."""
    with pytest.raises(ScheduleRejected):
        schedule_service.run_task_now(777)
