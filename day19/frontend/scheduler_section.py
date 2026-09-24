"""Раздел «🗓 Планировщик» дня 18: задачи, напоминания, сводки и уведомления.

Один раздел интерфейса на весь день: планировщик живёт в процессе бэкенда, поэтому
Streamlit только показывает и меняет задачи — своих таймеров и соединений у
страницы нет. Отсюда и то, что таблица задач и статус обновляются фрагментом с
``run_every="5s"``: тик происходит в бэкенде, а страница подтягивает его след.

Что здесь есть:

* состояние планировщика (работает ли обслуживание таймеров, сколько задач поставлено);
* таблица задач с действиями: пауза, возобновление, запуск вне расписания, удаление;
* форма создания задачи — поля строятся по аргументам выбранного инструмента
  (``GET /scheduler/tools`` отдаёт типы и границы), поэтому форма не знает
  инструментов «по именам» и не разойдётся с доменом;
* напоминания с фильтром по состоянию;
* регулярные сводки: период, число записей, метрики и полный текст;
* история запусков выбранной задачи (фаза, результат, длительность, ошибка).

Данные тянутся только через ``frontend/scheduler_api.py``: домен живёт на бэкенде,
и раскладывать его правила по интерфейсу нельзя.
"""
from __future__ import annotations

import json

import streamlit as st

from . import api_client, common, scheduler_api

#: Значения по умолчанию для формы создания задачи.
DEFAULT_SOURCE_URL = "https://jsonplaceholder.typicode.com/posts"
DEFAULT_INTERVAL = 10
DEFAULT_DELAY = 30
DEFAULT_SUMMARY_INTERVAL = 20
CRON_EXAMPLE = "*/5 * * * *"

#: Выбор расписания: по инструменту (как задумано доменом) или вручную.
SCHEDULE_CHOICES = ("по инструменту", "interval", "cron")

#: Фильтры таблиц (подпись → значение для API; ``None`` — без фильтра).
TASK_FILTERS = {"Все": None, "Активные": "active", "На паузе": "paused",
                "Выполненные": "completed"}
REMINDER_FILTERS = {"Все": None, "Ждут выдачи": "scheduled", "Выданы": "done"}

#: Сколько символов превью метрик печатать в таблице сводок.
METRICS_PREVIEW = 90


def render_scheduler_section() -> None:
    """Раздел «🗓 Планировщик»: задачи, напоминания, сводки и история запусков."""
    st.title("🗓 Планировщик фоновых задач")
    st.caption(
        "Задачи живут в процессе бэкенда (APScheduler) и хранятся в SQLite, поэтому "
        "переживают перезапуск приложения. Три инструмента дня: напоминание "
        "(разовое), периодический сбор данных из внешнего API и регулярная сводка "
        "по накопленным данным. Те же инструменты вызывает агент по реплике — "
        "раздел «🔌 MCP»."
    )
    tools = (_load(scheduler_api.api_scheduler_tools,
                   "Каталог инструментов недоступен") or {}).get("tools") or []
    _render_tasks()
    st.divider()
    _render_create_form(tools)
    st.divider()
    _render_reminders()
    st.divider()
    _render_summaries()
    st.divider()
    _render_history()


# ---------- задачи ----------
@st.fragment(run_every="5s")
def _render_tasks() -> None:
    """Состояние планировщика и таблица задач с действиями (обновление каждые 5 с)."""
    payload = _load(scheduler_api.api_scheduler_tasks, "Список задач недоступен")
    if payload is None:
        return
    _render_status(payload.get("scheduler") or {})
    tasks = payload.get("tasks") or []
    if not tasks:
        st.info("Задач пока нет. Запланируйте первую — форма ниже.")
        return
    st.dataframe([common.schedule_row(task) for task in tasks],
                 width="stretch", hide_index=True)
    _render_actions(tasks)


