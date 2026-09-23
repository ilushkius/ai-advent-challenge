"""Хранилище задач планировщика в SQLite (день 18): ``SchedulerStore``.

Здесь живёт строка ``scheduled_tasks`` и её журнал ``task_runs``: создание задачи,
её состояние, метки запусков и запись одного запуска. Правила («какие переходы
состояния допустимы», «какой инструмент знает день») — в домене
(``scheduler_fsm``, ``schedule_spec``); хранилище их не повторяет, поэтому
тестируется без автомата и без планировщика.

Зачем хранилище вообще нужно, если планировщик держит задачи в памяти: APScheduler
не переживает перезапуск процесса, а задание дня требует, чтобы задачи переживали.
``scheduled_tasks`` — источник правды; APScheduler получает из него набор задач
(``TaskScheduler.sync_from_db``) и отдаёт обратно ``next_run_at``, когда расписание
знает только он (cron).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from ..domain.scheduler_values import ScheduledTaskState
from ..models.scheduler import ScheduledTask, SchedulerTaskRun
from . import database
from .scheduler_rows import as_utc, run_dict, task_dict

__all__ = ["ScheduledTaskNotFoundError", "SchedulerStore"]


class ScheduledTaskNotFoundError(Exception):
    """Задачи с таким id нет в БД (роутер отвечает 404)."""


class SchedulerStore:
    """Строки scheduled_tasks/task_runs: задачи планировщика и их запуски."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``TaskStateStore``)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- задачи ---
    def create_task(self, *, name: str, tool_name: str, arguments: dict[str, Any],
                    schedule_type: str, schedule_value: dict[str, Any],
                    status: str = ScheduledTaskState.ACTIVE.value,
                    next_run_at: Optional[datetime] = None) -> dict[str, Any]:
        """Заводит задачу планировщика и возвращает её запись."""
        with self.session() as session:
            row = ScheduledTask(
                name=name,
                tool_name=tool_name,
                arguments=dict(arguments or {}),
                schedule_type=schedule_type,
                schedule_value=dict(schedule_value or {}),
                status=status,
                next_run_at=next_run_at,
            )
            session.add(row)
            session.commit()
            return task_dict(row)

    def task(self, task_id: int) -> Optional[dict[str, Any]]:
        """Задача по id (``None`` — нет такой)."""
        with self.session() as session:
            row = self._find(session, task_id)
            return task_dict(row) if row is not None else None

    def task_row(self, session, task_id: int) -> ScheduledTask:
        """Строка задачи в уже открытой сессии или ``ScheduledTaskNotFoundError``."""
        row = self._find(session, task_id)
        if row is None:
            raise ScheduledTaskNotFoundError(f"Задача планировщика {task_id} не найдена")
        return row

    def list_tasks(self, status: Optional[str] = None,
                   limit: int = 100) -> List[dict[str, Any]]:
        """Задачи по возрастанию id, при желании — только одного состояния."""
        with self.session() as session:
            query = session.query(ScheduledTask)
            if status:
                query = query.filter(ScheduledTask.status == status)
            rows = (query.order_by(ScheduledTask.id.asc())
                    .limit(max(1, int(limit))).all())
            return [task_dict(row) for row in rows]

    def active_tasks(self) -> List[dict[str, Any]]:
        """Активные задачи по возрастанию id — их подхватывает сверка планировщика."""
        return self.list_tasks(status=ScheduledTaskState.ACTIVE.value,
                               limit=10 ** 6)

    def due_tasks(self, now: datetime) -> List[dict[str, Any]]:
        """Активные задачи, у которых срок наступил (``next_run_at`` пуст или прошёл)."""
        moment = as_utc(now)
        return [
            row for row in self.active_tasks()
            if row["next_run_at"] is None or row["next_run_at"] <= moment
        ]

    def delete_task(self, task_id: int) -> bool:
        """Удаляет задачу вместе с её запусками (каскад). ``False`` — задачи не было."""
        with self.session() as session:
            row = self._find(session, task_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def set_arguments(self, task_id: int, arguments: dict[str, Any]) -> dict[str, Any]:
        """Переписывает аргументы задачи (регистрация дописывает ``reminder_id``).

        Нужен ровно для одного шага: разовое напоминание создаётся до того, как
        появляется строка в ``reminders``, а тик обязан знать её номер. Без этой
        записи повторный запуск создал бы второе напоминание вместо выдачи первого.
        """
        with self.session() as session:
            row = self.task_row(session, task_id)
            row.arguments = dict(arguments or {})
            session.commit()
            return task_dict(row)

    def set_status(self, task_id: int, status: str) -> dict[str, Any]:
        """Меняет состояние задачи (значение ``ScheduledTaskState``)."""
        with self.session() as session:
            row = self.task_row(session, task_id)
            row.status = status
            session.commit()
            return task_dict(row)

    def set_next_run(self, task_id: int, next_run_at: Optional[datetime],
                     status: Optional[str] = None) -> dict[str, Any]:
        """Записывает момент следующего запуска (и, если задано, состояние).

        Единственный путь записи расписания в БД: им пользуются регистрация задачи,
        возобновление с паузы, тик (после запуска) и сверка с APScheduler — поэтому
        ``next_run_at`` в строке всегда соответствует тому, что знает планировщик.
        """
        with self.session() as session:
            row = self.task_row(session, task_id)
            row.next_run_at = next_run_at
            if status is not None:
                row.status = status
            session.commit()
            return task_dict(row)

    # --- запуски ---
    def record_run(self, task_id: int, *, phase: str, status: str,
                   started_at: datetime, finished_at: datetime,
                   duration_ms: int, detail: Optional[dict] = None,
                   error: Optional[str] = None,
                   last_run_at: Optional[datetime] = None,
                   next_run_at: Optional[datetime] = None,
                   task_status: Optional[str] = None) -> dict[str, Any]:
        """Записывает один запуск и, одной транзакцией с ним, метки самой задачи."""
        with self.session() as session:
            row = self.task_row(session, task_id)
            run = SchedulerTaskRun(
                task_id=row.id, phase=phase, status=status,
                started_at=started_at, finished_at=finished_at,
                duration_ms=int(duration_ms),
                detail=dict(detail) if detail is not None else None,
                error=error,
            )
            session.add(run)
            if last_run_at is not None:
                row.last_run_at = last_run_at
            if next_run_at is not None or task_status is not None:
                row.next_run_at = next_run_at
            if task_status is not None:
                row.status = task_status
            session.commit()
            return run_dict(run)

    def runs(self, task_id: int, limit: int = 50) -> List[dict[str, Any]]:
        """История запусков задачи по убыванию времени начала (свежие — первыми)."""
        with self.session() as session:
            self.task_row(session, task_id)
            rows = (
                session.query(SchedulerTaskRun)
                .filter(SchedulerTaskRun.task_id == task_id)
                .order_by(SchedulerTaskRun.started_at.desc(), SchedulerTaskRun.id.desc())
                .limit(max(1, int(limit)))
                .all()
            )
            return [run_dict(row) for row in rows]

    def _find(self, session, task_id: int) -> Optional[ScheduledTask]:
        """Строка задачи по id (``None`` — нет такой)."""
        return session.query(ScheduledTask).filter(ScheduledTask.id == int(task_id)).first()
