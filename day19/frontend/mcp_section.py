"""Раздел «🔌 MCP» дня 18: подключение, каталог серверов и вызов инструментов.

Единственная точка входа — ``render_mcp_section()``: аргументов нет, потому что
MCP-подключение у процесса одно (оно не привязано к агенту). Раздел показывает

- поле цели (URL сервера или команда запуска) и селектор транспорта;
- кнопки «🔌 Подключиться» и «⏏ Отключиться»;
- статус подключения: состояние FSM, цель, транспорт, сервер и его протокол,
  допустимые события, текст последней ошибки;
- каталог известных серверов с кнопкой подключения (`mcp_call.render_servers`);
- таблицу инструментов (``name``, ``description``, ``input_schema``,
  ``output_schema``) и кнопку «🔄 Обновить список инструментов»;
- форму ручного вызова инструмента и результат последнего вызова
  (``mcp_call.render_tool_call`` / ``render_call_result``);
- блок «🤖 Спросить агента»: агент сам решает по реплике, нужен ли вызов, и
  использует данные инструмента в ответе (``mcp_ask``);
- подсказку, пока соединения нет.

Свой сервер дня (день 18) публикует ШЕСТЬ инструментов: три читают
jsonplaceholder.typicode.com (``get_user``, ``get_post``, ``list_user_posts``), а
три ставят фоновые задачи через API дня (``schedule_reminder``, ``collect_data``,
``generate_summary``) — их результат виден в разделе «🗓 Планировщик». Поэтому для
сервера дня нужен ещё и запущенный бэкенд, а не только MCP-подключение; чужому
серверу (``uvx mcp-server-fetch``) бэкенд не нужен.

Данные раздела — только HTTP-запросы к бэкенду (``mcp_api.api_mcp_*``):
подключение живёт в процессе бэкенда, поэтому UI его не открывает и не держит.
"""
import json

import streamlit as st

from . import api_client, common, mcp_api, mcp_ask, mcp_call

#: Цель по умолчанию — СОБСТВЕННЫЙ MCP-сервер дня 18: та же строка лежит в
#: ``backend/core/config.MCP_DEFAULT_TARGET``. frontend не импортирует backend,
#: поэтому строка продублирована осознанно.
DEFAULT_TARGET = "uv run python mcp_server/server.py"

#: Примеры целей для подсказки под полем ввода.
TARGET_EXAMPLES = (
    "uv run python mcp_server/server.py — свой сервер дня (stdio, jsonplaceholder)",
    "uvx mcp-server-fetch — fetch-сервер официального набора (stdio, uvx)",
    "npx -y @modelcontextprotocol/server-filesystem . — файловый сервер (stdio, npx)",
    "http://127.0.0.1:9000/mcp — MCP-сервер по Streamable HTTP",
    "sse://127.0.0.1:9000/sse — MCP-сервер по SSE",
)

#: Сколько символов схемы аргументов печатать в таблице (полная — в разборе ниже).
SCHEMA_PREVIEW = 120


def _load_status() -> dict | None:
    """Статус подключения с бэкенда (None — бэкенд недоступен)."""
    try:
        return mcp_api.api_mcp_status()
    except api_client.BackendError as exc:
        st.error(f"Статус MCP не получен: {exc.message}")
        return None


def _load_tools(refresh: bool = False) -> dict | None:
    """Список инструментов с бэкенда (None — запрос не удался; ошибка показана)."""
    try:
        return mcp_api.api_mcp_tools(refresh=refresh)
    except api_client.BackendError as exc:
        st.error(f"Список инструментов не получен: {exc.message}")
        return None


def _load_servers() -> dict | None:
    """Каталог известных серверов с бэкенда (None — запрос не удался)."""
    try:
        return mcp_api.api_mcp_servers()
    except api_client.BackendError as exc:
        st.error(f"Каталог серверов не получен: {exc.message}")
        return None