def _render_status(status: dict) -> None:
    """Плашка состояния планировщика."""
    if not status:
        return
    state = "работает" if status.get("running") else "остановлен"
    st.caption(
        f"⚙️ Планировщик {state} · часовой пояс {status.get('timezone', '—')} · "
        f"поставлено задач {status.get('pending_jobs', 0)} · сверка с БД каждые "
        f"{status.get('sync_seconds', '—')} с"
    )


def _render_actions(tasks: list[dict]) -> None:
    """Кнопки действий над выбранной задачей."""
    labels = {f"№{task['id']} · {task['name']} · {task['schedule_label']}": task["id"]
              for task in tasks}
    chosen = st.selectbox("Действие над задачей", list(labels), key="sched_action_task")
    task_id = labels[chosen]
    columns = st.columns(4)
    with columns[0]:
        if st.button("⏸ Пауза", key="sched_pause"):
            _act(scheduler_api.api_scheduler_pause, task_id, "Задача на паузе.")
    with columns[1]:
        if st.button("▶ Возобновить", key="sched_resume"):
            _act(scheduler_api.api_scheduler_resume, task_id, "Задача возобновлена.")
    with columns[2]:
        if st.button("▶ Запустить сейчас", key="sched_run"):
            _run_now(task_id)
    with columns[3]:
        if st.button("🗑 Удалить", key="sched_delete"):
            _delete(task_id)


def _run_now(task_id: int) -> None:
    """Внеочередной запуск: тик выполняется сразу, отчёт — в плашке."""
    try:
        run = scheduler_api.api_scheduler_run(task_id)
    except api_client.BackendError as exc:
        common.flash("error", f"Запуск не выполнен: {exc.message}")
    else:
        kind = "success" if run.get("status") == "ok" else "error"
        detail = f" · {run['error']}" if run.get("error") else ""
        common.flash(kind, f"Задача {task_id} запущена: {run.get('phase')} → "
                           f"{run.get('status')} ({run.get('duration_ms')} мс){detail}")
    st.rerun(scope="app")


def _delete(task_id: int) -> None:
    """Удаление задачи (каскадом уходят её запуски)."""
    try:
        scheduler_api.api_scheduler_delete(task_id)
    except api_client.BackendError as exc:
        common.flash("error", f"Удаление не выполнено: {exc.message}")
    else:
        common.flash("success", f"Задача {task_id} удалена.")
    st.rerun(scope="app")


def _act(action, task_id: int, message: str) -> None:
    """Общий путь паузы и возобновления: вызвать, сообщить, перерисовать."""
    try:
        action(task_id)
    except api_client.BackendError as exc:
        common.flash("error", f"{message} Не получилось: {exc.message}")
    else:
        common.flash("success", message)
    st.rerun(scope="app")


# ---------- создание задачи ----------
def _render_create_form(tools: list[dict]) -> None:
    """Форма создания задачи: поля строятся по аргументам выбранного инструмента."""
    if not tools:
        st.info("Каталог инструментов пуст: бэкенд недоступен или не отдал список.")
        return
    with st.expander("➕ Запланировать задачу", expanded=True):
        labels = {spec["name"]: spec["label"] for spec in tools}
        tool_name = st.selectbox("Инструмент", list(labels),
                                 format_func=lambda name: labels[name],
                                 key="sched_tool")
        spec = next(item for item in tools if item["name"] == tool_name)
        st.caption(spec.get("description", ""))
        st.caption("Расписание: " + str(spec.get("schedule_help", "")))
        with st.form(key=f"sched_form_{tool_name}"):
            arguments = {arg["name"]: _arg_widget(tool_name, arg)
                         for arg in spec.get("arguments", [])}
            name = st.text_input("Имя задачи (необязательно)",
                                 key=f"sched_name_{tool_name}")
            run_now = st.checkbox(
                "Выполнить немедленно при регистрации", value=True,
                key=f"sched_now_{tool_name}",
                help="Напоминание сохранится, сбор сделает первый запрос, "
                     "сводка посчитается сразу за прошедший интервал.",
            )
            choice = st.selectbox("Расписание", list(SCHEDULE_CHOICES),
                                  key=f"sched_kind_{tool_name}")
            cron = ""
            if choice == "cron":
                cron = st.text_input("Cron-выражение (пять полей)",
                                     value=CRON_EXAMPLE, key=f"sched_cron_{tool_name}")
            submitted = st.form_submit_button("🗓 Запланировать", type="primary")
        if submitted:
            _create(tool_name, arguments, name, run_now, choice, cron)


