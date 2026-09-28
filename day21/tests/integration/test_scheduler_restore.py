"""Восстановление задач планировщика после перезапуска процесса (день 18).

Главное требование дня проверяется здесь: APScheduler держит задачи в памяти и не
переживает рестарт, поэтому источник правды — таблица ``scheduled_tasks``. Тест
поднимает планировщик, создаёт задачи, останавливает его (как это делает
``lifespan`` при выходе) и поднимает НОВЫЙ планировщик на той же БД: задачи должны
вернуться, просроченный запуск — не оказаться в прошлом, пауза и завершение —
сохраниться, а удалённая задача — не вернуться.

В отличие от остальных тестов дня здесь запускается настоящий APScheduler: он
требует работающего цикла событий, поэтому сценарии обёрнуты в ``asyncio.run``.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from backend.services.schedule_service import ScheduleService
from backend.services.scheduler import TaskScheduler
from backend.storage.scheduler_data_store import SchedulerDataStore
from backend.storage.scheduler_store import SchedulerStore

from scheduler_fakes import FakeFetcher

COLLECT = {"source_url": "https://example.test/posts", "interval_seconds": 10,
           "name": "posts"}


def _stack(session_factory, fetcher):
    """Планировщик и сервис на одной временной БД (как два «процесса» дня)."""
    store = SchedulerStore(session_factory=session_factory)
    data = SchedulerDataStore(session_factory=session_factory)
    scheduler = TaskScheduler(store=store, data=data, fetch=fetcher)
    service = ScheduleService(scheduler=scheduler, store=store, data=data, fetch=fetcher)
    return scheduler, service


def _first_process(session_factory, fetcher):
    """Первый «процесс»: создаёт задачи и останавливается."""
    async def scenario() -> dict:
        scheduler, service = _stack(session_factory, fetcher)
        scheduler.start()
        collect = service.create_task(tool="collect_data", arguments=COLLECT)["task"]
        reminder = service.create_task(
            tool="schedule_reminder",
            arguments={"text": "почта", "delay_seconds": 3600},
        )["task"]
        paused = service.create_task(tool="collect_data", arguments=COLLECT,
                                     run_now=False)["task"]
        service.pause_task(paused["id"])
        doomed = service.create_task(tool="collect_data", arguments=COLLECT,
                                     run_now=False)["task"]
        service.delete_task(doomed["id"])
        scheduler.shutdown()
        return {"collect": collect, "reminder": reminder, "paused": paused,
                "doomed": doomed["id"]}

    return asyncio.run(scenario())


def test_tasks_survive_restart(session_factory):
    """После перезапуска задачи на месте: активные поставлены, пауза сохранена."""
    fetcher = FakeFetcher()
    created = _first_process(session_factory, fetcher)

    async def scenario() -> dict:
        scheduler, service = _stack(session_factory, fetcher)
        scheduler.start()
        # Сверка — то, что делает lifespan при старте: она и поднимает задачи.
        active = scheduler.sync_from_db()
        status = scheduler.status()
        tasks = {task["id"]: task for task in service.list_tasks()["tasks"]}
        history = service.task_history(created["collect"]["id"])
        scheduler.shutdown()
        return {"active": active, "status": status, "tasks": tasks,
                "runs": history["count"], "fetcher_calls": fetcher.call_count}

    result = asyncio.run(scenario())
    now = datetime.now(timezone.utc)

    assert result["active"] == 2  # сбор и напоминание; пауза и удалённая — нет
    assert result["status"]["running"] is True
    assert result["status"]["pending_jobs"] == 2

    collect = result["tasks"][created["collect"]["id"]]
    assert collect["status"] == "active"
    assert collect["next_run_at"] is not None and collect["next_run_at"] >= now - timedelta(seconds=1)
    assert result["runs"] >= 1  # журнал запусков тоже пережил перезапуск

    reminder = result["tasks"][created["reminder"]["id"]]
    assert reminder["status"] == "active" and reminder["next_run_at"] > now

    paused = result["tasks"][created["paused"]["id"]]
    assert paused["status"] == "paused"
    assert created["doomed"] not in result["tasks"]


def test_overdue_interval_task_is_caught_up(session_factory):
    """Пропущенный запуск не ждёт целый период: момент запуска не остаётся в прошлом."""
    fetcher = FakeFetcher()
    store = SchedulerStore(session_factory=session_factory)
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    store.create_task(
        name="Сбор: posts", tool_name="collect_data", arguments=COLLECT,
        schedule_type="interval", schedule_value={"seconds": 10},
        next_run_at=stale,
    )

    async def scenario() -> dict:
        scheduler, service = _stack(session_factory, fetcher)
        scheduler.start()
        scheduler.sync_from_db()
        task = service.list_tasks()["tasks"][0]
        scheduler.shutdown()
        return task

    task = asyncio.run(scenario())
    assert task["next_run_at"] > stale
    assert task["next_run_at"] >= datetime.now(timezone.utc) - timedelta(seconds=1)


def test_restart_does_not_duplicate_tasks(session_factory):
    """Повторный старт на той же БД не размножает задачи и job'ы."""
    fetcher = FakeFetcher()
    _first_process(session_factory, fetcher)

    async def scenario() -> tuple[int, int]:
        scheduler, service = _stack(session_factory, fetcher)
        scheduler.start()
        first = scheduler.status()["pending_jobs"]
        scheduler.sync_from_db()
        scheduler.sync_from_db()
        second = scheduler.status()["pending_jobs"]
        count = service.list_tasks()["count"]
        scheduler.shutdown()
        return first, second, count

    first, second, count = asyncio.run(scenario())
    assert first == second == 2
    assert count == 3  # две активные + одна на паузе