def _render_status(status: dict) -> None:
    """Плашка состояния подключения и его деталей."""
    state = status.get("state", "disconnected")
    icon = common.MCP_STATE_ICONS.get(state, "⚪")
    label = common.MCP_STATE_LABELS.get(state, state)

    if status.get("connected"):
        server = " ".join(
            part for part in (status.get("server_name"), status.get("server_version")) if part
        ) or "неизвестный сервер"
        st.success(
            f"{icon} **{label}** — {server} · протокол "
            f"{status.get('protocol') or '—'} · инструментов: "
            f"{common.fmt_int(status.get('tool_count', 0))}"
        )
    elif state == "error":
        st.error(f"{icon} **{label}**{': ' + status['error'] if status.get('error') else ''}")
    else:
        st.warning(f"{icon} **{label}**")

    details = {
        "цель": status.get("target") or "—",
        "транспорт": status.get("transport_label") or "—",
        "допустимые события": ", ".join(status.get("allowed_events") or []) or "—",
    }
    st.caption(" · ".join(f"**{key}:** {value}" for key, value in details.items()))
    if status.get("connected") and status.get("error"):
        st.warning(f"Последняя ошибка: {status['error']}")


def _render_tools_table(tools: list) -> None:
    """Таблица инструментов: имя, описание, схема аргументов (кратко)."""
    rows = [{
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "input_schema": _schema_preview(tool.get("input_schema")),
    } for tool in tools]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _schema_preview(schema) -> str:
    """Схема аргументов одной строкой (в таблице — обрезанная, целиком — ниже)."""
    if not schema:
        return "—"
    text = json.dumps(schema, ensure_ascii=False)
    return text if len(text) <= SCHEMA_PREVIEW else text[:SCHEMA_PREVIEW] + "…"


def _render_schema_viewer(tools: list) -> None:
    """Полные схемы выбранного инструмента: аргументы и структура результата."""
    names = [tool.get("name", "") for tool in tools]
    with st.expander("🧾 Полная input_schema инструмента", expanded=False):
        chosen = st.selectbox("Инструмент", names, key="mcp_schema_tool")
        tool = next(item for item in tools if item.get("name") == chosen)
        st.json(tool.get("input_schema") or {})
        st.caption(
            "🧾 Полная output_schema инструмента — по ней сервер объявляет "
            "структуру `structuredContent` (пусто, если сервер её не публикует)."
        )
        st.json(tool.get("output_schema") or {})


def _render_tools(payload: dict) -> None:
    """Таблица инструментов и разбор полных схем аргументов и результата."""
    st.subheader("🧰 Инструменты MCP-сервера")
    st.caption(
        "Каталог инструментов сервера (`tools/list`): имя, описание, JSON Schema "
        "аргументов (`input_schema`) и структуры результата (`output_schema`). "
        "Вызвать инструмент можно вручную — ниже по форме, — а агент делает это "
        "сам по ключевым словам реплики."
    )
    tools = payload.get("tools") or []
    if not tools:
        st.info("Сервер вернул пустой список инструментов.")
        return
    st.caption(f"Инструментов: **{common.fmt_int(payload.get('count', len(tools)))}**")
    _render_tools_table(tools)
    _render_schema_viewer(tools)


def _render_refresh_button() -> None:
    """Кнопка «🔄 Обновить список инструментов»: опрашивает сервер заново.

    Запрос идёт со ``refresh=True`` (клиент на бэкенде перезапрашивает
    ``tools/list``), затем страница перерисовывается и читает уже обновлённый
    кэш — так список приходит с сервера ровно один раз за нажатие.
    """
    if not st.button("🔄 Обновить список инструментов"):
        return
    if _load_tools(refresh=True) is not None:
        common.flash("success", "Список инструментов обновлён.")
    st.rerun()


