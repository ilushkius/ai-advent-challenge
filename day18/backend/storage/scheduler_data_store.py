"""Хранилище данных планировщика в SQLite (день 18): ``SchedulerDataStore``.

Таблицы, которые копят инструменты, а не планируют запуски: ``reminders``,
``collected_data``, ``periodic_summaries`` и ``notifications``. Отдельный модуль от
``SchedulerStore``, потому что это другой вопрос: там — «когда запускать», здесь —
«что инструменты сохранили».

Единственное место, где живёт правило выдачи напоминания: ``complete_reminder``
прогоняет состояние через ``ReminderFSM`` (``SCHEDULED`` → ``DONE``), поэтому
повторная выдача уже выполненного напоминания — явная ошибка
``UnknownSchedulerEvent``, а не «тихий» no-op. По той же причине отметка
«прочитано» на неизвестном уведомлении — ``NotificationNotFoundError``, а не
``None``: роутер отвечает 404 с понятным текстом.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from ..domain.scheduler_fsm import ReminderEvent, ReminderFSM
from ..domain.scheduler_values import ReminderState
from ..models.scheduler import (
    CollectedRecord,
    PeriodicSummary,
    Reminder,
    SchedulerNotification,
)
from . import database
from .scheduler_rows import (
    collected_dict,
    notification_dict,
    reminder_dict,
    summary_dict,
)

__all__ = [
    "NotificationNotFoundError",
    "ReminderNotFoundError",
    "SchedulerDataStore",
]


class ReminderNotFoundError(Exception):
    """Напоминания с таким id нет в БД."""


class NotificationNotFoundError(Exception):
    """Уведомления с таким id нет в БД."""


class SchedulerDataStore:
    """Строки reminders/collected_data/periodic_summaries/notifications."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- напоминания ---
    def add_reminder(self, *, text: str, remind_at: datetime,
                     task_id: Optional[int] = None) -> dict[str, Any]:
        """Сохраняет напоминание в состоянии ``scheduled``."""
        with self.session() as session:
            row = Reminder(
                text=text, remind_at=remind_at,
                status=ReminderState.SCHEDULED.value, task_id=task_id,
            )
            session.add(row)
            session.commit()
            return reminder_dict(row)

    def reminders(self, status: Optional[str] = None,
                  limit: int = 100) -> List[dict[str, Any]]:
        """Напоминания по возрастанию момента выдачи (ближайшие — первыми)."""
        with self.session() as session:
            query = session.query(Reminder)
            if status:
                query = query.filter(Reminder.status == status)
            rows = (query.order_by(Reminder.remind_at.asc(), Reminder.id.asc())
                    .limit(max(1, int(limit))).all())
            return [reminder_dict(row) for row in rows]

    def complete_reminder(self, reminder_id: int,
                          *, completed_at: datetime) -> dict[str, Any]:
        """Помечает напоминание выполненным (``FIRE``); повтор — ошибка FSM.

        Событие проводит состояние через ``ReminderFSM``: ``SCHEDULED`` → ``DONE``.
        Попытка выдать уже выданное напоминание бросает ``UnknownSchedulerEvent`` —
        это признак того, что задача сработала дважды, а не повод молча продолжать.
        """
        with self.session() as session:
            row = session.query(Reminder).filter(Reminder.id == int(reminder_id)).first()
            if row is None:
                raise ReminderNotFoundError(f"Напоминание {reminder_id} не найдено")
            machine = ReminderFSM(_state(row.status))
            machine.handle(ReminderEvent.FIRE)
            row.status = machine.state.value
            session.commit()
            record = reminder_dict(row)
            record["completed_at"] = completed_at
            return record

    def reminder_row(self, session, reminder_id: int) -> Reminder:
        """Строка напоминания в открытой сессии или ``ReminderNotFoundError``."""
        row = session.query(Reminder).filter(Reminder.id == int(reminder_id)).first()
        if row is None:
            raise ReminderNotFoundError(f"Напоминание {reminder_id} не найдено")
        return row

    # --- накопленные записи ---
    def add_collected(self, *, name: str, source_url: str, payload: Any,
                      collected_at: Optional[datetime] = None) -> dict[str, Any]:
        """Сохраняет одну запись сбора."""
        with self.session() as session:
            row = CollectedRecord(name=name, source_url=source_url, payload=payload)
            if collected_at is not None:
                row.collected_at = collected_at
            session.add(row)
            session.commit()
            return collected_dict(row)

    def collected(self, name: Optional[str] = None,
                  since: Optional[datetime] = None,
                  limit: int = 100) -> List[dict[str, Any]]:
        """Записи сбора по возрастанию времени (свежие — последними)."""
        with self.session() as session:
            query = session.query(CollectedRecord)
            if name:
                query = query.filter(CollectedRecord.name == name)
            if since is not None:
                query = query.filter(CollectedRecord.collected_at >= since)
            rows = (query.order_by(CollectedRecord.collected_at.asc(),
                                   CollectedRecord.id.asc())
                    .limit(max(1, int(limit))).all())
            return [collected_dict(row) for row in rows]

    def collected_count(self, name: Optional[str] = None,
                        since: Optional[datetime] = None) -> int:
        """Сколько записей собрано (с фильтрами) — счётчик для отчёта и тестов."""
        with self.session() as session:
            query = session.query(CollectedRecord)
            if name:
                query = query.filter(CollectedRecord.name == name)
            if since is not None:
                query = query.filter(CollectedRecord.collected_at >= since)
            return int(query.count())

    # --- сводки ---
    def add_summary(self, *, name: str, content: str, period_start: datetime,
                    period_end: datetime, total_records: int,
                    key_metrics: dict[str, Any],
                    task_id: Optional[int] = None) -> dict[str, Any]:
        """Сохраняет регулярную сводку (текст, период, число записей, метрики)."""
        with self.session() as session:
            row = PeriodicSummary(
                name=name, content=content, period_start=period_start,
                period_end=period_end, total_records=int(total_records),
                key_metrics=dict(key_metrics or {}), task_id=task_id,
            )
            session.add(row)
            session.commit()
            return summary_dict(row)

    def summaries(self, name: Optional[str] = None,
                  limit: int = 100) -> List[dict[str, Any]]:
        """Сводки по убыванию времени создания (свежие — первыми)."""
        with self.session() as session:
            query = session.query(PeriodicSummary)
            if name:
                query = query.filter(PeriodicSummary.name == name)
            rows = (query.order_by(PeriodicSummary.id.desc())
                    .limit(max(1, int(limit))).all())
            return [summary_dict(row) for row in rows]

    def summary(self, summary_id: int) -> Optional[dict[str, Any]]:
        """Сводка по id (``None`` — нет такой)."""
        with self.session() as session:
            row = (session.query(PeriodicSummary)
                   .filter(PeriodicSummary.id == int(summary_id)).first())
            return summary_dict(row) if row is not None else None

    # --- уведомления ---
    def add_notification(self, *, kind: str, text: str,
                         task_id: Optional[int] = None,
                         payload: Optional[dict] = None) -> dict[str, Any]:
        """Кладёт уведомление в очередь (непрочитанное)."""
        with self.session() as session:
            row = SchedulerNotification(
                kind=kind, text=text, task_id=task_id,
                payload=dict(payload) if payload is not None else None,
            )
            session.add(row)
            session.commit()
            return notification_dict(row)

    def notifications(self, unread_only: bool = False,
                      limit: int = 100) -> List[dict[str, Any]]:
        """Уведомления по убыванию времени (свежие — первыми)."""
        with self.session() as session:
            query = session.query(SchedulerNotification)
            if unread_only:
                query = query.filter(SchedulerNotification.read_at.is_(None))
            rows = (query.order_by(SchedulerNotification.id.desc())
                    .limit(max(1, int(limit))).all())
            return [notification_dict(row) for row in rows]

    def unread_count(self) -> int:
        """Сколько уведомлений ещё не прочитано (бейдж в интерфейсе)."""
        with self.session() as session:
            return int(
                session.query(SchedulerNotification)
                .filter(SchedulerNotification.read_at.is_(None))
                .count()
            )

    def mark_read(self, notification_id: int, *, read_at: datetime) -> dict[str, Any]:
        """Отмечает уведомление прочитанным (повторная отметка — безопасный no-op)."""
        with self.session() as session:
            row = (session.query(SchedulerNotification)
                   .filter(SchedulerNotification.id == int(notification_id)).first())
            if row is None:
                raise NotificationNotFoundError(
                    f"Уведомление {notification_id} не найдено"
                )
            if row.read_at is None:
                row.read_at = read_at
                session.commit()
            return notification_dict(row)


def _state(value: str) -> ReminderState:
    """Состояние напоминания из строки БД (непонятное значение — ``scheduled``)."""
    try:
        return ReminderState(str(value))
    except ValueError:
        return ReminderState.SCHEDULED
