"""Планировщик фоновых задач процесса (день 18): ``TaskScheduler``.

Зачем он нужен. APScheduler держит задачи в памяти и не переживает перезапуск
процесса, а задание дня требует, чтобы задачи переживали. Поэтому источник правды —
таблица ``scheduled_tasks``: ``sync_from_db`` доводит набор задач APScheduler до
того, что лежит в БД (добавляет пропавшие, убирает удалённые, подтягивает
``next_run_at``), и делает это не только при старте, но и по таймеру раз в
``SCHEDULER_SYNC_SECONDS`` — так задача, созданная в другом процессе
(MCP-сервер добавляет её через ``POST /scheduler/tasks``), подхватывается сама.

Три правила, которые нельзя нарушить:

1. **Тик — синхронная функция.** APScheduler 3.x в ``AsyncIOExecutor`` выполняет
   не-корутины в пуле потоков, поэтому фон не блокирует цикл событий FastAPI.
   Сессии SQLite уже открываются с ``check_same_thread=False``
   (``shared/db_base.make_engine``), так что запись из потока безопасна.
2. **Исключение внутри тика не валит планировщик.** ``run_tick`` ловит всё: запуск
   пишется в ``task_runs`` со ``status="error"``, пользователь получает
   уведомление, а задача остаётся активной и повторится на следующем тике.
3. **Тик не ходит через MCP.** MCP-соединение принадлежит пользователю и держит
   блокировку клиента, поэтому вызов инструмента из фонового потока был бы
   дедлоком. Тик вызывает функции домена (``scheduled_jobs``), а инструмент —
   лишь тонкая обёртка над ``POST /scheduler/tasks``.

Знание про классы APScheduler вынесено в ``apscheduler_bridge.py``: здесь — правила
дня, там — обвязка библиотеки. Расписание задачи записывается в БД ВСЕГДА: при
регистрации — расчётное значение, после тика — фактическое ``job.next_run_time``
(для cron его иначе негде взять).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from shared.logging_utils import get_logger

from ..core import config
from ..domain.schedule_spec import ScheduleRejected
from ..domain.schedule_timing import next_run_at
from ..domain.scheduler_fsm import (
    ScheduledTaskEvent,
    ScheduledTaskFSM,
    UnknownSchedulerEvent,
)
from ..domain.scheduler_values import (
    REASON_NOT_ACTIVE,
    REASON_NOT_FOUND,
    REASON_NOT_PAUSED,
    RUN_PHASE_TICK,
    RunStatus,
    ScheduleType,
    ScheduledTaskState,
)
from ..storage.scheduler_data_store import SchedulerDataStore
from ..storage.scheduler_rows import as_utc, jsonable
from ..storage.scheduler_store import SchedulerStore
from . import apscheduler_bridge as bridge
from . import scheduled_jobs
from .source_fetch import fetch_json

__all__ = ["TaskScheduler", "get_scheduler"]

logger = get_logger(__name__)

#: Сколько строк читает сверка (защита от бесконечного списка задач).
SYNC_LIMIT = 1000


class TaskScheduler:
    """Фоновый планировщик процесса: задачи из БД, тики в пуле потоков APScheduler."""

    def __init__(self, store: Optional[SchedulerStore] = None,
                 data: Optional[SchedulerDataStore] = None,
                 session_factory=None,
                 jobs: Optional[Callable[[dict], Callable[[], None]]] = None,
                 fetch: Callable[..., Any] = fetch_json) -> None:
        self._store = store or SchedulerStore(session_factory=session_factory)
        self._data = data or SchedulerDataStore(session_factory=session_factory)
        self._jobs = jobs
        self._fetch = fetch
        self._scheduler = None

    # --- жизненный цикл ---
    @property
    def running(self) -> bool:
        """Идёт ли обслуживание таймеров прямо сейчас."""
        return self._scheduler is not None and bool(self._scheduler.running)

    def start(self) -> None:
        """Запускает APScheduler, ставит сверку и поднимает задачи из БД.

        Вызывается из ``lifespan`` FastAPI (внутри работающего цикла событий) —
        ``AsyncIOScheduler`` берёт текущий цикл и дальше только планирует в нём.
        Повторный вызов — безопасный no-op: у процесса один планировщик.
        """
        if self.running:
            return
        scheduler = bridge.make_scheduler()
        scheduler.start()
        self._scheduler = scheduler
        bridge.add_reconcile_job(scheduler, self._reconcile,
                                 config.SCHEDULER_SYNC_SECONDS)
        active = self.sync_from_db()
        logger.debug("Планировщик запущен: активных задач %d", active)

    def shutdown(self) -> None:
        """Останавливает планировщик (lifespan). Повторный вызов — no-op."""
        scheduler = self._scheduler
        if scheduler is None:
            return
        self._scheduler = None
        bridge.shutdown_scheduler(scheduler)
        logger.debug("Планировщик остановлен")

    def status(self) -> dict[str, Any]:
        """Состояние планировщика для ``GET /scheduler/status``."""
        scheduler = self._scheduler
        pending = 0
        timezone_name = config.SCHEDULER_TIMEZONE
        if scheduler is not None:
            timezone_name = str(scheduler.timezone)
            pending = sum(1 for job in scheduler.get_jobs()
                          if bridge.job_task_id(job.id) is not None)
        return {
            "running": self.running,
            "timezone": timezone_name,
            "pending_jobs": pending,
            "sync_seconds": config.SCHEDULER_SYNC_SECONDS,
        }

    # --- сверка БД и планировщика ---
    def sync_from_db(self) -> int:
        """Приводит набор задач APScheduler к строкам ``scheduled_tasks``.

        Три работы: убрать job'ы удалённых задач, поставить job'ы новых активных
        задач и записать в БД фактическое ``next_run_time`` (в том числе для cron,
        где ближайший запуск знает только планировщик). Возвращает число активных
        задач — то же, что показывает список задач.
        """
        tasks = self._store.list_tasks(limit=SYNC_LIMIT)
        known = {task["id"] for task in tasks}
        active = [task for task in tasks
                  if task["status"] == ScheduledTaskState.ACTIVE.value]
        if self._scheduler is not None:
            for job in list(self._scheduler.get_jobs()):
                task_id = bridge.job_task_id(job.id)
                if task_id is not None and task_id not in known:
                    self.unregister(task_id)
            for task in active:
                try:
                    self._ensure_job(task)
                except Exception as exc:  # noqa: BLE001 — одна задача не мешает другим
                    logger.warning(
                        "Планировщик: задача %s не поставлена: %s", task["id"], exc
                    )
            for task in self._store.due_tasks(datetime.now(timezone.utc)):
                self._catch_up(task)
        return len(active)

    def register(self, task: dict[str, Any]) -> dict[str, Any]:
        """Ставит задачу в APScheduler и записывает расчётный ``next_run_at``.

        Пропущенный запуск «догоняется»: если расчётный момент уже прошёл (пока
        приложение было выключено), задача выполняется сразу — так напоминание не
        теряется, а сбор не ждёт целый период. Планировщик не запущен (тесты,
        скрипты) — расписание всё равно считается и ложится в БД.
        """
        moment = self._planned_next_run(task)
        if self._scheduler is None:
            return self._store.set_next_run(task["id"], moment)
        job = bridge.add_task_job(self._scheduler, task, moment,
                                  self._job_callable(task))
        return self._store.set_next_run(
            task["id"], as_utc(bridge.job_next_run_time(job)) or moment
        )

    def unregister(self, task_id: int) -> None:
        """Снимает задачу с обслуживания (без изменения строки БД)."""
        if self._scheduler is None:
            return
        bridge.remove_task_job(self._scheduler, task_id)

    # --- состояние задачи ---
    def pause(self, task_id: int) -> dict[str, Any]:
        """Ставит задачу на паузу: ``ACTIVE`` → ``PAUSED`` (иначе 409-класс отказа).

        Найденный момент следующего запуска сохраняется: он понадобится, когда
        задачу возобновят, — а ``job.pause()`` очищает расписание только в памяти
        планировщика.
        """
        task = self._require_task(task_id)
        state = self._apply_event(task, ScheduledTaskEvent.PAUSE, REASON_NOT_ACTIVE)
        job = self._job(task_id)
        if job is not None:
            bridge.pause_job(job)
        return self._store.set_status(task_id, state.value)

    def resume(self, task_id: int) -> dict[str, Any]:
        """Возвращает задачу к работе: ``PAUSED`` → ``ACTIVE`` (иначе отказ).

        Если job сохранился (пауза в живом планировщике), расписание берётся у него;
        если задача стояла на паузе через перезапуск, job'а нет — задача ставится
        заново, с расчётом от её последнего запуска.
        """
        task = self._require_task(task_id)
        state = self._apply_event(task, ScheduledTaskEvent.RESUME, REASON_NOT_PAUSED)
        self._store.set_status(task_id, state.value)
        job = self._job(task_id)
        if job is None:
            return self.register(self._store.task(task_id))
        bridge.resume_job(job)
        return self._store.set_next_run(
            task_id, as_utc(bridge.job_next_run_time(job)) or task["next_run_at"]
        )

    # --- запуск ---
    def run_tick(self, task_id: int) -> dict[str, Any]:
        """Выполняет один запуск задачи целиком и записывает его в журнал.

        Единственная точка исполнения тика: ею пользуются задача APScheduler,
        ``POST /scheduler/tasks/{id}/run`` и тесты. Исключение инструмента не
        выходит наружу — запуск пишется со ``status="error"``, задача остаётся
        активной и повторится.
        """
        task = self._require_task(task_id)
        started = datetime.now(timezone.utc)
        clock = time.perf_counter()
        status = RunStatus.OK.value
        error: Optional[str] = None
        detail: Any = None
        try:
            detail = scheduled_jobs.tick(
                task["tool_name"], task["arguments"],
                data=self._data, task=task, fetch=self._fetch, now=started,
            )
        except Exception as exc:  # noqa: BLE001 — сбой инструмента не валит планировщик
            status = RunStatus.ERROR.value
            error = str(exc)
            logger.warning("Планировщик: задача %s завершилась ошибкой: %s", task_id, exc)
        finished = datetime.now(timezone.utc)
        duration_ms = int((time.perf_counter() - clock) * 1000)
        completed = (task["schedule_type"] == ScheduleType.DATE.value
                     and status == RunStatus.OK.value)
        task_status = ScheduledTaskState.COMPLETED.value if completed else None
        next_moment = None if completed else self._next_run_after(task)
        run = self._store.record_run(
            task_id, phase=RUN_PHASE_TICK, status=status, started_at=started,
            finished_at=finished, duration_ms=duration_ms, detail=jsonable(detail),
            error=error, last_run_at=finished, next_run_at=next_moment,
            task_status=task_status,
        )
        if completed:
            self.unregister(task_id)
            logger.debug("Планировщик: разовая задача %s выполнена и снята", task_id)
        return run

    # --- внутреннее ---
    def _require_task(self, task_id: int) -> dict[str, Any]:
        """Строка задачи или ``ScheduleRejected(REASON_NOT_FOUND)``."""
        task = self._store.task(task_id)
        if task is None:
            raise ScheduleRejected(
                REASON_NOT_FOUND, f"Задача планировщика {task_id} не найдена"
            )
        return task

    def _ensure_job(self, task: dict[str, Any]) -> None:
        """Ставит job задачи, если его нет, иначе подтягивает ``next_run_at`` из него."""
        job = self._job(task["id"])
        if job is None:
            self.register(task)
            return
        moment = as_utc(bridge.job_next_run_time(job))
        if moment is not None and moment != task["next_run_at"]:
            self._store.set_next_run(task["id"], moment)

    def _apply_event(self, task: dict[str, Any], event: ScheduledTaskEvent,
                     reason_code: str) -> ScheduledTaskState:
        """Прогоняет состояние задачи через её FSM, отказ — ``ScheduleRejected``."""
        try:
            return ScheduledTaskFSM(ScheduledTaskState(task["status"])).handle(event)
        except (UnknownSchedulerEvent, ValueError) as exc:
            raise ScheduleRejected(reason_code, str(exc)) from exc

    def _planned_next_run(self, task: dict[str, Any]) -> Optional[datetime]:
        """Расчётный момент следующего запуска (не раньше «сейчас»)."""
        now = datetime.now(timezone.utc)
        moment = next_run_at(task["schedule_type"], task["schedule_value"], now,
                             task["last_run_at"])
        if moment is None:
            return None
        return moment if moment > now else now

    def _next_run_after(self, task: dict[str, Any]) -> Optional[datetime]:
        """Момент следующего запуска после тика: у запущенного планировщика — из job'а.

        Для cron это единственный источник: расписание триггера вычисляется внутри
        APScheduler, и повторять его разбор в домене нельзя.
        """
        job = self._job(task["id"])
        moment = as_utc(bridge.job_next_run_time(job))
        if moment is not None:
            return moment
        now = datetime.now(timezone.utc)
        return next_run_at(task["schedule_type"], task["schedule_value"], now,
                           task["last_run_at"] or now)

    def _job_callable(self, task: dict[str, Any]) -> Callable[[], None]:
        """Функция, которую выполняет APScheduler: тик этой же задачи."""
        if self._jobs is not None:
            return self._jobs(task)
        task_id = task["id"]

        def run() -> None:
            self._tick(task_id)

        return run

    def _job(self, task_id: int):
        """Job задачи в запущенном планировщике (``None`` — его нет)."""
        if self._scheduler is None:
            return None
        return self._scheduler.get_job(bridge.task_job_id(task_id))

    def _catch_up(self, task: dict[str, Any]) -> None:
        """Догоняет пропущенный запуск: переносит ближайший запуск на «сейчас».

        Строка задачи говорит, что момент наступил, а планировщик ещё ждёт
        будущего — значит запуск был пропущен (процесс стоял). Обратный случай
        (job раньше строки) не трогаем: его закрывает сама APScheduler.
        """
        job = self._job(task["id"])
        moment = as_utc(bridge.job_next_run_time(job))
        if moment is None:
            return
        now = datetime.now(timezone.utc)
        if moment <= now:
            return
        logger.debug("Планировщик: догоняю пропущенный запуск задачи %s", task["id"])
        bridge.reschedule_job_now(job, now)

    def _tick(self, task_id: int) -> None:
        """Тело задачи APScheduler: запуск с логом и без падения наружу."""
        try:
            run = self.run_tick(task_id)
        except Exception as exc:  # noqa: BLE001 — задача удалена или БД недоступна
            logger.warning("Планировщик: тик задачи %s не выполнен: %s", task_id, exc)
        else:
            logger.debug("Планировщик: задача %s отработала (%s)", task_id, run["status"])

    def _reconcile(self) -> None:
        """Служебный тик: сверка БД и планировщика (подхват чужих изменений)."""
        try:
            self.sync_from_db()
        except Exception as exc:  # noqa: BLE001 — сверка не должна падать молча
            logger.warning("Планировщик: сверка не выполнена: %s", exc)


_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """Единственный планировщик процесса (ленивый singleton, как ``get_mcp_registry``)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
