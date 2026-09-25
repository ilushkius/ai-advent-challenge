"""Создание задач планировщика и управление ими (день 18).

Проверяется путь, которым пользуются и MCP-инструмент, и интерфейс: проверка
аргументов, расписание, немедленное действие, строка в ``scheduled_tasks``,
журнал запусков и отказы с КОДАМИ причин. Отдельно — что при отказе ничего не
создаётся и что пауза/возобновление идут через стейт-машину, а не «на глазок».
"""
from datetime import datetime, timezone

import pytest

from backend.core import config
from backend.domain.schedule_spec import COLLECT_DATA, GENERATE_SUMMARY, SCHEDULE_REMINDER, ScheduleRejected
from backend.domain.scheduler_values import (
    REASON_BAD_ARGUMENTS,
    REASON_BAD_URL,
    REASON_NOT_ACTIVE,
    REASON_NOT_FOUND,
    REASON_NOT_PAUSED,
    REASON_UNKNOWN_TOOL,
    RUN_PHASE_PREPARE,
    ScheduledTaskState,
)

COLLECT = {"source_url": "https://example.test/posts", "interval_seconds": 10,
           "name": "posts"}


def test_create_collect_task_registers_and_collects_once(schedule_service, scheduler_data):
    """Сбор ставится в планировщик, а первая запись собирается сразу."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)
    task = created["task"]
    assert task["schedule_type"] == "interval"
    assert task["schedule_value"] == {"seconds": 10}
    assert task["schedule_label"] == "каждые 10 с"
    assert task["status"] == ScheduledTaskState.ACTIVE.value
    assert task["next_run_at"] is not None
    assert created["result"]["collection"]["records_saved"] == 1
    assert scheduler_data.collected_count(name="posts") == 1


def test_create_reminder_links_task_and_reminder(schedule_service, scheduler_data):
    """Разовое напоминание сохраняется, а его номер уходит в аргументы задачи.

    Иначе тик не знал бы, какую строку помечать выполненной, и повторный запуск
    создавал бы второе напоминание вместо выдачи первого.
    """
    created = schedule_service.create_task(
        tool=SCHEDULE_REMINDER, arguments={"text": "проверить почту", "delay_seconds": 30}
    )
    task = created["task"]
    reminders = scheduler_data.reminders()
    assert len(reminders) == 1
    assert reminders[0]["text"] == "проверить почту"
    assert task["arguments"]["reminder_id"] == reminders[0]["id"]
    assert task["schedule_type"] == "date"
    assert reminders[0]["task_id"] == task["id"]
    assert datetime.fromisoformat(task["schedule_value"]["run_date"]) > datetime.now(timezone.utc)


def test_create_summary_counts_first_period(schedule_service, scheduler_data):
    """Первая сводка считается сразу за прошедший интервал и сохраняется."""
    created = schedule_service.create_task(
        tool=GENERATE_SUMMARY, arguments={"name": "posts", "interval_seconds": 20}
    )
    assert created["result"]["summary"]["total_records"] == 0  # сбор ещё не шёл
    assert created["result"]["aggregate"]["key_metrics"]["period_seconds"] == 20
    assert scheduler_data.summaries()[0]["name"] == "posts"


def test_run_now_false_skips_immediate_step(schedule_service, scheduler_data):
    """``run_now=False`` — задача создаётся, но немедленного действия нет."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT,
                                          run_now=False)
    assert created["immediate"] is False
    assert created["result"] is None
    assert scheduler_data.collected_count(name="posts") == 0
    assert [run["phase"] for run in schedule_service.task_history(created["task"]["id"])["runs"]] == []


