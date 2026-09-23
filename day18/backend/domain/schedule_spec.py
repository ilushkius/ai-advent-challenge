"""Инструменты планировщика и их аргументы (день 18).

Единственный источник правды о трёх инструментах дня: какие у них аргументы, как
проверяется их значение, какое расписание получается «по инструменту» и в каком
виде расписание лежит в БД (``scheduled_tasks.schedule_type`` /
``schedule_value``).

Почему расписание — данные, а не код. MCP-инструмент и ручное создание задачи
(``POST /scheduler/tasks``) идут одним код-путём: ``validate_arguments`` →
расписание (``schedule_for``) или ручное переопределение
(``schedule_timing.normalize_schedule``) → запись в БД. Планировщик
(``backend/services/scheduler.py``) читает из строки БД ровно то, что положил этот
модуль, и не разбирает аргументы инструмента заново.

Формы расписания и арифметика ближайшего запуска — в ``schedule_timing.py``;
здесь — описания инструментов, проверка аргументов и расписание «по умолчанию».

Отличие от буквы задания, названное осознанно: у разовой задачи (``date``) в БД
лежит абсолютное время (``run_date``), а не задержка (``delay_seconds``). Иначе
после перезапуска приложения напоминание отсчитывалось бы заново и срабатывало бы
каждый раз снова — а задание требует, чтобы задачи переживали перезапуск.

Отказ — это данные: ``ScheduleRejected`` несёт код причины (``REASON_*``) и текст.
Роутер переводит код в HTTP-статус, интерфейс — в подпись.

Модуль чистый: ``dataclasses``/``datetime`` и ``backend.core.config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..core import config
from .scheduler_values import (
    REASON_BAD_ARGUMENTS,
    REASON_BAD_URL,
    REASON_UNKNOWN_TOOL,
    ScheduleType,
)

#: Имена инструментов планировщика — контракт дня (MCP-сервер, UI, БД).
SCHEDULE_REMINDER = "schedule_reminder"
COLLECT_DATA = "collect_data"
GENERATE_SUMMARY = "generate_summary"

#: Поле расписания interval: секунды, которые понимают ``normalize_schedule``,
#: ``next_run_at`` и планировщик.
SECONDS_FIELD = "seconds"


class ScheduleRejected(Exception):
    """Отказ планировщика: код причины (контракт API) и текст для человека.

    Отказ — данные, а не падение: роутер переводит ``reason_code`` в HTTP-статус
    (400 для аргументов и расписания, 404 для отсутствующей задачи, 409 для
    неверного состояния), интерфейс показывает ``message``.
    """

    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ToolArgument:
    """Аргумент инструмента: имя, тип JSON Schema, обязательность и границы."""

    name: str
    type: str
    required: bool
    description: str
    minimum: Optional[int] = None
    maximum: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Запись аргумента для ``GET /scheduler/tools`` и формы интерфейса."""
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
        }
        if self.minimum is not None:
            payload["minimum"] = self.minimum
        if self.maximum is not None:
            payload["maximum"] = self.maximum
        return payload


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Инструмент планировщика: подпись, назначение, аргументы и характер расписания."""

    name: str
    label: str
    description: str
    arguments: tuple[ToolArgument, ...]
    schedule_help: str

    def argument(self, name: str) -> Optional[ToolArgument]:
        """Аргумент по имени (``None`` — такого аргумента у инструмента нет)."""
        for item in self.arguments:
            if item.name == name:
                return item
        return None

    @property
    def required(self) -> tuple[str, ...]:
        """Имена обязательных аргументов."""
        return tuple(item.name for item in self.arguments if item.required)

    def to_dict(self) -> dict[str, Any]:
        """Запись инструмента для API и интерфейса."""
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "schedule_help": self.schedule_help,
            "arguments": [item.to_dict() for item in self.arguments],
        }


#: Границы полей-строк: длину проверяет ``validate_arguments``.
_STRING_LIMITS = {
    "text": config.REMINDER_TEXT_MAX,
    "name": config.SCHEDULE_NAME_MAX,
}

#: Тип значения для сообщения об отказе (имя типа Python → слово для человека).
_VALUE_LABELS = {
    "bool": "логическое значение",
    "int": "целое число",
    "float": "дробное число",
    "str": "строка",
    "list": "список",
    "dict": "объект",
    "NoneType": "пусто",
}

#: Инструменты дня: напоминание разовое, сбор и сводка — периодические.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name=SCHEDULE_REMINDER,
        label="⏰ Напоминание",
        description=(
            "Разовое напоминание: сохраняется в таблицу reminders, а задача через "
            "delay_seconds секунд помечает его выполненным и кладёт уведомление в очередь."
        ),
        arguments=(
            ToolArgument(
                "text", "string", True,
                f"текст напоминания (до {config.REMINDER_TEXT_MAX} символов)",
            ),
            ToolArgument(
                "delay_seconds", "integer", True,
                "через сколько секунд напомнить",
                config.SCHEDULE_INTERVAL_MIN, config.SCHEDULE_INTERVAL_MAX,
            ),
        ),
        schedule_help="разовый запуск через delay_seconds секунд",
    ),
    ToolSpec(
        name=COLLECT_DATA,
        label="📥 Периодический сбор данных",
        description=(
            "Читает JSON по адресу и накапливает ответы в таблице collected_data: "
            "первый запрос выполняется сразу, дальше — каждые interval_seconds."
        ),
        arguments=(
            ToolArgument(
                "source_url", "string", True,
                f"адрес HTTP/HTTPS, откуда читать JSON (до {config.COLLECT_URL_MAX} символов)",
            ),
            ToolArgument(
                "interval_seconds", "integer", True,
                "период сбора в секундах",
                config.SCHEDULE_INTERVAL_MIN, config.SCHEDULE_INTERVAL_MAX,
            ),
            ToolArgument(
                "name", "string", True,
                "имя сбора (по нему записи попадают в collected_data и в сводку)",
            ),
        ),
        schedule_help="первый запрос сразу, дальше каждые interval_seconds секунд",
    ),
    ToolSpec(
        name=GENERATE_SUMMARY,
        label="📊 Регулярная сводка",
        description=(
            "Агрегирует накопленные записи за период в сводку (periodic_summaries): "
            "первая сводка считается сразу за прошедший интервал, дальше — каждые "
            "interval_seconds."
        ),
        arguments=(
            ToolArgument(
                "name", "string", True,
                "имя сводки (по нему отбираются записи collected_data)",
            ),
            ToolArgument(
                "interval_seconds", "integer", True,
                "и период агрегации, и период повтора, в секундах",
                config.SCHEDULE_INTERVAL_MIN, config.SCHEDULE_INTERVAL_MAX,
            ),
        ),
        schedule_help=(
            "первая сводка сразу за прошедший интервал, дальше каждые "
            "interval_seconds секунд"
        ),
    ),
)

#: Имена инструментов в объявленном порядке (каталог, проверки, отчёт).
TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)


def tool_spec(name: str) -> Optional[ToolSpec]:
    """Инструмент по имени (``None`` — такого инструмента планировщик не знает)."""
    wanted = (name or "").strip()
    for spec in TOOL_SPECS:
        if spec.name == wanted:
            return spec
    return None


def require_tool_spec(name: str) -> ToolSpec:
    """Инструмент по имени или ``ScheduleRejected`` с перечнем доступных."""
    spec = tool_spec(name)
    if spec is None:
        raise ScheduleRejected(
            REASON_UNKNOWN_TOOL,
            f"Инструмент «{name}» не входит в планировщик дня. "
            f"Доступны: {', '.join(TOOL_NAMES)}",
        )
    return spec


def tool_specs() -> list[dict[str, Any]]:
    """Каталог инструментов дня для ``GET /scheduler/tools`` и формы интерфейса."""
    return [spec.to_dict() for spec in TOOL_SPECS]


def validate_arguments(tool_name: str, arguments: dict[str, Any] | None) -> None:
    """Проверяет аргументы инструмента по его описанию (``None`` — всё хорошо).

    Порядок проверок — от очевидного к тонкому: незнакомый инструмент → лишний
    аргумент → отсутствующий обязательный → тип и границы значения. Результат не
    возвращается: либо аргументы годны, либо брошено ``ScheduleRejected``.
    """
    spec = require_tool_spec(tool_name)
    args = dict(arguments or {})
    known = {item.name for item in spec.arguments}
    for name in args:
        if name not in known:
            raise ScheduleRejected(
                REASON_BAD_ARGUMENTS,
                f"Инструмент «{spec.name}» не принимает аргумент «{name}». "
                f"Доступны: {', '.join(sorted(known))}",
            )
    for item in spec.arguments:
        if item.name not in args:
            if item.required:
                raise ScheduleRejected(
                    REASON_BAD_ARGUMENTS,
                    f"Не указан обязательный аргумент «{item.name}» инструмента "
                    f"«{spec.name}».",
                )
            continue
        _validate_value(spec, item, args[item.name])


def _validate_value(spec: ToolSpec, item: ToolArgument, value: Any) -> None:
    """Тип и границы одного значения (текст отказа — с ожиданием и фактом)."""
    if item.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ScheduleRejected(
                REASON_BAD_ARGUMENTS,
                f"Аргумент «{item.name}» инструмента «{spec.name}» должен быть "
                f"целым числом, получено {_value_label(value)}",
            )
        low, high = item.minimum, item.maximum
        if low is not None and high is not None and not low <= value <= high:
            raise ScheduleRejected(
                REASON_BAD_ARGUMENTS,
                f"Аргумент «{item.name}» инструмента «{spec.name}» должен быть "
                f"целым числом от {low} до {high}, получено {value}",
            )
        return
    if not isinstance(value, str):
        raise ScheduleRejected(
            REASON_BAD_ARGUMENTS,
            f"Аргумент «{item.name}» инструмента «{spec.name}» должен быть "
            f"строкой, получено {_value_label(value)}",
        )
    text = value.strip()
    if not text:
        raise ScheduleRejected(
            REASON_BAD_URL if item.name == "source_url" else REASON_BAD_ARGUMENTS,
            f"Аргумент «{item.name}» инструмента «{spec.name}» не может быть пустым",
        )
    if item.name == "source_url":
        if not text.startswith(("http://", "https://")):
            raise ScheduleRejected(
                REASON_BAD_URL,
                "Аргумент «source_url» должен быть адресом http:// или https://, "
                f"получено «{_clip(text)}»",
            )
        if len(text) > config.COLLECT_URL_MAX:
            raise ScheduleRejected(
                REASON_BAD_URL,
                f"Аргумент «source_url» длиннее {config.COLLECT_URL_MAX} символов",
            )
        return
    limit = _STRING_LIMITS.get(item.name, config.SCHEDULE_VALUE_MAX)
    if len(text) > limit:
        raise ScheduleRejected(
            REASON_BAD_ARGUMENTS,
            f"Аргумент «{item.name}» инструмента «{spec.name}» длиннее {limit} символов",
        )


def default_task_name(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """Имя задачи по инструменту и его аргументам (пользователь может переопределить)."""
    args = dict(arguments or {})
    if tool_name == SCHEDULE_REMINDER:
        base = f"Напоминание: {args.get('text', '')}"
    elif tool_name == COLLECT_DATA:
        base = f"Сбор: {args.get('name', '')}"
    elif tool_name == GENERATE_SUMMARY:
        base = f"Сводка: {args.get('name', '')}"
    else:
        base = str(tool_name)
    return base.strip()[:config.SCHEDULE_NAME_MAX]


def schedule_for(tool_name: str, arguments: dict[str, Any] | None,
                 now: Optional[datetime] = None) -> tuple[ScheduleType, dict[str, Any]]:
    """Расписание «по инструменту»: разовое у напоминания, периодическое у остальных.

    Напоминание становится задачей типа ``date`` с абсолютным моментом
    ``run_date = now + delay_seconds``: момент считается один раз при регистрации и
    лежит в БД, поэтому перезапуск приложения его не сдвигает.
    """
    require_tool_spec(tool_name)
    args = dict(arguments or {})
    moment = ensure_utc(now) or datetime.now(timezone.utc)
    if tool_name == SCHEDULE_REMINDER:
        delay = int(args.get("delay_seconds", config.SCHEDULE_INTERVAL_MIN))
        return ScheduleType.DATE, {"run_date": iso(moment + timedelta(seconds=delay))}
    seconds = int(args.get("interval_seconds", config.SCHEDULE_INTERVAL_MIN))
    return ScheduleType.INTERVAL, {SECONDS_FIELD: seconds}


def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Приводит метку времени к UTC-aware (naive считаем UTC, как хранилище дня)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_moment(value: Any) -> Optional[datetime]:
    """Разбирает момент времени из ``datetime`` или строки ISO-8601 (``None`` — нет)."""
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def iso(moment: datetime) -> str:
    """Момент строкой ISO-8601 в UTC (форма, которую читает ``parse_moment``)."""
    return ensure_utc(moment).isoformat()


def _value_label(value: Any) -> str:
    """Фактический тип значения для сообщения об отказе."""
    name = type(value).__name__
    return _VALUE_LABELS.get(name, name)


def _clip(text: str, limit: int = 60) -> str:
    """Обрезает длинный текст для сообщения об отказе."""
    return text if len(text) <= limit else text[:limit] + "…"