def _arg_widget(tool_name: str, arg: dict):
    """Виджет одного аргумента: целые — числом с границами, остальные — текстом."""
    key = f"sched_arg_{tool_name}_{arg['name']}"
    help_text = arg.get("description", "")
    if arg.get("type") == "integer":
        return st.number_input(
            arg["name"], min_value=arg.get("minimum"), max_value=arg.get("maximum"),
            value=_int_default(tool_name, arg["name"]), step=1, key=key,
            help=help_text,
        )
    return st.text_input(arg["name"], value=_text_default(arg["name"]), key=key,
                         help=help_text)


def _int_default(tool_name: str, argument: str) -> int:
    """Значение по умолчанию для целого аргумента (периоды и задержка)."""
    if argument == "delay_seconds":
        return DEFAULT_DELAY
    if tool_name == "generate_summary":
        return DEFAULT_SUMMARY_INTERVAL
    return DEFAULT_INTERVAL


def _text_default(argument: str) -> str:
    """Значение по умолчанию для строкового аргумента."""
    if argument == "source_url":
        return DEFAULT_SOURCE_URL
    if argument == "name":
        return "posts"
    return ""


def _create(tool: str, arguments: dict, name: str, run_now: bool,
            choice: str, cron: str) -> None:
    """Создаёт задачу: собирает переопределение расписания и отправляет запрос."""
    payload: dict = {"tool": tool, "arguments": arguments, "run_now": bool(run_now)}
    if (name or "").strip():
        payload["name"] = name.strip()
    if choice == "interval":
        payload["schedule_type"] = "interval"
        payload["schedule_value"] = {
            "seconds": int(arguments.get("interval_seconds") or DEFAULT_INTERVAL)
        }
    elif choice == "cron":
        payload["schedule_type"] = "cron"
        payload["schedule_value"] = {"cron": (cron or "").strip()}
    try:
        result = scheduler_api.api_scheduler_create(payload)
    except api_client.BackendError as exc:
        common.flash("error", f"Задача не создана: {exc.message}")
    else:
        kind = "warning" if result.get("error") else "success"
        common.flash(kind, result.get("message") or "Задача создана.")
    st.rerun(scope="app")


# ---------- напоминания ----------
def _render_reminders() -> None:
    """Таблица напоминаний с фильтром по состоянию."""
    st.subheader("⏰ Напоминания")
    label = st.segmented_control("Показать", list(REMINDER_FILTERS), default="Все",
                                 key="sched_reminder_filter")
    payload = _load(lambda: scheduler_api.api_scheduler_reminders(
        REMINDER_FILTERS.get(label or "Все")), "Напоминания недоступны")
    if payload is None:
        return
    rows = payload.get("reminders") or []
    if not rows:
        st.caption("Напоминаний нет (или ни одно не подходит под фильтр).")
        return
    st.dataframe(
        [{"текст": item.get("text"), "напомнить": common.fmt_time(item.get("remind_at")),
          "состояние": common.REMINDER_STATE_LABELS.get(item.get("status"),
                                                        item.get("status")),
          "создано": common.fmt_time(item.get("created_at"))} for item in rows],
        width="stretch", hide_index=True,
    )


