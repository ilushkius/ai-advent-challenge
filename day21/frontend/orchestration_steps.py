"""Шаг прогона оркестрации в интерфейсе: строка, диаграмма флоу и таблица (день 20).

Здесь всё, что рисует ОДИН шаг запуска и связи между шагами: раскрывающийся отчёт по
шагу, диаграмма ``mermaid`` (узел на шаг, подпись ребра — объём данных, ушедший
следующему серверу) и таблица шагов с колонками требования дня: индекс, сервер,
инструмент, входные данные, выходные данные, время выполнения и статус.

Вынесено из ``orchestration_section.py``, потому что тот подошёл к лимиту 400 строк,
а шаг нужен и разделу прогресса, и истории: без общего модуля пришлось бы держать
две копии отрисовки, и таблица с диаграммой разошлись бы на первой правке.
"""
from __future__ import annotations

import streamlit as st

#: Подписи статусов шага и колонки таблицы шагов — требование дня, дословно.
STEP_STATUS_LABELS = {"ok": "✅", "failed": "❌", "stopped": "⏹"}
STEP_COLUMNS = ("шаг", "сервер", "инструмент", "входные данные",
                "выходные данные", "время", "статус")


def render_step(step: dict) -> None:
    """Один шаг прогресса: сервер, инструмент, время и раскрытый вход/выход."""
    server = step.get("server_name") or "—"
    tool = step.get("tool_name") or ""
    mark = STEP_STATUS_LABELS.get(step.get("status"), "")
    summary = (f"{mark} {step.get('step_index')}. {server} · {tool} — "
               f"{step.get('duration_ms', 0)} мс")
    if step.get("error_message"):
        summary += f" · {step['error_message']}"
    with st.expander(summary, expanded=False):
        st.caption(f"статус: {step.get('status')} · сервер: {server}")
        st.markdown("**Входные аргументы**")
        st.json(step.get("input_args") or {})
        output = step.get("output_result") or {}
        st.markdown("**Выходные данные**")
        structured = output.get("structured")
        if structured:
            st.json(structured)
        elif output.get("text"):
            st.code(output["text"])
        else:
            st.caption(output.get("reason_code") or "результата нет")


def render_flow(steps: list[dict]) -> None:
    """Схема флоу: диаграмма mermaid плюс текстовая цепочка серверов и объёмов.

    Диаграмма рисуется ``st.mermaid_chart`` (отдельный элемент Streamlit — без
    разбора markdown-блоков), а под ней идёт ТЕКСТОВАЯ схема того же потока:
    ``search_server · search_web → 5 элементов → data_server · summarize → …``.
    Текстовая форма нужна не «на всякий случай»: диаграмма рисуется js-mermaid
    уже в браузере пользователя, и в окружениях, где этот код не выполняется
    (headless-проверки, отключённый JS), область осталась бы пустой — а след
    прогона обязан читаться всегда. Задание дня допускает и текстовую схему.
    """
    st.markdown("**Диаграмма флоу**")
    if not steps:
        st.caption("Схема появится, когда начнут выполняться шаги.")
        return
    st.mermaid_chart(flow_diagram(steps))
    st.code(flow_text(steps), language=None)


def flow_diagram(steps: list[dict]) -> str:
    """Определение диаграммы mermaid: узел на шаг, подпись ребра — объём данных."""
    lines = ["flowchart LR"]
    for index, step in enumerate(steps):
        server = step.get("server_name") or "—"
        tool = step.get("tool_name") or ""
        mark = STEP_STATUS_LABELS.get(step.get("status"), "")
        lines.append(f'    S{index}["{mark} {server}<br/>{tool}"]')
    for index in range(len(steps) - 1):
        label = edge_label(steps[index]).replace('"', "'")
        lines.append(f'    S{index} -->|"{label}"| S{index + 1}')
    return "\n".join(lines)


def flow_text(steps: list[dict]) -> str:
    """Текстовая схема потока: шаг, сервер, инструмент и объём до следующего шага."""
    lines: list[str] = []
    for index, step in enumerate(steps):
        server = step.get("server_name") or "—"
        tool = step.get("tool_name") or "?"
        mark = STEP_STATUS_LABELS.get(step.get("status"), "")
        head = f"{index}. {mark} {server} · {tool}"
        if index < len(steps) - 1:
            lines.append(f"{head}  →[{edge_label(step)}]→")
        else:
            lines.append(f"{head}  ({edge_label(step)})")
    return "\n".join(lines)


def edge_label(step: dict) -> str:
    """Что именно ушло следующему серверу: объём, имя файла или номер строки."""
    structured = structured_of(step)
    tool = step.get("tool_name") or ""
    if tool in ("search_web", "search_local"):
        return f"{structured.get('count', 0)} элементов"
    if tool == "summarize":
        return f"{len(str(structured.get('summary_text') or ''))} знаков"
    if tool == "extract_keywords":
        return f"{structured.get('count', 0)} ключевых слов"
    if tool == "save_to_file":
        return f"файл {structured.get('filename') or '—'}"
    if tool == "save_to_db":
        return f"строка {structured.get('row_id') or '—'}"
    return step.get("status") or "—"


def render_steps_table(steps: list[dict]) -> None:
    """Таблица шагов: индекс, сервер, инструмент, вход, выход, время и статус."""
    st.markdown("**Таблица шагов**")
    if not steps:
        st.caption("Шагов пока нет.")
        return
    st.dataframe([step_row(step) for step in steps],
                 width="stretch", hide_index=True)


def step_row(step: dict) -> dict:
    """Строка таблицы шагов: объёмы сокращены, чтобы таблица читалась."""
    output = step.get("output_result") or {}
    structured = output.get("structured")
    return {
        "шаг": step.get("step_index"),
        "сервер": step.get("server_name") or "—",
        "инструмент": step.get("tool_name"),
        "входные данные": brief(step.get("input_args")),
        "выходные данные": brief(structured) if structured else (output.get("text") or
                                                                output.get("reason_code") or "—"),
        "время": f"{step.get('duration_ms', 0)} мс",
        "статус": f"{STEP_STATUS_LABELS.get(step.get('status'), '')} "
                  f"{step.get('status')}",
    }


def brief(value, limit: int = 90) -> str:
    """Короткое текстовое представление аргументов и результатов для таблицы."""
    if value is None:
        return "—"
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def structured_of(step: dict) -> dict:
    """Структурированный выход шага (``{}`` — результата нет)."""
    output = step.get("output_result") or {}
    structured = output.get("structured")
    return structured if isinstance(structured, dict) else {}