def test_prepare_run_is_journalled(schedule_service):
    """Немедленное действие попадает в журнал запусков фазой ``prepare``."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)
    runs = schedule_service.task_history(created["task"]["id"])["runs"]
    assert [run["phase"] for run in runs] == [RUN_PHASE_PREPARE]
    assert runs[0]["status"] == "ok"
    assert runs[0]["detail"]["collection"]["records_saved"] == 1


def test_failed_immediate_step_keeps_task(schedule_service, scheduler_data, fetcher):
    """Сбой источника не отменяет задачу: причина видна, попытка повторится."""
    fetcher.fail("источник недоступен")
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)
    assert created["error"] == "источник недоступен"
    assert created["result"] is None
    assert created["task"]["status"] == ScheduledTaskState.ACTIVE.value
    runs = schedule_service.task_history(created["task"]["id"])["runs"]
    assert runs[0]["phase"] == RUN_PHASE_PREPARE and runs[0]["status"] == "error"


@pytest.mark.parametrize("tool,arguments,reason", [
    ("нет такого", {}, REASON_UNKNOWN_TOOL),
    (COLLECT_DATA, {"source_url": "https://x.test/p", "interval_seconds": 0, "name": "p"},
     REASON_BAD_ARGUMENTS),
    (COLLECT_DATA, {"source_url": "не-url", "interval_seconds": 10, "name": "p"},
     REASON_BAD_URL),
])
def test_rejected_creation_creates_nothing(schedule_service, scheduler_store, tool,
                                           arguments, reason):
    """Отказ — данные с кодом причины, и в БД ничего не появляется."""
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_service.create_task(tool=tool, arguments=arguments)
    assert excinfo.value.reason_code == reason
    assert scheduler_store.list_tasks() == []


def test_manual_schedule_overrides_tool_default(schedule_service):
    """Ручное расписание сильнее выведенного: те же инструменты умеют ходить по cron."""
    created = schedule_service.create_task(
        tool=COLLECT_DATA, arguments=COLLECT, schedule_type="cron",
        schedule_value={"cron": "*/5 * * * *"}, run_now=False,
    )
    assert created["task"]["schedule_type"] == "cron"
    assert created["task"]["next_run_at"] is None  # ближайший запуск знает планировщик


def test_pause_and_resume_go_through_fsm(schedule_service, scheduler_store):
    """Пауза и возобновление меняют состояние; повторный шаг — отказ с кодом."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)
    task_id = created["task"]["id"]
    assert schedule_service.pause_task(task_id)["status"] == ScheduledTaskState.PAUSED.value
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_service.pause_task(task_id)
    assert excinfo.value.reason_code == REASON_NOT_ACTIVE
    assert scheduler_store.task(task_id)["status"] == ScheduledTaskState.PAUSED.value
    assert schedule_service.resume_task(task_id)["status"] == ScheduledTaskState.ACTIVE.value
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_service.resume_task(task_id)
    assert excinfo.value.reason_code == REASON_NOT_PAUSED


def test_paused_task_is_not_run_by_schedule_but_can_run_manually(schedule_service, scheduler_store):
    """Пауза не мешает ручному запуску: ``run`` — это явное действие пользователя."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)
    task_id = created["task"]["id"]
    schedule_service.pause_task(task_id)
    run = schedule_service.run_task_now(task_id)
    assert run["phase"] == "tick" and run["status"] == "ok"
    assert scheduler_store.task(task_id)["status"] == ScheduledTaskState.PAUSED.value


def test_delete_task_removes_runs(schedule_service, scheduler_store):
    """Удаление задачи уносит её журнал запусков (каскад внешнего ключа)."""
    created = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)
    task_id = created["task"]["id"]
    assert schedule_service.delete_task(task_id) is True
    assert scheduler_store.task(task_id) is None
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_service.task_history(task_id)
    assert excinfo.value.reason_code == REASON_NOT_FOUND
    with pytest.raises(ScheduleRejected):  # повторное удаление — та же «не найдена»
        schedule_service.delete_task(task_id)


def test_unknown_task_is_not_found(schedule_service):
    """Неизвестный номер задачи — отказ ``not_found`` (роутер отвечает 404)."""
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_service.task(999)
    assert excinfo.value.reason_code == REASON_NOT_FOUND


def test_notifications_are_queued_and_marked_read(schedule_service):
    """Сводка кладёт уведомление в очередь, отметка «прочитано» его снимает."""
    schedule_service.create_task(tool=GENERATE_SUMMARY,
                                 arguments={"name": "posts", "interval_seconds": 20})
    payload = schedule_service.notifications()
    assert payload["count"] == 1 and payload["unread"] == 1
    notification_id = payload["notifications"][0]["id"]
    assert schedule_service.mark_notification_read(notification_id)["unread"] is False
    assert schedule_service.notifications()["unread"] == 0
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_service.mark_notification_read(999)
    assert excinfo.value.reason_code == REASON_NOT_FOUND


def test_tools_catalog_and_status(schedule_service):
    """Каталог инструментов и статус планировщика доступны сервису (их отдаёт API)."""
    tools = schedule_service.tools()
    assert [item["name"] for item in tools] == [SCHEDULE_REMINDER, COLLECT_DATA,
                                               GENERATE_SUMMARY]
    status = schedule_service.scheduler.status()
    assert status["running"] is False  # таймеры в этих тестах не запускаются
    assert status["sync_seconds"] == config.SCHEDULER_SYNC_SECONDS


def test_list_tasks_filters_by_status(schedule_service):
    """Список задач фильтруется по состоянию и отдаёт состояние планировщика."""
    first = schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT)["task"]
    schedule_service.create_task(tool=COLLECT_DATA, arguments=COLLECT, run_now=False)
    schedule_service.pause_task(first["id"])
    assert schedule_service.list_tasks(status="paused")["count"] == 1
    assert schedule_service.list_tasks()["count"] == 2
    assert "scheduler" in schedule_service.list_tasks()