# ---------- сводки ----------
def _render_summaries() -> None:
    """Таблица сводок, метрики одной строкой и полный текст выбранной."""
    st.subheader("📊 Регулярные сводки")
    payload = _load(scheduler_api.api_scheduler_summaries, "Сводки недоступны")
    if payload is None:
        return
    rows = payload.get("summaries") or []
    if not rows:
        st.caption("Сводок пока нет: их считает инструмент «📊 Регулярная сводка».")
        return
    st.dataframe(
        [{"имя": item.get("name"),
          "период": _period_text(item.get("period_start"), item.get("period_end")),
          "записей": item.get("total_records"),
          "метрики": _metrics_preview(item.get("key_metrics") or {})} for item in rows],
        width="stretch", hide_index=True,
    )
    labels = {f"№{item['id']} · {item['name']} · "
              f"{common.fmt_time(item.get('created_at'))}": item for item in rows}
    chosen = st.selectbox("Сводка", list(labels), key="sched_summary_pick")
    if st.button("📄 Показать текст", key="sched_summary_show"):
        st.session_state["sched_summary_text"] = labels[chosen].get("content") or ""
    text = st.session_state.get("sched_summary_text")
    if text:
        st.text(text)


def _metrics_preview(metrics: dict) -> str:
    """Метрики одной строкой: числовые поля (среднее) и категориальные (уникальные)."""
    parts = []
    for field, data in (metrics.get("numeric") or {}).items():
        parts.append(f"{field}: avg {data.get('avg')}")
    for field, data in (metrics.get("categorical") or {}).items():
        parts.append(f"{field}: уник. {data.get('unique')}")
    text = "; ".join(parts) or "—"
    return text if len(text) <= METRICS_PREVIEW else text[:METRICS_PREVIEW] + "…"


def _period_text(start, end) -> str:
    """Период сводки с секундами: у коротких интервалов минуты не различимы.

    Общий форматтер ``common.fmt_time`` обрезает время до минут (он для диалога), а
    у сводки с интервалом в 30 секунд начало и конец попадают в одну минуту —
    сравнить периоды двух сводок было бы нельзя.
    """
    if not start or not end:
        return "—"
    return f"{str(start)[:19].replace('T', ' ')} — " \
           f"{str(end)[11:19] if str(start)[:10] == str(end)[:10] else str(end)[:19].replace('T', ' ')}"


# ---------- история запусков ----------
def _render_history() -> None:
    """История запусков выбранной задачи: фаза, результат, длительность, ошибка."""
    st.subheader("🧾 Запуски задачи")
    payload = _load(scheduler_api.api_scheduler_tasks, "Список задач недоступен")
    if payload is None:
        return
    tasks = payload.get("tasks") or []
    if not tasks:
        st.caption("Задач нет — истории тоже.")
        return
    labels = {f"№{task['id']} · {task['name']}": task["id"] for task in tasks}
    chosen = st.selectbox("Задача", list(labels), key="sched_history_task")
    history = _load(lambda: scheduler_api.api_scheduler_history(labels[chosen]),
                    "История недоступна")
    if history is None:
        return
    runs = history.get("runs") or []
    if not runs:
        st.caption("Запусков пока не было.")
        return
    st.dataframe(
        [{"фаза": run.get("phase"),
          "результат": common.RUN_STATUS_LABELS.get(run.get("status"), run.get("status")),
          "начало": common.fmt_time(run.get("started_at")),
          "мс": run.get("duration_ms"),
          "детали": _detail_preview(run.get("detail")),
          "ошибка": run.get("error")} for run in runs],
        width="stretch", hide_index=True,
    )


def _detail_preview(detail) -> str:
    """Детали запуска одной строкой (в таблице они иллюстрация, не данные)."""
    if detail is None:
        return "—"
    text = json.dumps(detail, ensure_ascii=False)
    return text if len(text) <= METRICS_PREVIEW else text[:METRICS_PREVIEW] + "…"


# ---------- общее ----------
def _load(call, failure: str) -> dict | None:
    """Запрос к бэкенду; ошибка — плашкой и ``None`` (без падения страницы)."""
    try:
        return call()
    except api_client.BackendError as exc:
        st.warning(f"{failure}: {exc.message}")
        return None
