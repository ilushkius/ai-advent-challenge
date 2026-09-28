"""ORM-таблицы планировщика фоновых задач (день 18).

Шесть таблиц, по одной на вопрос «что происходит с фоном»:

- ``scheduled_tasks`` (ScheduledTask) — ЗАДАЧА ПЛАНИРОВЩИКА: имя, инструмент, его
  аргументы, расписание (``schedule_type``/``schedule_value``), состояние
  (``status``) и метки последнего и следующего запуска. Строка переживает рестарт
  процесса: именно из неё ``TaskScheduler.sync_from_db`` восстанавливает задачи
  APScheduler, поэтому метаданные задачи лежат в БД, а не в памяти;
- ``task_runs`` (SchedulerTaskRun) — ЖУРНАЛ ЗАПУСКОВ: по строке на «подготовку»
  (немедленное действие инструмента при регистрации) и на каждый тик
  (``phase``, ``status``, время, длительность, детали и текст ошибки);
- ``reminders`` (Reminder) — НАПОМИНАНИЯ: текст, момент и состояние; выдаёт их
  тик задачи ``schedule_reminder`` — помечает строку выполненной и кладёт
  уведомление в очередь;
- ``notifications`` (SchedulerNotification) — ОЧЕРЕДЬ УВЕДОМЛЕНИЙ: durable-запись
  того, что показать пользователю (напоминание сработало, сводка готова, тик
  упал). ``read_at`` — прочитано ли уведомление;
- ``collected_data`` (CollectedRecord) — НАКОПЛЕННЫЕ ЗАПИСИ: что вернул источник
  при каждом сборе (имя сбора, адрес, payload, время). Из них считает сводку
  инструмент ``generate_summary``;
- ``periodic_summaries`` (PeriodicSummary) — РЕГУЛЯРНЫЕ СВОДКИ: текст сводки,
  период, число записей и ключевые метрики.

Почему ``periodic_summaries``, а не ``summaries``: имя ``summaries`` в проекте уже
занято конспектами сжатия истории (день 9, ``backend/models/context.py``), и
переименовывать унаследованную таблицу ради нового дня нельзя.

Отличия от буквального списка полей задания (осознанные, перечислены в
``STRUCTURE.md``): у ``reminders`` есть ``task_id`` (связь напоминания с задачей),
у ``periodic_summaries`` — ``total_records``/``key_metrics``/``task_id`` (без них
раздел «Сводки» не покажет метрики), а таблицы ``task_runs`` и ``notifications``
задание не перечисляет, но без них нет истории запусков и очереди уведомлений.

Границы строк — из ``config`` (та же конвенция, что у таблиц памяти и задачи);
удаление задачи уносит её запуски каскадом и отвязывает напоминания, уведомления
и сводки (там FK с ``ondelete="SET NULL"``: история остаётся, ссылка исчезает).
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base

from ..core import config


class ScheduledTask(Base):
    """Задача планировщика (таблица scheduled_tasks, день 18).

    ``schedule_value`` — форма расписания, которую понимает ``TaskScheduler``:
    ``{"run_date": …}`` для разовой задачи, ``{"seconds": N}`` для периодической,
    ``{"cron": "…"}`` для cron. ``arguments`` — аргументы инструмента ровно в том
    виде, в каком их принял ``POST /scheduler/tasks`` (у напоминания сюда же
    дописывается ``reminder_id`` — тик обязан знать, какую строку помечать).
    """

    __tablename__ = "scheduled_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(config.SCHEDULE_NAME_MAX), nullable=False)
    schedule_type = Column(String(16), nullable=False, index=True)
    schedule_value = Column(JSON, nullable=False, default=dict)
    tool_name = Column(String(config.SCHEDULE_TOOL_MAX), nullable=False)
    arguments = Column(JSON, nullable=False, default=dict)
    status = Column(String(16), nullable=False, default="active", index=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    runs = relationship(
        "SchedulerTaskRun",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SchedulerTaskRun(Base):
    """Один запуск задачи планировщика (таблица task_runs).

    Фаз две: ``prepare`` — немедленное действие инструмента в момент регистрации
    задачи (напоминание сохраняется, сбор делает первый запрос, сводка считается
    сразу), ``tick`` — запуск по расписанию. Ошибка запуска не удаляет строку
    задачи: ``status="error"`` и ``error`` объясняют, что случилось, а задача
    продолжает работать (``max_instances=1`` у планировщика не даёт тикам
    накладываться).
    """

    __tablename__ = "task_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        Integer,
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    phase = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Integer, nullable=False, default=0)
    detail = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    task = relationship("ScheduledTask", back_populates="runs")


class Reminder(Base):
    """Напоминание (таблица reminders): что и когда напомнить.

    ``task_id`` связывает напоминание с задачей планировщика, которая его выдаст:
    по нему видно, что именно поставило напоминание, и он же обнуляется, если
    задачу удалили (``ondelete="SET NULL"`` — напоминание остаётся историей).
    """

    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String(config.REMINDER_TEXT_MAX), nullable=False)
    remind_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="scheduled", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    task_id = Column(
        Integer,
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )


class SchedulerNotification(Base):
    """Уведомление планировщика (таблица notifications).

    Очередь durable: уведомление, созданное тиком, видит интерфейс — в том числе
    после перезапуска страницы. ``kind`` — вид (``reminder``, ``summary``,
    ``error``), ``payload`` — машинные детали (номер задачи, номер сводки),
    ``read_at`` — отметка «прочитано».
    """

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(32), nullable=False)
    text = Column(String(config.NOTIFICATION_TEXT_MAX), nullable=False)
    task_id = Column(
        Integer,
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    read_at = Column(DateTime(timezone=True), nullable=True, index=True)


class CollectedRecord(Base):
    """Одна запись, собранная инструментом ``collect_data`` (таблица collected_data).

    ``payload`` — ответ источника как есть (SQLAlchemy сериализует его в JSON),
    ``name`` — имя сбора: по нему сводка выбирает записи за период, а разделы
    интерфейса фильтруют таблицу. ``source_url`` хранится рядом с данными: по нему
    видно, откуда запись пришла, даже если задача давно удалена.
    """

    __tablename__ = "collected_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(config.SCHEDULE_NAME_MAX), nullable=False, index=True)
    source_url = Column(String(config.COLLECT_URL_MAX), nullable=False)
    payload = Column(JSON, nullable=True)
    collected_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True
    )


class PeriodicSummary(Base):
    """Регулярная сводка (таблица periodic_summaries, день 18).

    ``content`` — текст сводки, ``period_start``/``period_end`` — за какой период
    она посчитана, ``total_records`` — сколько записей в него попало,
    ``key_metrics`` — те же метрики структурой (по ним таблица «Сводки» показывает
    числа и уникальные значения без разбора текста).
    """

    __tablename__ = "periodic_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(config.SCHEDULE_NAME_MAX), nullable=False, index=True)
    content = Column(Text, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    total_records = Column(Integer, nullable=False, default=0)
    key_metrics = Column(JSON, nullable=False, default=dict)
    task_id = Column(
        Integer,
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
