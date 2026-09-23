"""Четыре сценария прогона планировщика (день 18) и данные прогона.

Вынесено из ``scripts/scheduler_demo.py`` отдельным модулем: там осталась
оркестрация (жизненный цикл стенда, MCP-клиент, разбор аргументов, отчёт), а
здесь — ЧТО именно проверяется и как результат показывается в консоли. Вместе два
модуля перевалили бы за лимит 400 строк, а деление по вопросу («что проверяем» /
«чем это поднять») читается лучше.

Сценарии:

1. **Напоминание** — ``schedule_reminder`` ставит разовую задачу, через
   ``delay_seconds`` напоминание выдано, уведомление — в очереди;
2. **Периодический сбор** — ``collect_data`` читает источник сразу и дальше по
   расписанию, записи в ``collected_data`` растут;
3. **Регулярная сводка** — ``generate_summary`` считает первую сводку сразу, дальше
   каждые ``interval_seconds``, в метриках видны среднее, минимум и максимум;
4. **Восстановление** — после перезапуска бэкенда задачи на месте со своими
   расписаниями, а сбор продолжает копить записи.

Все сценарии работают против ЖИВОГО стенда (``scripts/scheduler_stand.py``) по
HTTP и вызывают инструменты через свой MCP-сервер по stdio — как это делает агент
в приложении.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

#: Сколько ждать срабатывания фоновой задачи в каждом сценарии (секунды).
REMINDER_DELAY = 30
REMINDER_WAIT = 60.0
COLLECT_INTERVAL = 10
COLLECT_WAIT = 35.0
SUMMARY_INTERVAL = 20
SUMMARY_WAIT = 45.0
RESTART_WAIT = 25.0

#: Задержка перед первым опросом: фон не обязан сработать мгновенно.
POLL_PAUSE = 1.0

#: Команда автотестов дня (секция «Автотесты» отчёта).
TESTS_COMMAND = "uv run pytest -q"


class ApiClient:
    """HTTP-клиент прогона: читает состояние бэкенда так же, как интерфейс."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, **kwargs) -> tuple[int, Any]:
        """Запрос без исключений на HTTP-ошибке: возвращает код и тело."""
        response = requests.request(method, self.base_url + path,
                                    timeout=self.timeout, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return response.status_code, body

    def get(self, path: str, **params) -> Any:
        """GET, который падает на ошибке (состояние обязано быть доступно)."""
        status, body = self.request("GET", path, params=params or None)
        if status >= 400:
            raise RuntimeError(f"GET {path} → HTTP {status}: {body}")
        return body


@dataclass
class DemoRun:
    """Собранные данные прогона: их печатает консоль, из них собирается отчёт."""

    backend_url: str = ""
    source_url: str = ""
    tools: list = field(default_factory=list)
    reminder_call: dict = field(default_factory=dict)
    reminder: dict = field(default_factory=dict)
    reminder_notification: dict = field(default_factory=dict)
    collect_call: dict = field(default_factory=dict)
    collect: dict = field(default_factory=dict)
    summary_call: dict = field(default_factory=dict)
    summary_first: dict = field(default_factory=dict)
    summaries: list = field(default_factory=list)
    restart: dict = field(default_factory=dict)
    pids: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    tests_command: str = TESTS_COMMAND
    tests_summary: str = ""

    def to_dict(self) -> dict:
        """Данные прогона словарём (режим ``--json``)."""
        return asdict(self)


def check(run: DemoRun, scenario: str, what: str, ok: bool, detail: str = "") -> None:
    """Записывает результат одной проверки для таблицы отчёта и печатает его."""
    run.checks.append({"scenario": scenario, "what": what, "ok": bool(ok),
                       "detail": detail})
    mark = "✓" if ok else "✗"
    print(f"  {mark} {what}" + (f" — {detail}" if detail else ""), flush=True)


def call_record(outcome) -> dict:
    """Запись о вызове инструмента для отчёта (успех и отказ одним словарём)."""
    return {
        "tool": outcome.tool,
        "arguments": dict(outcome.arguments),
        "state": outcome.state.value,
        "accepted": outcome.accepted,
        "structured": outcome.result.structured if outcome.result else None,
        "text": outcome.result.text if outcome.result else "",
        "error": outcome.error,
        "duration_ms": outcome.duration_ms,
    }


def wait_until(test, timeout: float, pause: float = POLL_PAUSE) -> bool:
    """Ждёт, пока ``test()`` не вернёт истину (или не выйдет время)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if test():
            return True
        time.sleep(pause)
    return bool(test())


# ---------- сценарий 1: напоминание ----------
def scenario_reminder(run: DemoRun, client: ApiClient, runner) -> None:
    """Разовое напоминание: сохранено сразу, выдано через ``delay_seconds``."""
    print(f"\n=== 1. Напоминание через {REMINDER_DELAY} секунд ===", flush=True)
    outcome = runner.call("schedule_reminder",
                          {"text": "проверить почту", "delay_seconds": REMINDER_DELAY})
    run.reminder_call = call_record(outcome)
    print(f"  вызов: {outcome.state.value}, {outcome.duration_ms} мс")
    if outcome.result and outcome.result.structured:
        print("  ответ инструмента: "
              + json.dumps(outcome.result.structured, ensure_ascii=False)[:220])

    wait_until(lambda: _reminder_status(client) == "done", REMINDER_WAIT)
    reminders = client.get("/scheduler/reminders")["reminders"]
    run.reminder = reminders[0] if reminders else {}
    notifications = client.get("/scheduler/notifications")["notifications"]
    run.reminder_notification = next(
        (item for item in notifications if item["kind"] == "reminder"), {})
    check(run, "1. Напоминание", "напоминание сохранено",
          bool(run.reminder), str(run.reminder.get("text", "")))
    check(run, "1. Напоминание", "напоминание выдано",
          run.reminder.get("status") == "done", str(run.reminder.get("status")))
    check(run, "1. Напоминание", "уведомление в очереди",
          str(run.reminder_notification.get("text", "")).startswith("Напоминание:"),
          str(run.reminder_notification.get("text", "")))


def _reminder_status(client: ApiClient) -> str:
    """Состояние первого напоминания (``""`` — напоминаний пока нет)."""
    reminders = client.get("/scheduler/reminders")["reminders"]
    return reminders[0]["status"] if reminders else ""


# ---------- сценарий 2: периодический сбор ----------
def scenario_collect(run: DemoRun, client: ApiClient, runner, source_url: str) -> None:
    """Периодический сбор: первая запись сразу, дальше по расписанию."""
    print(f"\n=== 2. Сбор данных каждые {COLLECT_INTERVAL} секунд ===", flush=True)
    outcome = runner.call("collect_data", {"source_url": source_url,
                                           "interval_seconds": COLLECT_INTERVAL,
                                           "name": "posts"})
    run.collect_call = call_record(outcome)
    first = client.get("/scheduler/collected", name="posts")
    print(f"  вызов: {outcome.state.value}; первая запись собрана сразу "
          f"(записей: {first['total']})", flush=True)
    check(run, "2. Периодический сбор", "первая запись собрана при регистрации",
          first["total"] >= 1, f"записей: {first['total']}")

    time.sleep(COLLECT_WAIT)
    after = client.get("/scheduler/collected", name="posts")
    records = after["records"]
    run.collect = {
        "total": after["total"],
        "after_wait": after["total"] - first["total"],
        "names": sorted({item["name"] for item in records}),
        "payload_example": records[-1]["payload"] if records else None,
        "collected_at": records[-1]["collected_at"] if records else None,
    }
    print(f"  за {COLLECT_WAIT:.0f} с записей стало {after['total']} "
          f"(+{run.collect['after_wait']})", flush=True)
    check(run, "2. Периодический сбор", "сбор идёт по расписанию",
          run.collect["after_wait"] >= 2, f"+{run.collect['after_wait']} записей")
    check(run, "2. Периодический сбор", "записи под именем сбора",
          run.collect["names"] == ["posts"], str(run.collect["names"]))


# ---------- сценарий 3: регулярная сводка ----------
def scenario_summary(run: DemoRun, client: ApiClient, runner) -> None:
    """Регулярная сводка: первая сразу, дальше по расписанию, с метриками."""
    print(f"\n=== 3. Сводка каждые {SUMMARY_INTERVAL} секунд ===", flush=True)
    outcome = runner.call("generate_summary",
                          {"name": "posts", "interval_seconds": SUMMARY_INTERVAL})
    run.summary_call = call_record(outcome)
    structured = (outcome.result.structured if outcome.result else None) or {}
    run.summary_first = {
        "summary_id": structured.get("summary_id"),
        "total_records": structured.get("total_records"),
        "period_start": structured.get("period_start"),
        "period_end": structured.get("period_end"),
        "summary_text": structured.get("summary_text"),
        "key_metrics": structured.get("key_metrics") or {},
        "message": structured.get("message"),
    }
    print(f"  первая сводка сразу: записей {run.summary_first['total_records']}, "
          f"период {run.summary_first['period_start']} — {run.summary_first['period_end']}")
    check(run, "3. Регулярная сводка", "первая сводка посчитана сразу",
          run.summary_first["summary_id"] is not None,
          f"записей {run.summary_first['total_records']}")

    time.sleep(SUMMARY_WAIT)
    summaries = client.get("/scheduler/summaries", name="posts")["summaries"]
    run.summaries = [
        {key: item[key] for key in ("id", "name", "period_start", "period_end",
                                    "total_records", "key_metrics", "content")}
        for item in summaries
    ]
    latest = run.summaries[0] if run.summaries else {}
    numeric = (latest.get("key_metrics") or {}).get("numeric") or {}
    categorical = (latest.get("key_metrics") or {}).get("categorical") or {}
    print(f"  за {SUMMARY_WAIT:.0f} с сводок стало {len(run.summaries)}; "
          f"числовые поля: {sorted(numeric)}", flush=True)
    if latest.get("content"):
        print("  текст последней сводки:")
        for line in str(latest["content"]).splitlines():
            print(f"    {line}")
    check(run, "3. Регулярная сводка", "сводка повторяется по расписанию",
          len(run.summaries) >= 2, f"сводок: {len(run.summaries)}")
    check(run, "3. Регулярная сводка", "метрики числовых полей заполнены",
          bool(numeric) and {"avg", "min", "max"} <= set(next(iter(numeric.values()))),
          ", ".join(sorted(numeric)))
    check(run, "3. Регулярная сводка", "категориальные поля описаны",
          bool(categorical), ", ".join(sorted(categorical)))


# ---------- сценарий 4: восстановление после перезапуска ----------
def scenario_restart(run: DemoRun, client: ApiClient, stand) -> None:
    """Перезапуск бэкенда: задачи остаются, фон продолжает работу."""
    print("\n=== 4. Восстановление после перезапуска ===", flush=True)
    before_tasks = client.get("/scheduler/tasks")
    before_collected = client.get("/scheduler/collected", name="posts")["total"]
    old_pid = stand.pid
    new_pid = stand.restart(client.request)
    after_tasks = client.get("/scheduler/tasks")
    status = client.get("/scheduler/status")

    print(f"  pid {old_pid} → {new_pid}; задач до: {before_tasks['count']}, "
          f"после: {after_tasks['count']}", flush=True)
    time.sleep(RESTART_WAIT)
    after_collected = client.get("/scheduler/collected", name="posts")["total"]
    run.restart = {
        "old_pid": old_pid,
        "new_pid": new_pid,
        "tasks_before": before_tasks["tasks"],
        "tasks_after": after_tasks["tasks"],
        "collected_before": before_collected,
        "collected_after": after_collected,
        "scheduler": status,
    }
    print(f"  за {RESTART_WAIT:.0f} с после старта записей стало {after_collected} "
          f"(+{after_collected - before_collected})", flush=True)
    check(run, "4. Восстановление", "новый процесс, другая pid",
          new_pid != old_pid, f"{old_pid} → {new_pid}")
    check(run, "4. Восстановление", "задачи восстановлены",
          after_tasks["count"] == before_tasks["count"],
          f"{after_tasks['count']} задач")
    active = [task for task in after_tasks["tasks"] if task["status"] == "active"]
    check(run, "4. Восстановление", "у активных задач есть следующий запуск",
          bool(active) and all(task["next_run_at"] for task in active),
          f"активных: {len(active)}")
    check(run, "4. Восстановление", "сбор продолжился после перезапуска",
          after_collected > before_collected,
          f"+{after_collected - before_collected} записей")


def print_summary(run: DemoRun) -> None:
    """Итог прогона одной строкой на сценарий."""
    print("\n=== Итог ===", flush=True)
    for scenario in ("1. Напоминание", "2. Периодический сбор", "3. Регулярная сводка",
                     "4. Восстановление"):
        checks = [item for item in run.checks if item["scenario"] == scenario]
        passed = sum(1 for item in checks if item["ok"])
        print(f"{scenario}: {passed}/{len(checks)} проверок пройдено")
    failed = [item for item in run.checks if not item["ok"]]
    print(f"всего проверок: {len(run.checks)}; не прошло: {len(failed)}")
    for item in failed:
        print(f"  ✗ {item['scenario']}: {item['what']} — {item['detail']}")
