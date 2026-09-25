"""Прямой вызов MCP-инструмента и серверы флота (день 17, обновлено днём 20).

Второй блок раздела «🔌 MCP»: пользователь выбирает инструмент подключённого
сервера, заполняет его аргументы по ``input_schema`` и вызывает — то же, что
делает агент сам, но вручную и с видимым результатом. Здесь же состав ФЛОТА
серверов (``GET /mcp/servers``, день 20) с кнопкой, которая открывает активное
соединение этого раздела с целью выбранного сервера.

Форма аргументов строится по схеме сервера, а не по списку известных полей:
``integer``/``number`` → числовое поле, ``boolean`` → флажок, ``string`` → строка,
остальное (массив, объект) — строка JSON, которую разбирает ``json.loads``.
Обязательные аргументы помечены звёздочкой, их перечень показан подписью.

Отказы (400/409/502) приходят ``BackendError`` и превращаются в сообщение
интерфейса; ошибка самого инструмента приходит результатом (``is_error``) и
показывается предупреждением — так пользователь видит разницу между «не смогли
вызвать» и «инструмент ответил, что не получилось».
"""
import json

import streamlit as st

from . import api_client, common, mcp_api

#: Подпись обязательного аргумента в форме.
REQUIRED_MARK = " *"

#: Пояснение к JSON-полю: какой тип значения ждёт инструмент.
JSON_FIELD_HELP = "Значение в формате JSON (например, [1, 2] или {\"key\": \"value\"})"


def render_servers(payload: dict) -> None:
    """Серверы ФЛОТА дня 20 и кнопка подключения активного соединения к выбранному.

    ``GET /mcp/servers`` теперь отдаёт состав флота из ``mcp_servers.json``: реестр
    уже держит по соединению на каждый сервер, поэтому колонка «подключён» — это
    состояние самого сервера, а не «какой из них выбран пользователем». Кнопка
    здесь остаётся: активное соединение раздела «🔌 MCP» (день 17) по-прежнему одно,
    и она открывает его с целью выбранного сервера — например, чтобы вручную вызвать
    его инструмент формой ниже.
    """
    servers = payload.get("servers") or []
    if not servers:
        st.caption(
            "Флот пуст: в `mcp_servers.json` нет ни одного сервера. Состав флота и "
            "его подключение смотрите в разделе «🌐 Оркестрация»."
        )
        return
    st.subheader("🗂 Серверы флота")
    st.caption(
        f"Зарегистрированные серверы (`mcp_servers.json`): всего "
        f"{payload.get('count', 0)}, подключено {payload.get('connected', 0)}, "
        f"инструментов {payload.get('total_tools', 0)}. Реестр держит соединение с "
        f"каждым сервером; кнопка ниже открывает активное соединение этого раздела."
    )
    st.dataframe(
        [{
            "сервер": item.get("name", ""),
            "цель": item.get("target", ""),
            "описание": item.get("description", ""),
            "подключён": "🟢 да" if item.get("connected") else "—",
            "инструментов": item.get("tool_count", 0),
            "ошибка": item.get("error") or "—",
        } for item in servers],
        width="stretch", hide_index=True,
    )
    targets = {item.get("name", ""): item.get("target", "") for item in servers}
    chosen = st.selectbox("Подключить активное соединение к серверу", list(targets),
                          key="mcp_catalog_server")
    if st.button("🔌 Подключиться к этому серверу"):
        _connect_from_catalog(targets[chosen])


def _connect_from_catalog(target: str) -> None:
    """Подключение к серверу из каталога (ошибки — сообщением, затем перерисовка)."""
    try:
        with st.spinner(f"Подключаюсь к {target}…"):
            mcp_api.api_mcp_connect(target)
    except api_client.BackendError as exc:
        common.flash("error", f"MCP-подключение не установлено: {exc.message}")
    else:
        st.session_state["mcp_last_target"] = target
        common.flash("success", f"MCP-подключение установлено: {target}")
    st.rerun()


