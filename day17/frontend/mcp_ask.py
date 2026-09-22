"""«Спросить агента»: тот же вопрос, но через агента с шагом MCP (день 17).

Третий блок раздела «🔌 MCP» и главная демонстрация дня: агент сам решает по
ключевым словам реплики, нужен ли вызов инструмента подключённого сервера,
вызывает его и использует данные в ответе (``Agent.apply_mcp_tool``). Здесь
видно и обратную сторону: если по реплике вызов не нужен или правила допуска его
отклонили, в ответе честно написано, почему.

Генерация требует ключа DeepSeek у бэкенда (ответ строит модель), но сам вызов
инструмента от ключа не зависит — поэтому отказ по соединению, неизвестный
инструмент и ошибка инструмента видны и без ключа: они приходят в отчёте ``mcp``.
"""
import json

import streamlit as st

from . import api_client, common

#: Примеры реплик, которые распознаются эвристикой домена (mcp_intent).
EXAMPLE_QUESTIONS = (
    "Найди информацию о пользователе с ID 1",
    "Покажи пост 3",
    "Какие посты у пользователя 2",
)

#: Реплика, по которой вызов не нужен вовсе (для проверки обратного случая).
NO_TOOL_EXAMPLE = "Сколько будет 2+2?"


def render_ask_agent() -> None:
    """Выбор агента, поле запроса и кнопка «🤖 Спросить агента»."""
    agents = st.session_state.get("agents") or []
    if not agents:
        st.info("Агентов пока нет: создайте агента в боковой панели.")
        return
    st.subheader("🤖 Спросить агента")
    st.caption(
        "Агент сам решает по ключевым словам реплики, нужен ли вызов "
        "инструмента подключённого сервера: имя инструмента и аргументы "
        "подбираются доменными правилами, а не моделью, поэтому вызов видно в "
        "ответе (`mcp`). Данные инструмента уходят в системный промпт того же "
        "запроса — модель отвечает по ним, а не по памяти."
    )
    labels = {f"{agent.get('name')} · {agent.get('agent_id')}": agent.get("agent_id")
              for agent in agents}
    active = common.active_agent() or {}
    keys = list(labels)
    default = next(
        (index for index, key in enumerate(keys) if labels[key] == active.get("agent_id")), 0,
    )
    chosen = st.selectbox("Агент", keys, index=default, key="mcp_ask_agent")
    prompt = st.text_input(
        "Запрос агенту", key="mcp_ask_prompt",
        placeholder=EXAMPLE_QUESTIONS[0],
    )
    if st.button("🤖 Спросить агента", type="primary"):
        _ask(labels[chosen], prompt)
    st.caption(
        "Примеры: " + " · ".join(f"«{question}»" for question in EXAMPLE_QUESTIONS)
        + f" · без вызова: «{NO_TOOL_EXAMPLE}». Нужен ключ DEEPSEEK_API_KEY у бэкенда."
    )


def _ask(agent_id: str, prompt: str) -> None:
    """Отправляет вопрос агенту: результат — в состояние, ошибка — сообщением."""
    text = (prompt or "").strip()
    if not text:
        st.info("Пустой запрос не отправлен: введите текст.")
        return
    try:
        with st.spinner("🤖 Агент думает…"):
            record = api_client.api_generate(agent_id, text)
    except api_client.BackendError as exc:
        common.flash("error", f"Запрос не выполнен: {exc.message}")
        st.rerun()
    st.session_state["mcp_last_ask"] = {
        "agent_id": agent_id, "prompt": text, "record": record,
    }
    st.rerun()


def render_ask_result() -> None:
    """Ответ агента и отчёт о шаге MCP (вызванный инструмент и его данные)."""
    ask = st.session_state.get("mcp_last_ask")
    if not ask:
        return
    record = ask.get("record") or {}
    st.subheader("💬 Ответ агента")
    st.caption(f"агент: {ask.get('agent_id')} · запрос: {ask.get('prompt')}")
    if record.get("status") != "ok":
        st.error(f"Генерация завершилась ошибкой: {record.get('error')}")
    else:
        st.markdown(common.esc(record.get("response")), unsafe_allow_html=True)

    report = record.get("mcp")
    if report is None:
        st.info("MCP-шаг не выполнялся (отказ по инвариантам).")
        return
    _render_report(report)


def _render_report(report: dict) -> None:
    """Блок «🔧 MCP-инструмент»: состояние вызова, аргументы, данные и ошибка."""
    st.markdown("**🔧 MCP-инструмент**")
    state = report.get("state", "")
    label = common.MCP_CALL_STATE_LABELS.get(state, state)
    reason = report.get("reason_code")
    parts = [f"**{label}**"]
    if report.get("tool"):
        parts.append(f"`{report['tool']}`")
    if report.get("arguments"):
        parts.append(json.dumps(report["arguments"], ensure_ascii=False))
    if report.get("duration_ms"):
        parts.append(f"{common.fmt_int(report['duration_ms'])} мс")
    if reason:
        parts.append("причина: " + common.MCP_REASON_LABELS.get(reason, reason))
    st.markdown(" · ".join(parts))

    if not report.get("detected"):
        st.caption("По запросу инструмент не потребовался: ключевых слов нет.")
    if report.get("used_in_prompt"):
        st.success(
            "Данные инструмента добавлены в системный промпт этого запроса: "
            f"+{common.fmt_int(report.get('added_tokens'))} токенов."
        )
    if report.get("error"):
        st.error(report["error"])
    result = report.get("result") or {}
    if result.get("structured") is not None:
        st.json(result["structured"])
    elif result.get("text"):
        st.code(result["text"])
    if result.get("is_error") and result.get("text"):
        st.warning(result["text"])
