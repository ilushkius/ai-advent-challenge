"""Раздел «🖥 Локальная LLM (Ollama)» дня 26: три запроса к модели на своей машине.

Раздел отвечает на вопрос «работает ли второй провайдер» без облака: подпись
показывает провайдера по умолчанию, модель и адрес Ollama (``GET /llm/provider``),
кнопка прогоняет три запроса (``POST /llm/local-demo`` — их делает бэкенд) и
приносит ответы вместе со временем, токенами и эвристической оценкой качества.

Первый запрос грузит веса модели в память, поэтому кнопка предупреждает об этом
заранее, а предел ожидания HTTP-запроса — ``LONG_TIMEOUT`` (10 минут). Недоступная
Ollama — не падение страницы, а красная плашка с текстом причины.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, llm_api

#: Последний прогон демо: переживает rerun'ы, поэтому хранится в состоянии сессии.
DEMO_KEY = "local_demo_last"


def render_local_llm_section() -> None:
    """Раздел «🖥 Локальная LLM»: состояние провайдера, прогон и таблица ответов."""
    st.subheader("🖥 Локальная LLM (Ollama)")
    st.caption("Второй провайдер рядом с DeepSeek: ответы приходят из Ollama по HTTP "
               "из программы (бэкенд ходит в `/api/chat`), платных токенов не тратится. "
               "Модель считается локальным железом, поэтому ответ идёт десятками секунд.")
    _provider_caption()
    if st.button("▶ Прогнать 3 запроса", type="primary", key="local_demo_run"):
        _run_demo()
    _render_rows(st.session_state.get(DEMO_KEY))


def _run_demo() -> None:
    """Прогон трёх запросов: результат кладётся в состояние сессии, таблица — ниже.

    Отдельного ``st.rerun`` не нужно: ответ попадает в ``session_state`` до
    ``_render_rows`` в этом же проходе скрипта, а ошибка показывается плашкой.
    """
    with st.spinner("Локальная модель отвечает (первый запрос грузит веса в память)…"):
        try:
            st.session_state[DEMO_KEY] = llm_api.api_local_demo()
        except api_client.BackendError as exc:
            st.session_state[DEMO_KEY] = None
            st.error(f"Демо локальной модели не выполнено: {exc.message}")


def _provider_caption() -> None:
    """Подпись о провайдере и локальной модели; недоступный бэкенд — тоже подписью."""
    try:
        info = llm_api.api_llm_provider()
    except api_client.BackendError as exc:
        st.caption(f"Провайдер: неизвестен (бэкенд недоступен: {exc.message})")
        return
    labels = info.get("labels") or {}
    default = str(info.get("provider") or "")
    st.caption(f"Провайдер по умолчанию: {labels.get(default, default) or '—'} · "
               f"локальная модель: {info.get('local_model') or '—'} · "
               f"адрес: {info.get('local_url') or '—'} · "
               f"таймаут: {info.get('local_timeout') or '—'} с")


def _render_rows(demo: dict | None) -> None:
    """Таблица трёх ответов и полный текст каждого: вопрос, ответ, время, токены."""
    if not demo:
        st.info("Нажмите кнопку: три запроса уйдут в локальную модель, а в таблице "
                "появятся ответ, время и токены. Первый запрос — самый долгий: "
                "модель грузится в память (~30–60 с).")
        return
    rows = demo.get("rows") or []
    st.caption(f"Модель: {demo.get('model') or '—'} · адрес: {demo.get('url') or '—'} · "
               f"итого {int(demo.get('total_ms') or 0) / 1000:.1f} с на {len(rows)} запроса")
    st.dataframe([_row_table(item) for item in rows], width="stretch", hide_index=True)
    for index, item in enumerate(rows):
        with st.expander(f"{item.get('title') or item.get('key')} — полный ответ",
                         expanded=index == 0):
            st.markdown(f"**Вопрос:** {item.get('question') or '—'}")
            st.markdown(common.esc(item.get("answer") or "—"))


def _row_table(item: dict) -> dict:
    """Строка таблицы демо: подписи интерфейса, а время — в секундах."""
    tokens = item.get("tokens") or {}
    return {
        "запрос": item.get("title") or item.get("key"),
        "ответ": _short(item.get("answer")),
        "время, с": round(int(item.get("duration_ms") or 0) / 1000, 2),
        "токены (вход/выход)": f"{tokens.get('prompt_tokens', 0)} / {tokens.get('completion_tokens', 0)}",
        "качество (эвристика)": f"{item.get('quality')}/5",
        "провайдер": item.get("provider") or "—",
    }


def _short(text, limit: int = 160) -> str:
    """Ответ одной строкой таблицы: длинный текст обрезается многоточием."""
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit] + "…"
