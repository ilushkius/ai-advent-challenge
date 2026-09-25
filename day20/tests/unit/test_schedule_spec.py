"""Инструменты планировщика, их аргументы и расписание (день 18).

Проверяется контракт домена: какие инструменты объявлены, какие расписания из них
выводятся, как проверяются аргументы (каждый отказ — со своим КОДОМ причины, потому
что роутер переводит код в HTTP-статус) и какой момент следующего запуска считается
для каждого типа расписания.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.core import config
from backend.domain.schedule_spec import (
    COLLECT_DATA,
    GENERATE_SUMMARY,
    SCHEDULE_REMINDER,
    TOOL_NAMES,
    ScheduleRejected,
    default_task_name,
    schedule_for,
    tool_spec,
    tool_specs,
    validate_arguments,
)
from backend.domain.schedule_timing import (
    next_run_at,
    normalize_schedule,
    schedule_label,
)
from backend.domain.scheduler_values import (
    REASON_BAD_ARGUMENTS,
    REASON_BAD_SCHEDULE,
    REASON_BAD_URL,
    REASON_UNKNOWN_TOOL,
    ScheduleType,
)

NOW = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)


def test_catalog_has_three_tools_with_arguments():
    """Каталог дня — три инструмента, и у каждого объявлены свои аргументы."""
    assert TOOL_NAMES == (SCHEDULE_REMINDER, COLLECT_DATA, GENERATE_SUMMARY)
    specs = {item["name"]: item for item in tool_specs()}
    assert set(specs) == set(TOOL_NAMES)
    assert [arg["name"] for arg in specs[SCHEDULE_REMINDER]["arguments"]] == [
        "text", "delay_seconds"
    ]
    assert [arg["name"] for arg in specs[COLLECT_DATA]["arguments"]] == [
        "source_url", "interval_seconds", "name"
    ]
    assert [arg["name"] for arg in specs[GENERATE_SUMMARY]["arguments"]] == [
        "name", "interval_seconds"
    ]
    interval = specs[COLLECT_DATA]["arguments"][1]
    assert (interval["minimum"], interval["maximum"]) == (
        config.SCHEDULE_INTERVAL_MIN, config.SCHEDULE_INTERVAL_MAX
    )
    assert tool_spec("нет такого") is None
    assert tool_spec(SCHEDULE_REMINDER).required == ("text", "delay_seconds")


def test_schedule_for_reminder_is_one_shot_at_absolute_time():
    """Напоминание — разовая задача с абсолютным моментом (переживает перезапуск)."""
    kind, value = schedule_for(SCHEDULE_REMINDER,
                               {"text": "почта", "delay_seconds": 30}, now=NOW)
    assert kind is ScheduleType.DATE
    assert datetime.fromisoformat(value["run_date"]) == NOW + timedelta(seconds=30)


@pytest.mark.parametrize("tool,seconds", [(COLLECT_DATA, 10), (GENERATE_SUMMARY, 20)])
def test_schedule_for_periodic_tools_is_interval(tool, seconds):
    """Сбор и сводка — периодические задачи с периодом из аргумента."""
    arguments = {"interval_seconds": seconds}
    if tool == COLLECT_DATA:
        arguments.update({"source_url": "https://example.test/posts", "name": "posts"})
    else:
        arguments["name"] = "posts"
    assert schedule_for(tool, arguments, now=NOW) == (
        ScheduleType.INTERVAL, {"seconds": seconds}
    )


def test_schedule_for_unknown_tool_is_rejected():
    """Незнакомый инструмент — отказ с кодом, а не пустое расписание."""
    with pytest.raises(ScheduleRejected) as excinfo:
        schedule_for("нет такого", {}, now=NOW)
    assert excinfo.value.reason_code == REASON_UNKNOWN_TOOL


def test_validate_arguments_accepts_good_collect():
    """Годные аргументы не дают ни исключения, ни ответа: функция только проверяет."""
    validate_arguments(COLLECT_DATA, {
        "source_url": "https://example.test/posts", "interval_seconds": 10, "name": "posts",
    })


@pytest.mark.parametrize("tool,arguments,reason,fragment", [
    ("нет такого", {}, REASON_UNKNOWN_TOOL, "не входит в планировщик"),
    (COLLECT_DATA,
     {"source_url": "https://x.test/p", "interval_seconds": 10, "name": "p", "лишнее": 1},
     REASON_BAD_ARGUMENTS, "не принимает аргумент"),
    (COLLECT_DATA, {"source_url": "https://x.test/p", "interval_seconds": 10},
     REASON_BAD_ARGUMENTS, "Не указан обязательный аргумент «name»"),
    (COLLECT_DATA, {"source_url": "https://x.test/p", "interval_seconds": "10", "name": "p"},
     REASON_BAD_ARGUMENTS, "должен быть целым числом"),
    (COLLECT_DATA, {"source_url": "https://x.test/p", "interval_seconds": True, "name": "p"},
     REASON_BAD_ARGUMENTS, "должен быть целым числом"),
    (COLLECT_DATA, {"source_url": "https://x.test/p", "interval_seconds": 0, "name": "p"},
     REASON_BAD_ARGUMENTS, "от 1 до 86400"),
    (COLLECT_DATA,
     {"source_url": "https://x.test/p", "interval_seconds": 86401, "name": "p"},
     REASON_BAD_ARGUMENTS, "от 1 до 86400"),
    (COLLECT_DATA, {"source_url": "ftp://x.test/p", "interval_seconds": 10, "name": "p"},
     REASON_BAD_URL, "http:// или https://"),
    (COLLECT_DATA, {"source_url": "", "interval_seconds": 10, "name": "p"},
     REASON_BAD_URL, "не может быть пустым"),
    (SCHEDULE_REMINDER, {"text": "x" * (config.REMINDER_TEXT_MAX + 1), "delay_seconds": 10},
     REASON_BAD_ARGUMENTS, "длиннее"),
    (SCHEDULE_REMINDER, {"text": 5, "delay_seconds": 10},
     REASON_BAD_ARGUMENTS, "должен быть строкой"),
])
def test_validate_arguments_rejections(tool, arguments, reason, fragment):
    """Каждый негодный аргумент отклоняется своим кодом причины и понятным текстом."""
    with pytest.raises(ScheduleRejected) as excinfo:
        validate_arguments(tool, arguments)
    assert excinfo.value.reason_code == reason
    assert fragment in str(excinfo.value)


def test_validate_arguments_rejects_long_url():
    """Слишком длинный адрес источника отклоняется отдельным кодом."""
    long_url = "https://example.test/" + "a" * config.COLLECT_URL_MAX
    with pytest.raises(ScheduleRejected) as excinfo:
        validate_arguments(COLLECT_DATA, {
            "source_url": long_url, "interval_seconds": 10, "name": "p",
        })
    assert excinfo.value.reason_code == REASON_BAD_URL
    assert str(config.COLLECT_URL_MAX) in str(excinfo.value)


@pytest.mark.parametrize("kind,value,expected", [
    ("interval", {"seconds": 15}, {"seconds": 15}),
    (ScheduleType.INTERVAL, {"interval_seconds": 15}, {"seconds": 15}),
    ("cron", {"cron": "*/5 * * * *"}, {"cron": "*/5 * * * *"}),
    ("date", {"run_date": "2026-09-23T10:15:00+00:00"},
     {"run_date": "2026-09-23T10:15:00+00:00"}),
    ("date", {"run_date": "2026-09-23T10:15:00"}, {"run_date": "2026-09-23T10:15:00+00:00"}),
])
def test_normalize_schedule_accepts_known_forms(kind, value, expected):
    """Ручное расписание приводится к форме БД (naive-время считается UTC)."""
    normalized_kind, normalized = normalize_schedule(kind, value)
    assert normalized_kind.value == (kind.value if isinstance(kind, ScheduleType) else kind)
    assert normalized == expected


@pytest.mark.parametrize("kind,value,fragment", [
    ("interval", {"seconds": 0}, "от 1 до 86400"),
    ("interval", {"seconds": "10"}, "целое поле seconds"),
    ("interval", {}, "целое поле seconds"),
    ("cron", {"cron": "* * *"}, "пяти полей"),
    ("cron", {"cron": ""}, "пяти полей"),
    ("date", {}, "run_date"),
    ("date", {"run_date": "не дата"}, "run_date"),
    ("ежедневно", {"seconds": 10}, "Неизвестный тип расписания"),
])
def test_normalize_schedule_rejections(kind, value, fragment):
    """Непонятное расписание — отказ с кодом ``bad_schedule``."""
    with pytest.raises(ScheduleRejected) as excinfo:
        normalize_schedule(kind, value)
    assert excinfo.value.reason_code == REASON_BAD_SCHEDULE
    assert fragment in str(excinfo.value)


def test_next_run_at_date_and_interval():
    """``date`` отдаёт свой момент, ``interval`` — прошлый запуск плюс период."""
    assert next_run_at(ScheduleType.DATE, {"run_date": "2026-09-23T10:05:00+00:00"},
                       now=NOW) == datetime(2026, 9, 23, 10, 5, tzinfo=timezone.utc)
    assert next_run_at(ScheduleType.INTERVAL, {"seconds": 10}, now=NOW) == NOW + timedelta(seconds=10)
    assert next_run_at(ScheduleType.INTERVAL, {"seconds": 10}, now=NOW,
                       last_run_at=NOW) == NOW + timedelta(seconds=10)


def test_next_run_at_interval_is_never_in_the_past():
    """Пропущенный период не уводит момент в прошлое: задача «догоняется» сразу."""
    stale = NOW - timedelta(hours=1)
    assert next_run_at(ScheduleType.INTERVAL, {"seconds": 10}, now=NOW,
                       last_run_at=stale) == NOW


def test_next_run_at_cron_is_unknown():
    """Ближайший запуск по cron знает только планировщик — домен отдаёт ``None``."""
    assert next_run_at(ScheduleType.CRON, {"cron": "*/5 * * * *"}, now=NOW) is None


@pytest.mark.parametrize("tool,arguments,expected", [
    (SCHEDULE_REMINDER, {"text": "позвонить клиенту", "delay_seconds": 30},
     "Напоминание: позвонить клиенту"),
    (COLLECT_DATA, {"source_url": "https://x.test/posts", "interval_seconds": 10,
                    "name": "posts"}, "Сбор: posts"),
    (GENERATE_SUMMARY, {"name": "posts", "interval_seconds": 20}, "Сводка: posts"),
])
def test_default_task_name(tool, arguments, expected):
    """Имя задачи по умолчанию собирается из инструмента и его аргументов."""
    assert default_task_name(tool, arguments) == expected


def test_schedule_label_is_human_readable():
    """Подпись расписания говорит, что и когда произойдёт."""
    assert schedule_label(ScheduleType.INTERVAL, {"seconds": 10}) == "каждые 10 с"
    assert "cron" in schedule_label(ScheduleType.CRON, {"cron": "*/5 * * * *"})
    assert "разовый" in schedule_label(ScheduleType.DATE,
                                       {"run_date": "2026-09-23T10:05:00+00:00"})
