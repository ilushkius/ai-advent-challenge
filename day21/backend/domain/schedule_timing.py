"""Нормализация расписания и арифметика ближайшего запуска (день 18).

Отдельный модуль от ``schedule_spec.py``: там — ЧТО за инструмент и с какими
аргументами, здесь — КОГДА запускать. Оба модуля — про один домен, но вместе они
перевалили за лимит 400 строк скилла ``fastapi-streamlit-day-structure``, а деление
по вопросу читается лучше, чем деление по половине файла.

Три формы расписания:

* ``date`` — разовый запуск в конкретный момент: ``{"run_date": "<ISO-8601>"}``;
* ``interval`` — каждые N секунд: ``{"seconds": N}`` (N в границах дня);
* ``cron`` — выражение из пяти полей: ``{"cron": "*/5 * * * *"}``.

``normalize_schedule`` принимает любое из этих значений (тип можно задать строкой —
так приходит из Pydantic-схемы и из интерфейса), приводит его к форме БД и
отказывает (``ScheduleRejected``) на непонятном расписании. ``next_run_at``
считает ближайший запуск для ``date`` и ``interval``; для ``cron`` возвращает
``None``: ближайший запуск по cron знает только сам планировщик, и его значение
(``job.next_run_time``) записывается в БД в ``TaskScheduler``.

Модуль чистый: ``datetime`` плюс ``schedule_spec``/``scheduler_values``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from ..core import config
from .schedule_spec import (
    SECONDS_FIELD,
    ScheduleRejected,
    ensure_utc,
    iso,
    parse_moment,
)
from .scheduler_values import (
    REASON_BAD_SCHEDULE,
    SCHEDULE_TYPE_LABELS,
    ScheduleType,
)


def schedule_type_of(value: ScheduleType | str) -> ScheduleType:
    """Тип расписания из члена ``Enum`` или строки (иначе ``ScheduleRejected``)."""
    if isinstance(value, ScheduleType):
        return value
    try:
        return ScheduleType(str(value))
    except ValueError:
        raise ScheduleRejected(
            REASON_BAD_SCHEDULE,
            f"Неизвестный тип расписания «{value}»; допустимы: "
            + ", ".join(item.value for item in ScheduleType),
        ) from None


def normalize_schedule(
    schedule_type: ScheduleType | str,
    schedule_value: dict[str, Any] | None,
) -> tuple[ScheduleType, dict[str, Any]]:
    """Нормализует расписание к форме БД (ручное переопределение из API и UI).

    Возвращает пару «тип, каноническое значение»: ``{"run_date"}`` для ``date``,
    ``{"seconds"}`` для ``interval`` (принимается и ``interval_seconds`` —
    имя аргумента инструмента), ``{"cron"}`` для ``cron``.
    """
    kind = schedule_type_of(schedule_type)
    value = dict(schedule_value or {})
    if kind is ScheduleType.INTERVAL:
        seconds = value.get(SECONDS_FIELD, value.get("interval_seconds"))
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise ScheduleRejected(
                REASON_BAD_SCHEDULE,
                f"Расписание interval требует целое поле {SECONDS_FIELD}",
            )
        low, high = config.SCHEDULE_INTERVAL_MIN, config.SCHEDULE_INTERVAL_MAX
        if not low <= seconds <= high:
            raise ScheduleRejected(
                REASON_BAD_SCHEDULE,
                f"Интервал должен быть от {low} до {high} секунд, получено {seconds}",
            )
        return ScheduleType.INTERVAL, {SECONDS_FIELD: seconds}
    if kind is ScheduleType.CRON:
        expression = str(value.get("cron", "")).strip()
        fields = expression.split()
        if len(fields) != 5:
            raise ScheduleRejected(
                REASON_BAD_SCHEDULE,
                "Cron-выражение должно состоять из пяти полей "
                f"(минуты часы день_месяца месяц день_недели), получено полей: {len(fields)}",
            )
        if len(expression) > config.SCHEDULE_VALUE_MAX:
            raise ScheduleRejected(
                REASON_BAD_SCHEDULE,
                f"Cron-выражение длиннее {config.SCHEDULE_VALUE_MAX} символов",
            )
        return ScheduleType.CRON, {"cron": expression}
    moment = parse_moment(value.get("run_date"))
    if moment is None:
        raise ScheduleRejected(
            REASON_BAD_SCHEDULE,
            "Расписание date требует поле run_date в формате ISO-8601 "
            "(например, 2026-09-23T10:15:00+00:00)",
        )
    return ScheduleType.DATE, {"run_date": iso(moment)}


def next_run_at(spec_type: ScheduleType | str, spec_value: dict[str, Any] | None,
                now: Optional[datetime] = None,
                last_run_at: Optional[datetime] = None) -> Optional[datetime]:
    """Момент следующего запуска по расписанию (``None`` — расписание знает APScheduler).

    ``date`` — сам момент запуска; ``interval`` — ``last_run_at + interval``, но не
    раньше ``now`` (пока приложение было выключено, время прошло); ``cron`` —
    ``None``.
    """
    kind = schedule_type_of(spec_type)
    value = dict(spec_value or {})
    moment = ensure_utc(now) or datetime.now(timezone.utc)
    if kind is ScheduleType.DATE:
        return parse_moment(value.get("run_date"))
    if kind is ScheduleType.INTERVAL:
        seconds = int(value.get(SECONDS_FIELD, config.SCHEDULE_INTERVAL_MIN))
        base = ensure_utc(last_run_at) or moment
        candidate = base + timedelta(seconds=seconds)
        return candidate if candidate > moment else moment
    return None


def schedule_label(spec_type: ScheduleType | str,
                   spec_value: dict[str, Any] | None) -> str:
    """Человекочитаемое расписание для таблицы, отчёта и подсказки."""
    kind = schedule_type_of(spec_type)
    value = dict(spec_value or {})
    if kind is ScheduleType.DATE:
        moment = parse_moment(value.get("run_date"))
        if moment is None:
            return SCHEDULE_TYPE_LABELS[kind]
        return "разовый запуск " + moment.strftime("%d.%m %H:%M:%S") + " UTC"
    if kind is ScheduleType.INTERVAL:
        return f"каждые {int(value.get(SECONDS_FIELD, 0))} с"
    return f"cron: {value.get('cron', '')}"