def _render_connect_form(status: dict) -> None:
    """Форма подключения: цель, транспорт и кнопки «Подключиться»/«Отключиться»."""
    remembered = st.session_state.get("mcp_last_target")
    value = status.get("target") or remembered or DEFAULT_TARGET
    with st.form(key="mcp_connect_form"):
        target = st.text_input(
            "URL или команда запуска MCP-сервера", value=value,
            help="Примеры: " + " | ".join(TARGET_EXAMPLES),
        )
        transport = st.selectbox(
            "Транспорт", list(common.MCP_TRANSPORT_LABELS),
            format_func=lambda key: common.MCP_TRANSPORT_LABELS[key],
            index=0,
            help="auto определяет транспорт по виду цели: http:// → HTTP, "
                 "sse:// → SSE, всё остальное — команда stdio",
        )
        connect = st.form_submit_button("🔌 Подключиться", type="primary")
    if connect:
        _connect(target, transport)

    if not status.get("connected"):
        st.info(
            "Соединение не установлено. Введите цель и нажмите «🔌 Подключиться» — "
            "список инструментов появится ниже. Свой сервер дня: "
            "`uv run python mcp_server/server.py` (stdio); альтернативы — "
            "`uvx mcp-server-fetch` или `http://127.0.0.1:9000/mcp` (HTTP)."
        )
        return
    if st.button("⏏ Отключиться", help="Закрыть соединение и остановить сервер-stdio"):
        _disconnect()


def _connect(target: str, transport: str) -> None:
    """Подключение к серверу: цель пустая — ошибка ввода, остальное — от бэкенда."""
    text = (target or "").strip()
    if not text:
        st.error("Укажите URL MCP-сервера или команду запуска.")
        return
    try:
        with st.spinner("Устанавливаю соединение с MCP-сервером…"):
            mcp_api.api_mcp_connect(text, transport)
    except api_client.BackendError as exc:
        common.flash("error", f"MCP-подключение не установлено: {exc.message}")
    else:
        st.session_state["mcp_last_target"] = text
        common.flash("success", f"MCP-подключение установлено: {text}")
    st.rerun()


def _disconnect() -> None:
    """Закрытие соединения (повторный вызов на бэкенде — безопасный no-op)."""
    try:
        mcp_api.api_mcp_disconnect()
    except api_client.BackendError as exc:
        common.flash("error", f"MCP-отключение не выполнено: {exc.message}")
    else:
        common.flash("info", "MCP-соединение закрыто.")
    st.rerun()


def render_mcp_section() -> None:
    """Раздел «🔌 MCP»: подключение, каталог инструментов и вызов."""
    st.title("🔌 MCP: инструменты сервера и их вызов")
    st.caption(
        "MCP (Model Context Protocol) — способ показать агенту внешние "
        "инструменты: файловую систему, веб-запросы, базы данных. День 18 "
        "подключается к MCP-серверу (stdio, SSE или Streamable HTTP), показывает "
        "его каталог `tools/list`, ВЫЗЫВАЕТ инструменты (`tools/call`) — вручную "
        "по форме и автоматически из реплики агента. Свой сервер дня публикует "
        "шесть инструментов: чтение jsonplaceholder (`get_user`, `get_post`, "
        "`list_user_posts`) и планирование фоновой работы (`schedule_reminder`, "
        "`collect_data`, `generate_summary`) — результат последних виден в разделе "
        "«🗓 Планировщик». Цель сервера дня можно задать точнее: "
        "`uv run python mcp_server/server.py --backend-url http://127.0.0.1:8000`."
    )
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        {"success": st.success, "error": st.error,
         "warning": st.warning}.get(kind, st.info)(message)

    status = _load_status()
    if status is None:
        st.warning("MCP-раздел работает через бэкенд. Запустите его из папки day19/:")
        st.code("uvicorn backend.api.main:app --port 8000", language="bash")
        return
    # Список инструментов читается до отрисовки статуса: иначе число инструментов
    # в статусе отставало бы на один проход (соединение открыто, список ещё нет).
    tools = _load_tools() if status.get("connected") else None
    if tools is not None:
        status = {**status, "tool_count": tools.get("count", status.get("tool_count", 0))}
    _render_status(status)
    _render_connect_form(status)
    servers = _load_servers()
    if servers is not None:
        mcp_call.render_servers(servers)
    if tools is not None:
        _render_tools(tools)
        _render_refresh_button()
        mcp_call.render_tool_call(tools.get("tools") or [])
    mcp_call.render_call_result()
    mcp_ask.render_ask_agent()
    mcp_ask.render_ask_result()
