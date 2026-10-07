"""Раздел «🏠 Локальный RAG» (день 28): один вопрос — два ответа, локальный и облачный.

Retrieval здесь всегда локальный: FAISS-индекс дня 22 с диска плюс
sentence-transformers. Сравнивается не поиск, а тот, кто генерирует ответ, поэтому обе
колонки таблицы опираются на одну и ту же выдачу корпуса и различаются только моделью,
временем, режимом и вердиктом.

Прогон идёт по одному вопросу за запрос (``POST /rag/compare_providers`` с одним
вопросом в теле): так виден прогресс, а упавший вопрос не убивает остальные. Сводку
считает тот же домен, что и бэкенд (``backend/domain/rag_compare``) — второго правила
средних в интерфейсе нет. Первый запрос грузит веса модели в память, о чём кнопка
предупреждает заранее: предел ожидания HTTP-запроса — ``LONG_TIMEOUT``.
"""
from __future__ import annotations

import streamlit as st

from backend.domain.rag_compare import summary as rag_compare_summary

from . import api_client, common, llm_api, rag_api

#: Ключи состояния сессии: правка списка вопросов и результат последнего прогона.
LOCAL_RAG_QUESTIONS_KEY = "local_rag_questions"
LOCAL_RAG_RESULT_KEY = "local_rag_results"

#: Обрезка ответа в итоговой таблице (полный текст — в раскрывашках под ней).
ANSWER_CHARS = 160

#: Подпись пустой ячейки.
EMPTY = "—"


def render_local_rag_section() -> None:
    """Раздел «🏠 Локальный RAG»: вопросы, кнопка прогона, таблица и сводка."""
    st.title("🏠 Локальный RAG")
    st.caption("Retrieval всегда локальный: FAISS-индекс дня 22 с диска и "
               "sentence-transformers. Отличается только тот, кто генерирует ответ, "
               "поэтому поиск по корпусу у обеих сторон один и тот же.")
    _provider_caption()
    config = _config_caption()
    if config is None:
        return
    editor = st.text_area("Вопросы (по одному в строке)", value=_questions_text(),
                          height=240, key=LOCAL_RAG_QUESTIONS_KEY)
    top_k = st.slider("Фрагментов в контексте (top_k)", 1, int(config["top_k_max"]),
                      int(config["top_k_default"]), key="local_rag_top_k")
    if st.button("🚀 Прогнать сравнение", type="primary", key="local_rag_run"):
        _run(_parse_questions(editor), top_k)
    _render_results()


def _provider_caption() -> None:
    """Подпись о провайдере по умолчанию и локальной модели; сбой — тоже подписью."""
    try:
        info = llm_api.api_llm_provider()
    except api_client.BackendError as exc:
        st.caption(f"Провайдер: неизвестен (бэкенд недоступен: {exc.message})")
        return
    labels = info.get("labels") or {}
    default = str(info.get("provider") or "")
    st.caption(f"Провайдер по умолчанию: {labels.get(default, default) or EMPTY} · "
               f"локальная модель: {info.get('local_model') or EMPTY} · "
               f"адрес: {info.get('local_url') or EMPTY} · "
               f"таймаут: {info.get('local_timeout') or EMPTY} с")


def _config_caption() -> dict | None:
    """Чанки по стратегиям и лимиты режима; ошибка бэкенда — плашкой и ``None``."""
    try:
        config = rag_api.api_rag_config()
    except api_client.BackendError as exc:
        st.warning(f"Состояние корпуса RAG недоступно: {exc.message}")
        return None
    chunks = " · ".join(f"{item.get('strategy') or EMPTY}: {int(item.get('chunks') or 0)}"
                        for item in (config.get("indexes") or []))
    st.caption(f"Чанков в индексах: {int(config.get('chunks_total') or 0)} "
               f"({chunks or EMPTY}) · стратегия по умолчанию: "
               f"{config.get('default_strategy') or EMPTY} · порог релевантности: "
               f"{float(config.get('relevance_threshold') or 0.0):g} (ниже него ответ "
               "приходит в режиме «не знаю» и модель не вызывается)")
    return config


def _questions_text() -> str:
    """Стартовое содержимое поля ввода: контрольные вопросы демо с бэкенда."""
    try:
        payload = rag_api.api_rag_demo_questions() or {}
    except api_client.BackendError as exc:
        st.warning(f"Список демо-вопросов недоступен: {exc.message}")
        return ""
    return "\n".join(str(item.get("question") or "").strip()
                     for item in (payload.get("questions") or [])
                     if str(item.get("question") or "").strip())


def _parse_questions(text) -> list:
    """Список вопросов из поля ввода: по строке на вопрос, пустые строки пропускаются."""
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _run(questions: list, top_k: int) -> None:
    """Прогон по одному вопросу за запрос; результат — в состояние сессии."""
    if not questions:
        st.info("Список вопросов пуст: добавьте строки в поле выше.")
        return
    rows: list = []
    total = len(questions)
    progress = st.progress(0.0, text=f"0/{total}")
    for index, question in enumerate(questions, start=1):
        progress.progress((index - 1) / total, text=f"{index}/{total}: {question[:60]}")
        try:
            payload = rag_api.api_rag_compare_providers([question], top_k=top_k)
        except api_client.BackendError as exc:
            common.flash("error", f"Прогон прерван на вопросе {index}: {exc.message}")
            st.session_state.pop(LOCAL_RAG_RESULT_KEY, None)
            st.rerun()
        rows.extend(payload.get("rows") or [])
        progress.progress(index / total, text=f"{index}/{total}: {question[:60]}")
    st.session_state[LOCAL_RAG_RESULT_KEY] = {"rows": rows,
                                              "summary": rag_compare_summary(rows)}
    st.rerun()