def render_tool_call(tools: list) -> None:
    """Форма аргументов выбранного инструмента и кнопка вызова."""
    st.subheader("▶ Вызов инструмента")
    if not tools:
        st.info("Сервер не публикует инструментов — вызывать нечего.")
        return
    st.caption(
        "Ручной вызов `tools/call`: аргументы собираются по `input_schema` "
        "инструмента. Результат — структурированный ответ сервера; если "
        "инструмент сообщил об ошибке, она придёт текстом, а не отказом запроса."
    )
    names = [tool.get("name", "") for tool in tools]
    chosen = st.selectbox("Инструмент", names, key="mcp_call_tool")
    tool = next(item for item in tools if item.get("name") == chosen)
    schema = tool.get("input_schema") or {}
    properties = schema.get("properties") or {}
    required = [name for name in (schema.get("required") or []) if isinstance(name, str)]
    st.caption("обязательные аргументы: " + (", ".join(required) or "нет"))

    with st.form(key=f"mcp_call_form_{chosen}"):
        entered = {
            name: _argument_widget(chosen, name, spec, name in required)
            for name, spec in properties.items()
        }
        submitted = st.form_submit_button("▶ Вызвать инструмент", type="primary")
    if not submitted:
        return
    try:
        arguments = _collect_arguments(properties, entered, required)
    except ValueError as exc:
        st.error(f"Аргументы не собраны: {exc}")
        return
    _call_tool(chosen, arguments)


def _argument_widget(tool_name: str, name: str, spec, required: bool):
    """Виджет одного аргумента по его JSON Schema (значение из ``default``)."""
    spec = spec if isinstance(spec, dict) else {}
    label = name + (REQUIRED_MARK if required else "")
    key = f"mcp_arg_{tool_name}_{name}"
    kind = spec.get("type")
    default = spec.get("default")
    if kind in ("integer", "number"):
        if not isinstance(default, (int, float)) or isinstance(default, bool):
            default = 1 if kind == "integer" else 1.0
        return st.number_input(label, value=default, step=1 if kind == "integer" else 0.1,
                               key=key)
    if kind == "boolean":
        return st.checkbox(label, value=bool(default), key=key)
    if kind is None or kind == "string":
        return st.text_input(label, value="" if default is None else str(default), key=key)
    return st.text_input(
        label, value="" if default is None else json.dumps(default, ensure_ascii=False),
        key=key, help=JSON_FIELD_HELP,
    )


def _collect_arguments(properties: dict, entered: dict, required: list) -> dict:
    """Собирает аргументы из формы: JSON-поля разбираются, пустые необязательные отброшены.

    Незаполненный необязательный аргумент не отправляется вовсе: сервер подставит
    своё значение по умолчанию (у ``list_user_posts`` это ``limit=5``), а ``null``
    в аргументах был бы уже другим значением.
    """
    arguments: dict = {}
    for name, spec in properties.items():
        value = entered.get(name)
        kind = (spec or {}).get("type") if isinstance(spec, dict) else None
        if kind not in ("integer", "number", "boolean", None, "string"):
            text = str(value or "").strip()
            if not text:
                if name in required:
                    raise ValueError(f"аргумент «{name}» обязателен и должен быть корректным JSON")
                continue
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"аргумент «{name}» не разобран как JSON: {exc}") from exc
        elif isinstance(value, str) and not value.strip() and name not in required:
            continue
        arguments[name] = value
    return arguments


def _call_tool(tool_name: str, arguments: dict) -> None:
    """Вызов инструмента: результат в состояние, ошибка запроса — сообщением."""
    try:
        with st.spinner(f"Вызываю {tool_name}…"):
            payload = mcp_api.api_mcp_call(tool_name, arguments)
    except api_client.BackendError as exc:
        common.flash("error", f"Вызов не выполнен: {exc.message}")
        st.rerun()
    st.session_state["mcp_last_call"] = payload
    st.rerun()


def render_call_result() -> None:
    """Результат последнего вызова: состояние, длительность и данные."""
    payload = st.session_state.get("mcp_last_call")
    if not payload:
        return
    st.subheader("🧾 Результат вызова")
    state = payload.get("state", "")
    label = common.MCP_CALL_STATE_LABELS.get(state, state)
    reason = payload.get("reason_code")
    parts = [
        f"**{label}**",
        f"{common.fmt_int(payload.get('duration_ms'))} мс",
        f"`{payload.get('tool') or '—'}`",
        json.dumps(payload.get("arguments") or {}, ensure_ascii=False),
    ]
    if reason:
        parts.append("причина: " + common.MCP_REASON_LABELS.get(reason, reason))
    st.markdown(" · ".join(parts))
    if payload.get("error"):
        st.error(payload["error"])
    result = payload.get("result") or {}
    structured = result.get("structured")
    if structured is not None:
        st.json(structured)
    elif result.get("text"):
        st.code(result["text"])
    if result.get("is_error") and result.get("text"):
        st.warning(result["text"])
