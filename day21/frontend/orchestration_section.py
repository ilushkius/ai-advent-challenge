"""Раздел «🌐 Оркестрация» дня 20: флот серверов, демо-сценарий, прогресс, история.

Оркестрация живёт в процессе бэкенда: Streamlit её только запускает и показывает.
Прогон идёт в фоновом потоке, поэтому прогресс читается фрагментом с
``run_every="1s"``: страница не держит прогон у себя, а подтягивает его след из
``GET /orchestration/runs/{id}`` — поэтому запуск по реплике из чата виден здесь же,
если его номер попал в состояние сессии.

Что здесь есть:

* таблица ФЛОТА: имя сервера, цель подключения, описание, число инструментов и
  состояние; кнопка обновления кэша (``POST /mcp/servers/refresh``) и таблица
  инструментов выбранного сервера со схемой аргументов;
* кнопка «🚀 Запустить демо-сценарий» — пять шагов по трём серверам одним нажатием
  (тот же сценарий, что у CLI-прогона и теста: он описан в домене);
* форма произвольного запроса: план строит бэкенд (моделью, а без ключа — эвристикой);
* прогресс активного запуска: полоса «сколько шагов пройдено», строки шагов, итог;
* диаграмма флоу (mermaid): узел на шаг с сервером и инструментом, подпись ребра —
  объём данных, который ушёл следующему серверу;
* таблица шагов: индекс, сервер, инструмент, входные аргументы, выходные данные,
  время и статус — ровно то, что требуется от журнала дня;
* история запусков, детали выбранного запуска и удаление;
* статистика: вызовы по серверам, среднее время шага и топ инструментов.

Данные тянутся только через ``frontend/orchestration_api.py``: правила прогона и
маршрутизации живут на бэкенде, и раскладывать их по интерфейсу нельзя.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, orchestration_api, orchestration_steps

#: Подписи статусов прогона, шага и состояний подключения сервера флота.
ORCH_STATUS_LABELS = {
    "running": "⏳ выполняется",
    "completed": "✅ выполнена",
    "stopped": "⏹ остановлена досрочно",
    "failed": "❌ ошибка",
}
SERVER_STATE_LABELS = {
    "connected": "🟢 подключён",
    "connecting": "🟡 подключается",
    "disconnected": "⚪ не подключён",
    "error": "❌ ошибка",
}

#: Периоды опроса: прогресс — раз в секунду (его видно глазами), история — реже.
POLL_RUN_SECONDS = "1s"
POLL_HISTORY_SECONDS = "5s"

#: Сколько шагов у демо-сценария (подпись полосы прогресса для него).
DEMO_STEP_COUNT = 5

#: Ключ состояния сессии, в котором лежит номер показываемого запуска.
RUN_KEY = "orch_run_id"

def render_orchestration_section() -> None:
    """Раздел «🌐 Оркестрация»: флот, запуск, прогресс, флоу, шаги, история, статистика."""
    st.title("🌐 Оркестрация MCP-серверов")
    st.caption(
        "Три независимых MCP-сервера (search_server, data_server, storage_server) "
        "поднимаются по stdio из mcp_servers.json. Реестр держит по соединению на "
        "сервер и маршрутизирует вызов по имени инструмента, а оркестратор строит "
        "план шагов (моделью, а без ключа — эвристикой) и логирует каждый шаг вместе "
        "с сервером в таблицу orchestration_steps."
    )
    _render_fleet()
    st.divider()
    _render_demo()
    st.divider()
    _render_progress()
    st.divider()
    _render_history()


# ---------- флот серверов ----------
def _render_fleet() -> None:
    """Таблица флота, обновление кэша инструментов и инструменты выбранного сервера."""
    st.subheader("🧩 Флот серверов")
    payload = _load(orchestration_api.api_mcp_fleet, "Состав флота недоступен")
    if payload is None:
        return
    servers = payload.get("servers") or []
    if not servers:
        st.warning(
            "Флот пуст: в `mcp_servers.json` нет ни одного сервера. Добавьте запись "
            "с именем, командой запуска и описанием — код менять не нужно."
        )
        return
    st.dataframe(
        [{
            "сервер": item.get("name", ""),
            "цель": item.get("target", ""),
            "описание": item.get("description", ""),
            "инструментов": item.get("tool_count", 0),
            "состояние": SERVER_STATE_LABELS.get(item.get("state"), item.get("state", "")),
            "ошибка": item.get("error") or "—",
        } for item in servers],
        width="stretch", hide_index=True,
    )
    st.caption(
        f"Всего серверов: {payload.get('count', 0)} · подключено: "
        f"{payload.get('connected', 0)} · инструментов в флоте: "
        f"{payload.get('total_tools', 0)}"
    )
    columns = st.columns([1, 2])
    with columns[0]:
        if st.button("🔄 Обновить кэш инструментов", key="orch_refresh"):
            _refresh_cache()
    with columns[1]:
        names = [item.get("name", "") for item in servers]
        chosen = st.selectbox("Инструменты сервера", names, key="orch_fleet_server")
        _render_server_tools(chosen)


def _refresh_cache() -> None:
    """Перечитывает каталоги флота и записывает кэш в файл конфигурации."""
    try:
        payload = orchestration_api.api_mcp_servers_refresh()
    except api_client.BackendError as exc:
        common.flash("error", f"Кэш инструментов не обновлён: {exc.message}")
    else:
        common.flash("success",
                     f"Кэш обновлён: серверов {payload.get('count', 0)}, "
                     f"инструментов {payload.get('total_tools', 0)}")
    st.rerun()


def _render_server_tools(name: str) -> None:
    """Инструменты сервера флота: имя, описание и схема аргументов."""
    payload = _load(lambda: orchestration_api.api_mcp_server_tools(name),
                    f"Инструменты сервера {name} недоступны")
    if payload is None:
        return
    tools = payload.get("tools") or []
    if not tools:
        st.caption("Сервер не отдал каталог инструментов: смотрите колонку «ошибка».")
        return
    if payload.get("cached"):
        st.caption("Каталог из кэша файла: сервер не подключён, показан последний известный.")
    st.dataframe(
        [{
            "инструмент": tool.get("name", ""),
            "описание": tool.get("description", ""),
            "аргументы": ", ".join((tool.get("input_schema") or {}).get("required") or [])
                         or "—",
        } for tool in tools],
        width="stretch", hide_index=True,
    )
    with st.expander("Схема аргументов инструментов сервера"):
        st.json({tool.get("name", ""): tool.get("input_schema") or {} for tool in tools})


# ---------- запуск ----------
def _render_demo() -> None:
    """Кнопка демо-сценария и форма произвольного запроса."""
    st.subheader("🚀 Запуск")
    st.caption(
        "Демо-сценарий: поиск данных на search_server, сводка и ключевые слова на "
        "data_server, файл и строка в базе на storage_server — пять шагов по трём "
        "серверам. Тот же сценарий запускают CLI-прогон и тесты: он описан в домене."
    )
    if st.button("🚀 Запустить демо-сценарий", type="primary",
                 width="stretch", key="orch_demo"):
        _start(orchestration_api.api_orchestration_demo)

    with st.form("orch_form"):
        query = st.text_input(
            "Свой запрос (план построит бэкенд)",
            value="найди данные про RAG и сохрани в базу", key="orch_query",
        )
        submitted = st.form_submit_button("▶ Запустить по запросу")
    if submitted and query.strip():
        _start(lambda: orchestration_api.api_orchestration_run(query.strip()))


def _start(call) -> None:
    """Общий путь запуска: ошибка — плашкой, успех — номером запуска в состоянии."""
    try:
        report = call()
    except api_client.BackendError as exc:
        common.flash("error", f"Оркестрация не запущена: {exc.message}")
    else:
        st.session_state[RUN_KEY] = report.get("run_id")
        common.flash("success",
                     f"Оркестрация запущена (запуск №{report.get('run_id')}, план: "
                     f"{report.get('plan_source') or '—'})")
    st.rerun()


# ---------- прогресс ----------
@st.fragment(run_every=POLL_RUN_SECONDS)
def _render_progress() -> None:
    """Прогресс запуска: полоса шагов, строки шагов, флоу и таблица (раз в секунду)."""
    run_id = st.session_state.get(RUN_KEY)
    if not run_id:
        st.info("Запусков в этой сессии ещё не было. Нажмите «🚀 Запустить "
                "демо-сценарий» или отправьте свой запрос.")
        return
    report = _load(lambda: orchestration_api.api_orchestration_run_report(run_id),
                   "Отчёт о запуске недоступен")
    if report is None:
        return
    run = report.get("run") or {}
    steps = report.get("steps") or []
    status = run.get("status") or ""
    st.subheader(f"Запуск №{run.get('id')} · план {run.get('plan', {}).get('name', '—')}")
    st.markdown(
        f"**{ORCH_STATUS_LABELS.get(status, status)}** · {report.get('message') or ''}"
    )
    st.caption(f"Запрос: {run.get('query') or '—'}")
    planned = DEMO_STEP_COUNT if run.get("plan", {}).get("name") == "demo-scenario" \
        else max(len(steps), 1)
    done = sum(1 for step in steps if step.get("status") != "running")
    st.progress(min(done / planned, 1.0),
                text=f"шагов пройдено: {done} из {planned}")
    for step in steps:
        orchestration_steps.render_step(step)
    if status and status != "running":
        servers = ", ".join(report.get("servers_used") or []) or "—"
        st.caption(
            f"Итог: {report.get('message') or '—'} · серверов задействовано: "
            f"{len(report.get('servers_used') or [])} ({servers}) · длительность "
            f"{run.get('total_duration_ms', 0)} мс"
        )
        if report.get("error"):
            st.error(f"Ошибка шага: {report['error']}")
    orchestration_steps.render_flow(steps)
    orchestration_steps.render_steps_table(steps)


# ---------- история и статистика ----------
@st.fragment(run_every=POLL_HISTORY_SECONDS)
def _render_history() -> None:
    """История запусков, статистика, детали выбранного запуска и удаление."""
    st.subheader("🕓 История запусков")
    payload = _load(orchestration_api.api_orchestration_runs,
                    "История запусков недоступна")
    if payload is None:
        return
    _render_stats(payload.get("stats") or {})
    runs = payload.get("runs") or []
    if not runs:
        st.caption("Запусков пока нет.")
        return
    st.dataframe([_run_row(run) for run in runs], width="stretch",
                 hide_index=True)
    labels = {f"№{run['id']} · {common.fmt_time(run.get('started_at'))} · "
              f"{ORCH_STATUS_LABELS.get(run['status'], run['status'])}": run["id"]
              for run in runs}
    chosen = st.selectbox("Детали запуска", list(labels), key="orch_history_run")
    run_id = labels[chosen]
    report = _load(lambda: orchestration_api.api_orchestration_run_report(run_id),
                   "Отчёт о запуске недоступен")
    if report is not None:
        st.caption(f"Запрос: {report.get('run', {}).get('query') or '—'}")
        for step in report.get("steps") or []:
            orchestration_steps.render_step(step)
    if st.button("🗑 Удалить запуск", key=f"orch_delete_{run_id}"):
        _delete_run(run_id)


def _render_stats(stats: dict) -> None:
    """Статистика журнала: вызовы по серверам, среднее время шага, топ инструментов."""
    if not stats:
        return
    columns = st.columns(3)
    with columns[0]:
        st.metric("запусков", stats.get("runs", 0))
    with columns[1]:
        st.metric("шагов", stats.get("steps", 0))
    with columns[2]:
        st.metric("среднее время шага, мс", stats.get("avg_step_ms", 0))
    servers = stats.get("servers") or []
    tools = stats.get("tools") or []
    if not servers and not tools:
        return
    with st.expander("Статистика по серверам и инструментам"):
        if servers:
            st.dataframe(
                [{"сервер": item.get("server") or "—", "вызовов": item.get("calls", 0),
                  "среднее, мс": item.get("avg_ms", 0)} for item in servers],
                width="stretch", hide_index=True,
            )
        if tools:
            st.dataframe(
                [{"инструмент": item.get("tool"), "сервер": item.get("server"),
                  "вызовов": item.get("calls", 0)} for item in tools],
                width="stretch", hide_index=True,
            )


def _delete_run(run_id: int) -> None:
    """Удаляет запуск вместе с шагами и очищает состояние сессии."""
    try:
        orchestration_api.api_orchestration_delete_run(run_id)
    except api_client.BackendError as exc:
        common.flash("error", f"Запуск не удалён: {exc.message}")
    else:
        if st.session_state.get(RUN_KEY) == run_id:
            st.session_state[RUN_KEY] = None
        common.flash("success", f"Запуск №{run_id} удалён.")
    st.rerun()


def _run_row(run: dict) -> dict:
    """Строка таблицы истории (подписи интерфейса, а не значения API)."""
    return {
        "№": run.get("id"),
        "запрос": orchestration_steps.brief(run.get("query"), 60),
        "статус": ORCH_STATUS_LABELS.get(run.get("status"), run.get("status")),
        "серверы": ", ".join(run.get("servers_used") or []) or "—",
        "шагов": len((run.get("plan") or {}).get("steps") or []),
        "начало": common.fmt_time(run.get("started_at")),
        "длительность, мс": run.get("total_duration_ms"),
    }


# ---------- общее ----------
def _load(call, failure: str) -> dict | None:
    """Запрос к бэкенду; ошибка — плашкой и ``None`` (без падения страницы)."""
    try:
        return call()
    except api_client.BackendError as exc:
        st.warning(f"{failure}: {exc.message}")
        return None


def orchestration_note(report: dict) -> str:
    """Строка «🌐 Оркестрация: …» для сводки хода (``""`` — прогона не было)."""
    if not report or not report.get("detected"):
        return ""
    status = ORCH_STATUS_LABELS.get(report.get("status"),
                                    report.get("status") or "")
    steps = report.get("count") or 0
    servers = len(report.get("servers_used") or [])
    seconds = (report.get("total_duration_ms") or 0) / 1000
    return (f"🌐 Оркестрация: {status} — {steps} шагов, {servers} сервера, "
            f"{seconds:.1f} с")
