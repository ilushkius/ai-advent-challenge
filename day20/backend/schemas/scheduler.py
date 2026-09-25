"""Схемы API дня 18: инструменты планировщика, задачи, их запуски и данные.

Схемы собираются из словарей хранилища методом ``from_row``: поля контракта описаны
один раз (в ``backend/storage/scheduler_rows.py`` и в домене), а не дублируются
здесь, и лишние ключи строки не ломают ответ.

Выходные схемы задачи и запусков намеренно терпимы к неполным данным (у всех полей
есть значения по умолчанию): та же ``ScheduledTaskOut`` описывает и полную запись из
БД, и краткий блок задачи в отчёте генерации (``record["schedule"].task``), который
приходит из ответа MCP-инструмента. Строгая схема заставила бы выдумывать поля,
которых инструмент не присылал.

Входные схемы, наоборот, строгие: ``SchedulerTaskIn`` проверяет тело запроса
(``schedule_type`` — член ``ScheduleType``, поэтому опечатка в типе расписания
получает 422 от Pydantic, а не 400 от домена).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..domain.scheduler_values import ScheduleType


class SchedulerToolArgument(BaseModel):
    """Аргумент инструмента планировщика: имя, тип, обязательность и границы."""

    name: str = Field(..., description="Имя аргумента в вызове инструмента")
    type: str = Field("string", description="Тип значения: string | integer")
    required: bool = Field(False, description="Обязателен ли аргумент")
    description: str = Field("", description="Что аргумент означает")
    minimum: Optional[int] = Field(None, description="Минимум (для целых чисел)")
    maximum: Optional[int] = Field(None, description="Максимум (для целых чисел)")


class SchedulerToolSchema(BaseModel):
    """Инструмент планировщика: подпись, назначение, аргументы и характер расписания."""

    name: str = Field(..., description="Имя инструмента (например, collect_data)")
    label: str = Field("", description="Человекочитаемая подпись для интерфейса")
    description: str = Field("", description="Что делает инструмент")
    schedule_help: str = Field("", description="Какое расписание получается у инструмента")
    arguments: List[SchedulerToolArgument] = Field(
        default_factory=list, description="Аргументы инструмента в объявленном порядке"
    )

    @classmethod
    def from_dict(cls, spec: dict[str, Any]) -> "SchedulerToolSchema":
        """Собирает схему из записи каталога инструментов."""
        return cls(**{key: value for key, value in spec.items() if key in cls.model_fields})


class SchedulerToolsResponse(BaseModel):
    """GET /scheduler/tools — каталог трёх инструментов дня."""

    tools: List[SchedulerToolSchema] = Field(
        default_factory=list, description="Инструменты планировщика"
    )
    count: int = Field(0, description="Сколько инструментов в каталоге")


class SchedulerStatusOut(BaseModel):
    """GET /scheduler/status — состояние фонового планировщика процесса."""

    running: bool = Field(False, description="Идёт ли обслуживание таймеров")
    timezone: str = Field(config.SCHEDULER_TIMEZONE, description="Часовой пояс планировщика")
    pending_jobs: int = Field(0, description="Сколько задач поставлено в APScheduler")
    sync_seconds: int = Field(
        config.SCHEDULER_SYNC_SECONDS,
        description="Как часто сверяются таблица задач и планировщик",
    )


class ScheduledTaskOut(BaseModel):
    """Задача планировщика: расписание, состояние и метки запусков.

    Поля необязательны (со значениями по умолчанию): эта же схема описывает краткий
    блок задачи в ответе генерации, где полного набора полей нет.
    """

    id: int = Field(0, description="Номер задачи")
    name: str = Field("", description="Имя задачи (по умолчанию — по инструменту)")
    tool_name: str = Field("", description="Инструмент: schedule_reminder | collect_data | generate_summary")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Аргументы инструмента (у напоминания — с reminder_id)"
    )
    schedule_type: str = Field("date", description="Тип расписания: date | interval | cron")
    schedule_value: dict[str, Any] = Field(
        default_factory=dict, description="Расписание в форме БД (run_date | seconds | cron)"
    )
    schedule_label: str = Field("", description="Расписание для человека")
    status: str = Field("active", description="Состояние: active | paused | completed")
    last_run_at: Optional[datetime] = Field(None, description="Когда задача запускалась последний раз")
    next_run_at: Optional[datetime] = Field(None, description="Когда запустится в следующий раз")
    created_at: Optional[datetime] = Field(None, description="Когда задача создана")
    allowed_events: List[str] = Field(
        default_factory=list, description="События FSM, допустимые в этом состоянии"
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ScheduledTaskOut":
        """Собирает схему из записи хранилища (лишние ключи игнорируются)."""
        return cls(**{key: value for key, value in row.items() if key in cls.model_fields})


class SchedulerTaskIn(BaseModel):
    """Тело POST /scheduler/tasks — что запланировать и как часто."""

    tool: str = Field(
        ...,
        min_length=1,
        max_length=config.SCHEDULE_TOOL_MAX,
        description="Инструмент планировщика из GET /scheduler/tools",
        examples=["collect_data"],
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Аргументы инструмента (их состав задаёт GET /scheduler/tools)",
        examples=[{"source_url": "https://jsonplaceholder.typicode.com/posts",
                   "interval_seconds": 10, "name": "posts"}],
    )
    name: Optional[str] = Field(
        None, min_length=1, max_length=config.SCHEDULE_NAME_MAX,
        description="Имя задачи (необязательно: по умолчанию собирается из инструмента)",
    )
    run_now: bool = Field(
        True, description="Выполнить немедленное действие инструмента (первый сбор, первая сводка)"
    )
    schedule_type: Optional[ScheduleType] = Field(
        None,
        description=(
            "Переопределение расписания: date | interval | cron. "
            "Без него расписание выводится из инструмента"
        ),
    )
    schedule_value: Optional[dict[str, Any]] = Field(
        None,
        description="Значение расписания: {'run_date': …} | {'seconds': N} | {'cron': '*/5 * * * *'}",
        examples=[{"cron": "*/5 * * * *"}],
    )


class SchedulerRunOut(BaseModel):
    """Один запуск задачи: подготовка при регистрации или тик по расписанию."""

    id: int = Field(0, description="Номер записи журнала")
    task_id: int = Field(0, description="Номер задачи")
    phase: str = Field("", description="Фаза: prepare | tick")
    status: str = Field("", description="Результат: ok | error")
    started_at: Optional[datetime] = Field(None, description="Начало запуска")
    finished_at: Optional[datetime] = Field(None, description="Конец запуска")
    duration_ms: int = Field(0, description="Длительность, мс")
    detail: Optional[Any] = Field(None, description="Что именно сделал инструмент")
    error: Optional[str] = Field(None, description="Текст ошибки запуска")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SchedulerRunOut":
        """Собирает схему из записи журнала."""
        return cls(**{key: value for key, value in row.items() if key in cls.model_fields})


class SchedulerTaskCreateOut(BaseModel):
    """POST /scheduler/tasks — созданная задача, её немедленный результат и подтверждение."""

    task: ScheduledTaskOut = Field(..., description="Созданная задача планировщика")
    result: Optional[Any] = Field(
        None, description="Результат немедленного действия инструмента (если оно выполнено)"
    )
    immediate: bool = Field(True, description="Выполнялось ли немедленное действие")
    message: str = Field("", description="Подтверждение для пользователя и модели")
    error: Optional[str] = Field(
        None, description="Причина, по которой немедленное действие не удалось (задача осталась)"
    )


class SchedulerTasksResponse(BaseModel):
    """GET /scheduler/tasks — задачи планировщика и состояние самого планировщика."""

    tasks: List[ScheduledTaskOut] = Field(default_factory=list, description="Задачи")
    count: int = Field(0, description="Сколько задач в ответе")
    scheduler: Optional[SchedulerStatusOut] = Field(
        None, description="Состояние планировщика процесса"
    )


class SchedulerRunsResponse(BaseModel):
    """GET /scheduler/tasks/{task_id}/history — задача и её запуски."""

    task: ScheduledTaskOut = Field(..., description="Задача")
    runs: List[SchedulerRunOut] = Field(
        default_factory=list, description="Запуски (свежие — первыми)"
    )
    count: int = Field(0, description="Сколько запусков в ответе")


class ReminderOut(BaseModel):
    """Напоминание: текст, момент выдачи и состояние."""

    id: int = Field(0, description="Номер напоминания")
    text: str = Field("", description="Текст напоминания")
    remind_at: Optional[datetime] = Field(None, description="Когда напомнить")
    status: str = Field("scheduled", description="Состояние: scheduled | done")
    created_at: Optional[datetime] = Field(None, description="Когда напоминание создано")
    task_id: Optional[int] = Field(None, description="Номер задачи планировщика (если есть)")
    allowed_events: List[str] = Field(
        default_factory=list, description="События FSM, допустимые в этом состоянии"
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReminderOut":
        """Собирает схему из записи хранилища."""
        return cls(**{key: value for key, value in row.items() if key in cls.model_fields})


class RemindersResponse(BaseModel):
    """GET /scheduler/reminders — напоминания (ближайшие — первыми)."""

    reminders: List[ReminderOut] = Field(default_factory=list, description="Напоминания")
    count: int = Field(0, description="Сколько напоминаний в ответе")


class CollectedRecordOut(BaseModel):
    """Одна запись, собранная инструментом collect_data."""

    id: int = Field(0, description="Номер записи")
    name: str = Field("", description="Имя сбора")
    source_url: str = Field("", description="Адрес источника")
    payload: Optional[Any] = Field(None, description="Ответ источника как есть")
    collected_at: Optional[datetime] = Field(None, description="Когда запись собрана")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "CollectedRecordOut":
        """Собирает схему из записи хранилища."""
        return cls(**{key: value for key, value in row.items() if key in cls.model_fields})


class CollectedResponse(BaseModel):
    """GET /scheduler/collected — накопленные записи сбора."""

    records: List[CollectedRecordOut] = Field(default_factory=list, description="Записи")
    count: int = Field(0, description="Сколько записей в ответе")
    total: int = Field(0, description="Сколько записей всего (с тем же фильтром)")
    name: Optional[str] = Field(None, description="Фильтр по имени сбора")


class PeriodicSummaryOut(BaseModel):
    """Регулярная сводка: текст, период и ключевые метрики."""

    id: int = Field(0, description="Номер сводки")
    name: str = Field("", description="Имя сводки")
    content: str = Field("", description="Текст сводки")
    period_start: Optional[datetime] = Field(None, description="Начало периода")
    period_end: Optional[datetime] = Field(None, description="Конец периода")
    total_records: int = Field(0, description="Сколько записей попало в период")
    key_metrics: dict[str, Any] = Field(
        default_factory=dict, description="Метрики периода (числовые и категориальные поля)"
    )
    task_id: Optional[int] = Field(None, description="Номер задачи планировщика")
    created_at: Optional[datetime] = Field(None, description="Когда сводка создана")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "PeriodicSummaryOut":
        """Собирает схему из записи хранилища."""
        return cls(**{key: value for key, value in row.items() if key in cls.model_fields})


class SummariesResponse(BaseModel):
    """GET /scheduler/summaries — регулярные сводки (свежие — первыми)."""

    summaries: List[PeriodicSummaryOut] = Field(default_factory=list, description="Сводки")
    count: int = Field(0, description="Сколько сводок в ответе")


class NotificationOut(BaseModel):
    """Уведомление планировщика (напоминание сработало, сводка готова, тик упал)."""

    id: int = Field(0, description="Номер уведомления")
    kind: str = Field("", description="Вид: reminder | summary | error")
    text: str = Field("", description="Текст уведомления")
    task_id: Optional[int] = Field(None, description="Номер задачи планировщика")
    payload: Optional[Any] = Field(None, description="Машинные детали (номер сводки и т. п.)")
    created_at: Optional[datetime] = Field(None, description="Когда уведомление создано")
    read_at: Optional[datetime] = Field(None, description="Когда прочитано (None — не прочитано)")
    unread: bool = Field(True, description="Не прочитано ли уведомление")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "NotificationOut":
        """Собирает схему из записи хранилища."""
        return cls(**{key: value for key, value in row.items() if key in cls.model_fields})


class NotificationsResponse(BaseModel):
    """GET /scheduler/notifications — очередь уведомлений планировщика."""

    notifications: List[NotificationOut] = Field(
        default_factory=list, description="Уведомления (свежие — первыми)"
    )
    count: int = Field(0, description="Сколько уведомлений в ответе")
    unread: int = Field(0, description="Сколько уведомлений не прочитано")


class ScheduleReportOut(BaseModel):
    """Поле ``schedule`` ответа генерации: зарегистрирован ли фоновый процесс."""

    registered: bool = Field(..., description="Зарегистрирована ли фоновая задача")
    tool: Optional[str] = Field(None, description="Инструмент планировщика, который сработал")
    task: Optional[ScheduledTaskOut] = Field(None, description="Созданная задача")
    summary: Optional[str] = Field(None, description="Текст сводки, если инструмент её посчитал")
    message: str = Field("", description="Подтверждение для пользователя")