# ---------- отображение ----------
def _side(row: dict, name: str) -> dict:
    """Запись стороны строки (``local``/``cloud``); отсутствующая — пустая."""
    return row.get(name) or {}


def _result_rows(rows: list) -> list:
    """Итоговая таблица: обе стороны строкой — ответ, источники, время, режим, вердикт."""
    return [{"№": index,
             "Вопрос": row.get("question") or EMPTY,
             "Ответ local": _short(_side(row, "local").get("answer")),
             "Ответ cloud": _short(_side(row, "cloud").get("answer")),
             "Источники (local / cloud)": " / ".join(
                 str(len(_side(row, side).get("sources") or []))
                 for side in ("local", "cloud")),
             "Время local, с": _seconds(_side(row, "local")),
             "Время cloud, с": _seconds(_side(row, "cloud")),
             "Режим (local / cloud)": " / ".join(
                 str(_side(row, side).get("mode") or EMPTY)
                 for side in ("local", "cloud")),
             "Вердикт": row.get("verdict") or EMPTY}
            for index, row in enumerate(rows, start=1)]


def _seconds(record: dict) -> float:
    """Время ответа стороны в секундах, округлённое до двух знаков."""
    return round(int(record.get("duration_ms") or 0) / 1000, 2)


def _short(text, limit: int = ANSWER_CHARS) -> str:
    """Ответ одной строкой таблицы: длинный текст обрезается многоточием."""
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else f"{value[:limit]}…"


def _sources_caption(sources: list) -> str:
    """Источники стороны одной строкой: ``источник · раздел`` на каждый фрагмент."""
    if not sources:
        return "Источников нет"
    return " · ".join(f"{item.get('source') or EMPTY} · {item.get('section') or EMPTY}"
                      for item in sources)


def _render_results() -> None:
    """Таблица прогона, сводка метриками и полные ответы в раскрывашках."""
    result = st.session_state.get(LOCAL_RAG_RESULT_KEY)
    if not result:
        st.info("Нажмите «🚀 Прогнать сравнение»: каждый вопрос уйдёт дважды — "
                "локальной модели Ollama и в облако DeepSeek. Первый запрос к "
                "локальной модели грузит её веса в память (~30–60 с).")
        return
    rows = result.get("rows") or []
    summary = result.get("summary") or {}
    st.markdown(f"**Результат прогона: {summary.get('total', len(rows))} вопросов**")
    st.dataframe(_result_rows(rows), width="stretch", hide_index=True)
    _render_summary(summary)
    for index, row in enumerate(rows, start=1):
        _render_row(index, row)


def _render_summary(summary: dict) -> None:
    """Сводка прогона: средние времена, источники и «не знаю» плюс общий вердикт."""
    columns = st.columns(4)
    columns[0].metric("Среднее время local, с",
                      round(int(summary.get("local_avg_ms") or 0) / 1000, 2))
    columns[1].metric("Среднее время cloud, с",
                      round(int(summary.get("cloud_avg_ms") or 0) / 1000, 2))
    columns[2].metric("Ответов с источниками (local / cloud)",
                      f"{summary.get('local_with_sources', 0)} / "
                      f"{summary.get('cloud_with_sources', 0)}")
    columns[3].metric("dont_know (local / cloud)",
                      f"{summary.get('local_dont_know', 0)} / "
                      f"{summary.get('cloud_dont_know', 0)}")
    st.caption(f"Общий вердикт: {summary.get('verdict') or EMPTY} · "
               f"локально лучше {summary.get('better_local', 0)} · "
               f"облако лучше {summary.get('better_cloud', 0)} · "
               f"равно {summary.get('equal', 0)}")


def _render_row(index: int, row: dict) -> None:
    """Полные ответы строки: обе стороны, их источники и предупреждение строки."""
    question = row.get("question") or EMPTY
    with st.expander(f"{index}. {question}"):
        columns = st.columns(2)
        for column, title, name in ((columns[0], "🖥 Local (Ollama)", "local"),
                                    (columns[1], "🌐 DeepSeek", "cloud")):
            record = _side(row, name)
            with column:
                st.markdown(f"**{title}** · {record.get('mode') or EMPTY} · "
                            f"{_seconds(record)} с · провайдер: "
                            f"{record.get('provider') or EMPTY}")
                st.markdown(common.esc(record.get("answer") or EMPTY))
                st.caption(_sources_caption(record.get("sources") or []))
        warnings = [str(_side(row, side).get("warning") or "")
                    for side in ("local", "cloud")]
        if any(warnings) or any(_side(row, side).get("fallback")
                                for side in ("local", "cloud")):
            st.warning(" · ".join(item for item in warnings if item)
                       or "Вызов не удался: ответ дан без контекста корпуса.")
