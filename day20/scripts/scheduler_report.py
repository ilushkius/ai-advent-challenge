"""Сборка отчёта прогона сценариев планировщика (день 18).

Отчёт собирается из ДАННЫХ прогона (``scripts/scheduler_demo.py``), а не пишется
руками: таблица инструментов строится по домену (``TOOL_SPECS``), схема таблиц — по
ORM-классам (``backend/models/scheduler.py``), а примеры вывода — из фактических
ответов инструментов. Поэтому отчёт не может разойтись с кодом: изменится
расписание или колонка — изменится и документ.

Разделы: проверки прогона, инструменты (обязательная таблица задания), четыре
сценария с фактическими значениями из БД, схема таблиц, автотесты и то, что
осталось за рамками дня.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Скрипт лежит в day20/scripts/, а пакет backend — в корне дня.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.domain.schedule_spec import TOOL_SPECS  # noqa: E402
from backend.models.scheduler import (  # noqa: E402
    CollectedRecord,
    PeriodicSummary,
    Reminder,
    ScheduledTask,
    SchedulerNotification,
    SchedulerTaskRun,
)

#: Заголовок отчёта.
TITLE = "# Планировщик фоновых задач: прогон четырёх сценариев (день 18)"

#: Сколько символов примера печатать в таблицах (полностью — в разделах сценариев).
PREVIEW = 220

#: Что за таблица и зачем она нужна (порядок — порядок в отчёте).
TABLE_PURPOSE = {
    "scheduled_tasks": "Задачи планировщика: имя, инструмент, аргументы, расписание, "
                       "состояние и метки запусков. Источник правды для восстановления "
                       "после перезапуска",
    "task_runs": "Журнал запусков: «подготовка» при регистрации и каждый тик — "
                 "результат, длительность, детали и текст ошибки",
    "reminders": "Напоминания: текст, момент выдачи и состояние (ждёт / выдано)",
    "notifications": "Очередь уведомлений: напоминание сработало, сводка готова, "
                     "тик упал; `read_at` — прочитано ли",
    "collected_data": "Накопленные записи сбора: имя сбора, адрес источника, ответ "
                      "как есть и время",
    "periodic_summaries": "Регулярные сводки: текст, период, число записей и ключевые "
                          "метрики",
}

#: Инструмент → (расписание, что сохраняется, что возвращает инструмент).
TOOL_FACTS = {
    "schedule_reminder": (
        "разовый запуск через `delay_seconds` секунд (`date`)",
        "`reminders` (текст и момент выдачи) + задача в `scheduled_tasks` + "
        "`task_runs`",
        "`ReminderScheduled`: `task_id`, `reminder_id`, `text`, `remind_at`, "
        "`next_run_at`, `message`",
    ),
    "collect_data": (
        "первый запрос сразу, далее каждые `interval_seconds` секунд (`interval`)",
        "`collected_data` (ответ источника как есть) + `task_runs` + уведомления "
        "об ошибках",
        "`CollectionStarted`: `task_id`, `name`, `source_url`, `interval_seconds`, "
        "`records_saved`, `next_run_at`, `message`",
    ),
    "generate_summary": (
        "первая сводка сразу за прошедший интервал, далее каждые `interval_seconds`",
        "`periodic_summaries` (текст, период, метрики) + уведомление о готовности",
        "`SummaryReady`: `task_id`, `summary_id`, `period_start`, `period_end`, "
        "`total_records`, `summary_text`, `key_metrics`, `next_run_at`, `message`",
    ),
}


def write_report(path: Path, run) -> Path:
    """Пишет markdown-отчёт по прогону и возвращает путь к файлу."""
    path = Path(path)
    if not path.is_absolute():
        path = DAY_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(run), encoding="utf-8")
    return path


def _render(run) -> str:
    """Тело отчёта: разделы в объявленном порядке."""
    parts = [
        TITLE,
        "",
        f"Бэкенд прогона: `{run.backend_url}` (отдельный процесс, своя БД, "
        f"офлайн-заглушка модели). Источник данных: `{run.source_url}`. "
        f"Инструменты вызваны через свой MCP-сервер по stdio: "
        f"{', '.join(f'`{name}`' for name in run.tools)}.",
        "",
        _section_checks(run),
        _section_tools(run),
        _section_reminder(run),
        _section_collect(run),
        _section_summary(run),
        _section_restart(run),
        _section_tables(),
        _section_tests(run),
        _section_outside(),
    ]
    return "\n".join(parts).rstrip() + "\n"


def _section_checks(run) -> str:
    """1. Проверки прогона: что проверялось и с каким результатом."""
    rows = [
        [check["scenario"], check["what"],
         "✅ пройдено" if check["ok"] else "❌ не пройдено",
         check.get("detail", "")]
        for check in run.checks
    ]
    failed = sum(1 for check in run.checks if not check["ok"])
    return "\n".join([
        "## 1. Проверки прогона",
        "",
        f"Всего проверок: **{len(run.checks)}**, не пройдено: **{failed}**.",
        "",
        _table(["сценарий", "что проверялось", "результат", "факт"], rows),
        "",
    ])


def _section_tools(run) -> str:
    """2. Инструменты планировщика: расписание, что сохраняется, что возвращает."""
    examples = {
        "schedule_reminder": run.reminder_call,
        "collect_data": run.collect_call,
        "generate_summary": run.summary_call,
    }
    rows = []
    for spec in TOOL_SPECS:
        schedule, stores, returns = TOOL_FACTS[spec.name]
        rows.append([f"`{spec.name}` · {spec.label}", schedule, stores, returns,
                     _example(examples.get(spec.name))])
    return "\n".join([
        "## 2. Инструменты планировщика",
        "",
        "| инструмент | расписание | что сохраняется | что возвращает | пример вывода |",
        "|---|---|---|---|---|",
        *("| " + " | ".join(row) + " |" for row in rows),
        "",
    ])


def _section_reminder(run) -> str:
    """3. Сценарий 1: напоминание — вызов, состояние и уведомление."""
    call = run.reminder_call
    reminder = run.reminder
    notification = run.reminder_notification
    return "\n".join([
        "## 3. Сценарий 1: напоминание",
        "",
        "Инструмент `schedule_reminder` вызван с `text=\"проверить почту\"` и "
        f"`delay_seconds=30`.",
        "",
        f"* состояние вызова: `{call.get('state')}` за {call.get('duration_ms')} мс;",
        f"* напоминание в БД: id={reminder.get('id')}, "
        f"«{reminder.get('text')}», момент выдачи {reminder.get('remind_at')}, "
        f"состояние `{reminder.get('status')}`;",
        f"* уведомление в очереди: «{notification.get('text')}» "
        f"(вид `{notification.get('kind')}`, прочитано: "
        f"{not notification.get('unread', True)}).",
        "",
        "### Ответ инструмента",
        "",
        _code(call.get("structured")),
        "",
    ])


def _section_collect(run) -> str:
    """4. Сценарий 2: периодический сбор — рост числа записей."""
    collect = run.collect
    payload = collect.get("payload_example")
    return "\n".join([
        "## 4. Сценарий 2: периодический сбор данных",
        "",
        "Инструмент `collect_data` вызван с адресом источника и "
        "`interval_seconds=10`: первая запись собрана сразу, дальше — по расписанию.",
        "",
        f"* записей всего: **{collect.get('total')}** "
        f"(+{collect.get('after_wait')} за время ожидания);",
        f"* имена сборов: {', '.join(f'`{name}`' for name in collect.get('names') or [])};",
        f"* последняя запись собрана в {collect.get('collected_at')}.",
        "",
        "### Ответ инструмента при регистрации",
        "",
        _code(run.collect_call.get("structured")),
        "",
        "### Что попало в `collected_data` (последняя запись)",
        "",
        _code(payload),
        "",
    ])


def _section_summary(run) -> str:
    """5. Сценарий 3: регулярная сводка — первая сразу, дальше по расписанию."""
    first = run.summary_first
    latest = run.summaries[0] if run.summaries else {}
    metrics = latest.get("key_metrics") or {}
    numeric = metrics.get("numeric") or {}
    categorical = metrics.get("categorical") or {}
    numeric_rows = [
        [f"`{field}`", str(data.get("count")), str(data.get("avg")),
         str(data.get("min")), str(data.get("max"))]
        for field, data in numeric.items()
    ]
    categorical_rows = [
        [f"`{field}`", str(data.get("unique")),
         ", ".join(f"«{item}»" for item in (data.get("samples") or []))]
        for field, data in categorical.items()
    ]
    return "\n".join([
        "## 5. Сценарий 3: регулярная сводка",
        "",
        "Инструмент `generate_summary` вызван с `name=\"posts\"` и "
        "`interval_seconds=20`: период агрегации равен периоду повтора.",
        "",
        f"* первая сводка: записей **{first.get('total_records')}**, период "
        f"{first.get('period_start')} — {first.get('period_end')};",
        f"* всего сводок после ожидания: **{len(run.summaries)}**;",
        f"* источники в метриках: "
        f"{', '.join(f'`{key}` — {value}' for key, value in (metrics.get('sources') or {}).items()) or '—'}.",
        "",
        "### Числовые поля последней сводки",
        "",
        _table(["поле", "значений", "среднее", "мин", "макс"], numeric_rows),
        "",
        "### Категориальные поля последней сводки",
        "",
        _table(["поле", "уникальных", "примеры"], categorical_rows),
        "",
        "### Текст последней сводки",
        "",
        "```",
        str(latest.get("content") or first.get("summary_text") or "").rstrip(),
        "```",
        "",
    ])


def _section_restart(run) -> str:
    """6. Сценарий 4: восстановление задач после перезапуска процесса."""
    restart = run.restart
    before = restart.get("tasks_before") or []
    after = restart.get("tasks_after") or []
    rows = [
        [
            f"№{item['id']}",
            item["name"],
            item["schedule_label"],
            item["status"],
            item.get("next_run_at") or "—",
        ]
        for item in after
    ]
    return "\n".join([
        "## 6. Сценарий 4: восстановление после перезапуска",
        "",
        f"Бэкенд остановлен и поднят заново на той же БД: pid "
        f"{restart.get('old_pid')} → {restart.get('new_pid')}, планировщик после "
        f"старта: `running={restart.get('scheduler', {}).get('running')}`, "
        f"задач поставлено {restart.get('scheduler', {}).get('pending_jobs')}.",
        "",
        f"* задач до перезапуска: **{len(before)}**, после: **{len(after)}**;",
        f"* записей сбора до: {restart.get('collected_before')}, после ожидания: "
        f"**{restart.get('collected_after')}** — сбор продолжился сам.",
        "",
        "### Задачи после перезапуска",
        "",
        _table(["номер", "имя", "расписание", "состояние", "следующий запуск"], rows),
        "",
        "Расписания посчитаны от последнего запуска: пропущенный запуск не ждёт "
        "целый период, а выполняется сразу при восстановлении.",
        "",
    ])


def _section_tables() -> str:
    """7. Схема таблиц планировщика: колонки берутся из ORM-классов."""
    models = (ScheduledTask, SchedulerTaskRun, Reminder, SchedulerNotification,
              CollectedRecord, PeriodicSummary)
    parts = ["## 7. Схема таблиц планировщика", ""]
    for model in models:
        table = model.__table__
        rows = [
            [column.name, str(column.type), "нет" if column.nullable else "да",
             _default(column)]
            for column in table.columns
        ]
        parts.extend([
            f"### `{table.name}`",
            "",
            TABLE_PURPOSE.get(table.name, ""),
            "",
            _table(["колонка", "тип", "обязательна", "значение по умолчанию"], rows),
            "",
        ])
    parts.extend([
        "Имя `periodic_summaries`, а не `summaries`: имя `summaries` в проекте уже "
        "занято конспектами сжатия истории (день 9), и переименовывать "
        "унаследованную таблицу нельзя.",
        "",
    ])
    return "\n".join(parts)


def _section_tests(run) -> str:
    """8. Автотесты дня."""
    summary = run.tests_summary or "прогон запущен без флага `--tests`"
    return "\n".join([
        "## 8. Автотесты дня",
        "",
        f"```\n{run.tests_command}\n```",
        "",
        f"Итог: {summary}",
        "",
    ])


def _section_outside() -> str:
    """9. Что осталось за рамками дня."""
    return "\n".join([
        "## 9. Что осталось за рамками дня",
        "",
        "* доставка уведомлений вне приложения (почта, мессенджер) — нет: очередь "
        "уведомлений живёт в БД и показывается в интерфейсе;",
        "* cron-расписание доступно только переопределением расписания задачи "
        "(`schedule_type=cron`), из аргументов инструмента оно не выводится;",
        "* сбор читает один адрес за задачу: несколько источников — это несколько "
        "задач `collect_data`;",
        "* сводка агрегирует записи одного имени сбора (`name`) — сводка «по всем "
        "данным» задаётся другим именем;",
        "* хранилище планировщика — SQLite в процессе бэкенда: несколько экземпляров "
        "приложения одновременно не поддерживаются (APScheduler живёт в одном).",
        "",
    ])


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Markdown-таблица; пустой список строк — подпись «нет данных»."""
    if not rows:
        return "_нет данных_"
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _example(record: dict | None) -> str:
    """Пример вывода инструмента одной строкой (для таблицы раздела 2)."""
    if not record or record.get("structured") is None:
        error = (record or {}).get("error") or "вызов не состоялся"
        return f"_{_clip(str(error))}_"
    text = json.dumps(record["structured"], ensure_ascii=False)
    return f"`{_clip(text)}`"


def _code(payload: Any) -> str:
    """Блок JSON с фактическим значением (``—`` — данных нет)."""
    if payload is None:
        return "_нет данных_"
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False,
                                                               indent=2, default=str)
    return f"```json\n{text.strip()}\n```"


def _default(column) -> str:
    """Значение по умолчанию колонки для таблицы схемы."""
    default = getattr(column, "default", None)
    if default is None:
        return "—"
    value = getattr(default, "arg", None)
    if callable(value):  # datetime.utcnow / dict / list
        return getattr(value, "__name__", str(value))
    return str(value)


def _clip(text: str, limit: int = PREVIEW) -> str:
    """Обрезает длинный текст для таблицы."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
