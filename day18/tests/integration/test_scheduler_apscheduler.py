"""Настоящая связка с APScheduler (день 18).

Единственный тест дня, который ждёт таймер: остальные проверяют тик напрямую.
Здесь важно, что фон действительно работает САМ — задача с периодом в секунду
должна оставить в журнале запусков строку фазы ``tick`` без единого ручного вызова
``run_tick``, — и что остановка не ломает цикл событий (``lifespan`` зовёт
``shutdown`` при выходе приложения).
"""
import asyncio
import time

from backend.domain.scheduler_values import RUN_PHASE_TICK
from backend.services.schedule_service import ScheduleService
from backend.services.scheduler import TaskScheduler
from backend.storage.scheduler_data_store import SchedulerDataStore
from backend.storage.scheduler_store import SchedulerStore

from scheduler_fakes import FakeFetcher

#: Сколько ждать первого автоматического запуска (секунд).
TICK_TIMEOUT = 15.0

ONE_SECOND = {"source_url": "https://example.test/fast", "interval_seconds": 1,
              "name": "fast"}


def test_scheduler_runs_jobs_by_itself(session_factory):
    """Задача с периодом в секунду срабатывает сама, а планировщик встаёт по команде."""
    fetcher = FakeFetcher()
    store = SchedulerStore(session_factory=session_factory)
    data = SchedulerDataStore(session_factory=session_factory)
    scheduler = TaskScheduler(store=store, data=data, fetch=fetcher)
    service = ScheduleService(scheduler=scheduler, store=store, data=data, fetch=fetcher)

    async def scenario() -> dict:
        scheduler.start()
        assert scheduler.status()["running"] is True
        task_id = service.create_task(tool="collect_data", arguments=ONE_SECOND)["task"]["id"]
        deadline = time.monotonic() + TICK_TIMEOUT
        ticks = []
        while time.monotonic() < deadline and not ticks:
            ticks = [run for run in store.runs(task_id) if run["phase"] == RUN_PHASE_TICK]
            await asyncio.sleep(0.2)
        task = store.task(task_id)
        scheduler.shutdown()
        # Цикл событий жив после остановки планировщика: lifespan завершается штатно.
        await asyncio.sleep(0.05)
        return {"ticks": ticks, "task": task, "running": scheduler.status()["running"],
                "collected": data.collected_count(name="fast")}

    result = asyncio.run(scenario())
    assert result["ticks"], "фоновый запуск не состоялся"
    assert result["ticks"][0]["status"] == "ok"
    assert result["ticks"][0]["detail"]["collection"]["records_saved"] == 1
    assert result["collected"] >= 2  # первая запись при регистрации + хотя бы один тик
    assert result["task"]["last_run_at"] is not None
    assert result["task"]["next_run_at"] > result["task"]["last_run_at"]
    assert result["running"] is False


def test_scheduler_stops_cleanly_without_jobs(session_factory):
    """Остановка планировщика без задач и повторный вызов — безопасные no-op."""
    scheduler = TaskScheduler(store=SchedulerStore(session_factory=session_factory),
                              data=SchedulerDataStore(session_factory=session_factory),
                              fetch=FakeFetcher())

    async def scenario() -> dict:
        scheduler.start()
        first = scheduler.status()
        scheduler.shutdown()
        scheduler.shutdown()
        return {"first": first, "after": scheduler.status()}

    result = asyncio.run(scenario())
    assert result["first"]["running"] is True
    assert result["first"]["pending_jobs"] == 0
    assert result["after"]["running"] is False
