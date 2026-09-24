"""Раздел «🔀 Пайплайны» дня 19: запуск, прогресс по шагам и история.

Пайплайн живёт в процессе бэкенда: Streamlit его только запускает и показывает.
Прогон может идти в фоновом потоке, поэтому прогресс читается фрагментом с
``run_every="1s"``: страница не держит прогон у себя, а подтягивает его след из
``GET /pipelines/runs/{id}`` — поэтому запуск, сделанный из чата (репликой про RAG),
виден здесь же, если его номер попал в состояние сессии.

Что здесь есть:

* состояние MCP-подключения: без него шаги не выполнятся (инструменты живут на
  сервере дня), поэтому раздел сразу предлагает подключиться;
* форма запуска: источник, запрос, предел, стиль сводки, имя файла и формат —
  это ровно аргументы запуска (``initial_args``) встроенного пайплайна;
* прогресс активного запуска: полоса «сколько шагов пройдено», строка на шаг
  (инструмент, время, статус) и раскрывающийся отчёт по шагу с входом и выходом;
* схема потока данных: ``search → summarize → save_to_file`` с объёмами на
  переходах (сколько нашлось, сколько пунктов, сколько байт в файле);
* история запусков: таблица, детали шагов выбранного запуска и удаление.

Данные тянутся только через ``frontend/pipeline_api.py``: правила прогона живут на
бэкенде, и раскладывать их по интерфейсу нельзя.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, mcp_api, pipeline_api

#: Цель подключения — СОБСТВЕННЫЙ MCP-сервер дня (осознанная копия
#: ``backend/core/config.MCP_DEFAULT_TARGET``: frontend не импортирует backend).
DEFAULT_TARGET = "uv run python mcp_server/server.py"

#: Выборы формы (подпись → значение аргумента запуска).
SOURCE_OPTIONS = {
    "файл дня: заметки про RAG": "file:mcp_server/data/notes.md",
    "jsonplaceholder: посты": "posts",
    "jsonplaceholder: пользователи": "users",
    "SQLite: шаги прошлых запусков": "sqlite:pipeline_steps",
}
STYLE_OPTIONS = {"Кратко": "short", "Подробно": "detailed", "Пунктами": "bullets"}
FORMAT_OPTIONS = {"Markdown": "md", "Текст": "txt", "JSON": "json"}

#: Подписи статусов прогона, шага и инструментов шага.
PIPELINE_STATUS_LABELS = {
    "running": "⏳ выполняется",
    "completed": "✅ выполнен",
    "stopped": "⏹ остановлен досрочно",
    "failed": "❌ ошибка",
}
STEP_STATUS_LABELS = {"ok": "✅", "failed": "❌", "stopped": "⏹"}
STEP_TOOL_LABELS = {"search": "🔎 search", "summarize": "🧾 summarize",
                    "save_to_file": "💾 save_to_file"}

#: Периоды опроса: прогресс — раз в секунду (его видно глазами), история — реже.
POLL_RUN_SECONDS = "1s"
POLL_HISTORY_SECONDS = "5s"

#: Ключ состояния сессии, в котором лежит номер показываемого запуска.
RUN_KEY = "pipe_run_id"


def render_pipeline_section() -> None:
    """Раздел «🔀 Пайплайны»: подключение, запуск, прогресс, схема и история."""
    st.title("🔀 Пайплайны MCP-инструментов")
    st.caption(
        "Пайплайн — декларативное описание шагов: search ищет данные в источнике, "
        "summarize сводит найденное, save_to_file пишет файл. Данные между шагами "
        "передаются маппингом, а каждый шаг логируется в SQLite (pipeline_steps) с "
        "входными аргументами, результатом и временем выполнения."
    )
    _render_connection()
    st.divider()
    _render_form()
    st.divider()
    _render_active_run()
    st.divider()
    _render_flow()
    st.divider()
    _render_history()


# ---------- подключение ----------
def _render_connection() -> None:
    """Состояние MCP-подключения и кнопка подключения к серверу дня.

    Без соединения пайплайн запустится, но каждый шаг завершится отказом
    ``not_connected``: инструменты живут на MCP-сервере. Поэтому состояние видно
    прямо здесь, а не только в разделе «🔌 MCP».
    """
    payload = _load(mcp_api.api_mcp_status, "Статус MCP недоступен")
    if payload is None:
        return
    connected = bool(payload.get("connected"))
    columns = st.columns([3, 2])
    with columns[0]:
        if connected:
            st.success(
                f"🔌 MCP подключён: {payload.get('target') or '—'} · "
                f"инструментов {payload.get('tool_count', 0)}"
            )
        else:
            st.warning(
                "MCP не подключён — пайплайн не сможет вызвать инструменты: "
                "подключитесь к серверу дня кнопкой справа."
            )
    with columns[1]:
        if not connected and st.button("🔌 Подключиться к серверу дня",
                                       key="pipe_connect"):
            try:
                mcp_api.api_mcp_connect(DEFAULT_TARGET)
            except api_client.BackendError as exc:
                common.flash("error", f"MCP-подключение не установлено: {exc.message}")
            else:
                common.flash("success", f"MCP-подключение установлено: {DEFAULT_TARGET}")
            st.rerun()


# ---------- форма запуска ----------
def _render_form() -> None:
    """Форма запуска: аргументы встроенного пайплайна (сам пайплайн задаёт бэкенд)."""
    with st.form("pipeline_form"):
        columns = st.columns(2)
        with columns[0]:
            source_label = st.selectbox("Источник поиска", list(SOURCE_OPTIONS))
            query = st.text_input("Запрос", value="RAG", key="pipe_query")
            limit = st.slider("Сколько элементов взять", 1, 20, 5, key="pipe_limit")
        with columns[1]:
            style = st.selectbox("Стиль сводки", list(STYLE_OPTIONS))
            filename = st.text_input("Имя файла", value="rag-summary.md",
                                     key="pipe_filename")
            fmt = st.selectbox("Формат файла", list(FORMAT_OPTIONS))
        submitted = st.form_submit_button("▶ Запустить пайплайн", type="primary")
    if not submitted:
        return
    initial_args = {
        "query": query,
        "source": SOURCE_OPTIONS[source_label],
        "limit": int(limit),
        "style": STYLE_OPTIONS[style],
        "max_length": 600,
        "filename": filename,
        "format": FORMAT_OPTIONS[fmt],
    }
    try:
        # Конфигурацию не присылаем: пайплайн по умолчанию описан в домене дня,
        # поэтому интерфейс не держит второй копии декларации.
        report = pipeline_api.api_pipeline_run(None, initial_args, background=True)
    except api_client.BackendError as exc:
        common.flash("error", f"Пайплайн не запущен: {exc.message}")
    else:
        st.session_state[RUN_KEY] = report.get("run_id")
        common.flash("success",
                     f"Пайплайн запущен (запуск №{report.get('run_id')}): "
                     f"{report.get('message') or ''}")
    st.rerun()


# ---------- прогресс ----------
@st.fragment(run_every=POLL_RUN_SECONDS)
def _render_active_run() -> None:
    """Прогресс запуска: полоса шагов, строки шагов и итог (обновление раз в секунду)."""
    run_id = st.session_state.get(RUN_KEY)
    if not run_id:
        st.info("Запусков в этой сессии ещё не было. Запустите пайплайн формой выше.")
        return
    report = _load(lambda: pipeline_api.api_pipeline_run_report(run_id),
                   "Отчёт о запуске недоступен")
    if report is None:
        return
    run = report.get("run") or {}
    steps = report.get("steps") or []
    status = run.get("status") or ""
    st.subheader(f"Запуск №{run.get('id')} · {run.get('pipeline_name') or ''}")
    st.markdown(
        f"**{PIPELINE_STATUS_LABELS.get(status, status)}** · "
        f"{report.get('message') or ''}"
    )
    planned = max(len(steps), 1)
    done = sum(1 for step in steps if step.get("status") != "running")
    st.progress(min(done / planned, 1.0),
                text=f"шагов пройдено: {done} из {planned}")
    for step in steps:
        _render_step(step)
    if status and status != "running":
        st.caption(
            f"Итог: {report.get('message') or '—'} · длительность "
            f"{run.get('total_duration_ms', 0)} мс · файл: "
            f"{_saved_path(steps) or '—'}"
        )
        if report.get("error"):
            st.error(f"Ошибка шага: {report['error']}")


def _render_step(step: dict) -> None:
    """Один шаг прогресса: строка статуса и раскрывающийся отчёт по шагу."""
    tool = step.get("tool_name") or ""
    label = STEP_TOOL_LABELS.get(tool, tool)
    mark = STEP_STATUS_LABELS.get(step.get("status"), "")
    summary = f"{mark} {label} — {step.get('duration_ms', 0)} мс"
    if step.get("error_message"):
        summary += f" · {step['error_message']}"
    with st.expander(f"{summary}", expanded=False):
        st.caption(f"шаг {step.get('step_index')} · статус {step.get('status')}")
        st.markdown("**Входные данные**")
        st.json(step.get("input_args") or {})
        output = step.get("output_result") or {}
        structured = output.get("structured")
        st.markdown("**Выходные данные**")
        if structured:
            st.json(structured)
        elif output.get("text"):
            st.code(output["text"])
        else:
            st.caption(output.get("reason_code") or "результата нет")


def _saved_path(steps: list[dict]) -> str:
    """Путь сохранённого файла из шага ``save_to_file`` (``""`` — файла нет)."""
    for step in steps:
        output = step.get("output_result") or {}
        structured = output.get("structured") or {}
        if structured.get("filepath"):
            return str(structured["filepath"])
    return ""


# ---------- схема потока ----------
def _render_flow() -> None:
    """Схема потока данных: инструменты и объёмы, которые прошли между ними."""
    run_id = st.session_state.get(RUN_KEY)
    report = None
    if run_id:
        report = _load(lambda: pipeline_api.api_pipeline_run_report(run_id),
                       "Схема потока недоступна")
    st.markdown("**Поток данных пайплайна**")
    if not report:
        st.code("search → summarize → save_to_file", language=None)
        st.caption("Запусков ещё не было: объёмы на переходах появятся после первого.")
        return
    steps = report.get("steps") or []
    found = _structured_of(steps, 0)
    summary = _structured_of(steps, 1)
    saved = _structured_of(steps, 2)
    st.markdown(
        "```mermaid\n"
        "graph LR\n"
        f"    S[\"search\"] -->|{found.get('count', 0)} элементов| M[\"summarize\"]\n"
        f"    M -->|{len(summary.get('key_points') or [])} пунктов, "
        f"{len(str(summary.get('summary_text') or ''))} символов| F[\"save_to_file\"]\n"
        f"    F -->|{saved.get('size_bytes', 0)} байт| D[\"файл "
        f"{saved.get('filename', '—')}\"]\n"
        "```"
    )


def _structured_of(steps: list[dict], index: int) -> dict:
    """Структурированный выход шага по номеру (``{}`` — шага или результата нет)."""
    if index >= len(steps):
        return {}
    output = steps[index].get("output_result") or {}
    structured = output.get("structured")
    return structured if isinstance(structured, dict) else {}


# ---------- история ----------
@st.fragment(run_every=POLL_HISTORY_SECONDS)
def _render_history() -> None:
    """История запусков: таблица, детали шагов выбранного запуска и удаление."""
    st.subheader("История запусков")
    payload = _load(pipeline_api.api_pipeline_runs, "История запусков недоступна")
    if payload is None:
        return
    runs = payload.get("runs") or []
    if not runs:
        st.caption("Запусков пока нет.")
        return
    st.dataframe([_run_row(run) for run in runs], width="stretch", hide_index=True)
    labels = {f"№{run['id']} · {run['pipeline_name']} · "
              f"{PIPELINE_STATUS_LABELS.get(run['status'], run['status'])}": run["id"]
              for run in runs}
    chosen = st.selectbox("Детали запуска", list(labels), key="pipe_history_run")
    run_id = labels[chosen]
    report = _load(lambda: pipeline_api.api_pipeline_run_report(run_id),
                   "Отчёт о запуске недоступен")
    if report is None:
        return
    for step in report.get("steps") or []:
        _render_step(step)
    if st.button("🗑 Удалить запуск", key=f"pipe_delete_{run_id}"):
        try:
            pipeline_api.api_pipeline_delete_run(run_id)
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
        "пайплайн": run.get("pipeline_name"),
        "статус": PIPELINE_STATUS_LABELS.get(run.get("status"), run.get("status")),
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


def pipeline_note(report: dict) -> str:
    """Строка «🔀 Пайплайн: …» для сводки хода (``""`` — прогона не было)."""
    if not report or not report.get("detected"):
        return ""
    label = PIPELINE_STATUS_LABELS.get(report.get("status"),
                                       report.get("status") or "")
    message = report.get("message") or ""
    return f"🔀 Пайплайн: {label} — {message}".strip()
