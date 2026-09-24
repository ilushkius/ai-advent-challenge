"""Значения планировщика фоновых задач (день 18): перечисления и подписи.

Модуль — словарь домена планировщика: типы расписаний, состояния задачи, статус
напоминания, результат запуска и коды причин отказа. Значения строковые: они
попадают в колонки БД (``schedule_type``, ``status``), в ответы API и в подписи
интерфейса без дополнительного маппинга — как в ``mcp_connection_fsm`` дня 16.

Коды ``REASON_*`` — часть контракта API (роутер переводит их в 400/404/409) и
подписи интерфейса, как одноимённые коды в ``mcp_tool_call.py``.
"""

from __future__ import annotations

import enum


class ScheduleType(enum.Enum):
    """Как запускается фоновая задача: разово, с периодом или по cron."""

    DATE = "date"
    INTERVAL = "interval"
    CRON = "cron"

    @property
    def label(self) -> str:
        """Человекочитаемое имя типа расписания (для интерфейса и отчёта)."""
        return SCHEDULE_TYPE_LABELS[self]


class ScheduledTaskState(enum.Enum):
    """Состояние задачи планировщика (колонка ``scheduled_tasks.status``)."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class ReminderState(enum.Enum):
    """Состояние напоминания: ждёт выдачи или уже выдано."""

    SCHEDULED = "scheduled"
    DONE = "done"


class RunStatus(enum.Enum):
    """Результат одного запуска инструмента планировщика."""

    OK = "ok"
    ERROR = "error"


#: Коды причин отказа — контракт API и подписи интерфейса.
REASON_UNKNOWN_TOOL = "unknown_tool"
REASON_BAD_ARGUMENTS = "bad_arguments"
REASON_BAD_SCHEDULE = "bad_schedule"
REASON_BAD_URL = "bad_url"
REASON_NOT_FOUND = "not_found"
REASON_NOT_ACTIVE = "not_active"      # пауза задачи, которая не active
REASON_NOT_PAUSED = "not_paused"      # возобновление задачи, которая не paused

#: Фазы запуска: «подготовка» (немедленное действие инструмента при регистрации)
#: и «tick» (запуск по расписанию). Значения — колонка ``task_runs.phase``.
RUN_PHASE_PREPARE = "prepare"
RUN_PHASE_TICK = "tick"

#: Виды уведомлений планировщика (колонка ``notifications.kind``).
NOTIFICATION_REMINDER = "reminder"
NOTIFICATION_SUMMARY = "summary"
NOTIFICATION_ERROR = "error"

#: Подписи значений для интерфейса и отчёта (frontend держит такие же копии:
#: он не импортирует backend, только HTTP).
SCHEDULE_TYPE_LABELS = {
    ScheduleType.DATE: "разовый (в назначенное время)",
    ScheduleType.INTERVAL: "периодический (каждые N секунд)",
    ScheduleType.CRON: "по cron-расписанию",
}

TASK_STATE_LABELS = {
    ScheduledTaskState.ACTIVE: "▶ активна",
    ScheduledTaskState.PAUSED: "⏸ на паузе",
    ScheduledTaskState.COMPLETED: "✅ выполнена",
}

REMINDER_STATE_LABELS = {
    ReminderState.SCHEDULED: "⏰ ждёт выдачи",
    ReminderState.DONE: "✅ выдано",
}

RUN_STATUS_LABELS = {
    RunStatus.OK: "✅ успешно",
    RunStatus.ERROR: "⚠️ ошибка",
}

REASON_LABELS = {
    REASON_UNKNOWN_TOOL: "инструмент планировщика не знает такого имени",
    REASON_BAD_ARGUMENTS: "аргументы инструмента не подходят",
    REASON_BAD_SCHEDULE: "расписание не разобрано",
    REASON_BAD_URL: "адрес источника не подходит",
    REASON_NOT_FOUND: "задача не найдена",
    REASON_NOT_ACTIVE: "задача не активна",
    REASON_NOT_PAUSED: "задача не на паузе",
}

NOTIFICATION_KIND_LABELS = {
    NOTIFICATION_REMINDER: "⏰ напоминание",
    NOTIFICATION_SUMMARY: "📊 сводка",
    NOTIFICATION_ERROR: "⚠️ ошибка",
}
