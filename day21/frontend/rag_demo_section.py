"""Раздел «🧪 RAG-демо» (день 24): контрольные вопросы и один прогон.

Раздел отвечает на вопрос задания: несёт ли RAG-ответ источники и цитаты и умеет
ли он сказать «не знаю». Вопросы лежат на бэкенде
(``day21/backend/data/demo_questions.json``) — интерфейс их не дублирует, а
спрашивает ``GET /rag/demo-questions``; прогон идёт по одному вопросу за запрос
(``POST /rag/demo-run``), чтобы прогресс был виден построчно, а режим, источники,
цитаты, уверенность и вердикт каждой строки считал бэкенд, а не интерфейс.

Порог релевантности печатается под заголовком: он объясняет, почему часть строк
пришла в режиме «не знаю» (``dont_know``). Задаётся он переменной
``RAG_RELEVANCE_THRESHOLD`` в ``day21/.env`` и требует перезапуска бэкенда.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, rag_api

#: Ключи состояния сессии: список вопросов и результат последнего прогона.
RAG_DEMO_QUESTIONS_KEY = "rag_demo_questions"
RAG_DEMO_RESULTS_KEY = "rag_demo_results"

#: Обрезка ответа и цитаты в итоговой таблице (полный текст — в разделе чата).
DEMO_ANSWER_CHARS = 160
DEMO_QUOTE_CHARS = 60

#: Серверные вердикты, означающие «строка совпала с ожиданием»: ответ найден в
#: корпусе или, наоборот, ожидаемого ответа в корпусе действительно нет.
DEMO_MATCHED_VERDICTS = ("совпадает", "верно: ответа в корпусе нет")

#: Подпись пустой колонки итоговой таблицы.
DEMO_EMPTY = "—"


def render_rag_demo_section() -> None:
    """Раздел «🧪 RAG-демо»: вопросы, кнопка прогона и итоговая таблица."""
    st.title("🧪 RAG-демо")
    config = _load_config()
    if config is None:
        return
    st.caption("Десять контрольных вопросов: пять с ответом в корпусе, три частичных "
               "и два без ответа. По каждой строке видно режим, ответ, источники, "
               "цитаты и вердикт — совпало ли это с ожиданием.")
    st.caption(f"Порог релевантности: {float(config.get('relevance_threshold') or 0.0):g} "
               "— если максимум косинуса по пулу кандидатов ниже порога, ответ "
               "приходит в режиме «не знаю» и модель не вызывается. Порог задаётся "
               "`RAG_RELEVANCE_THRESHOLD` в `day21/.env` (нужен перезапуск бэкенда).")
    questions = _questions()
    if not questions:
        return
    st.dataframe(_question_rows(questions), width="stretch", hide_index=True)
    if st.button("🚀 Прогнать демо", type="primary"):
        _run(questions)
    _render_results()


def _load_config() -> dict | None:
    """Состояние корпуса с порогом; ошибка бэкенда — плашкой и ``None``."""
    try:
        return rag_api.api_rag_config()
    except api_client.BackendError as exc:
        st.warning(f"Состояние корпуса RAG недоступно: {exc.message}")
        return None


def _questions() -> list:
    """Контрольные вопросы бэкенда, кэш в состоянии сессии (пустой список — плашкой)."""
    cached = st.session_state.get(RAG_DEMO_QUESTIONS_KEY)
    if cached is None:
        try:
            cached = (rag_api.api_rag_demo_questions() or {}).get("questions") or []
        except api_client.BackendError as exc:
            st.warning(f"Список демо-вопросов недоступен: {exc.message}")
            return []
        st.session_state[RAG_DEMO_QUESTIONS_KEY] = cached
    if not cached:
        st.info("Список демо-вопросов пуст: проверьте "
                "`day21/backend/data/demo_questions.json`.")
    return cached


def _run(questions: list) -> None:
    """Прогон демо по одному вопросу за запрос; результат — в состояние сессии."""
    rows: list = []
    total = len(questions)
    progress = st.progress(0.0, text=f"0/{total}")
    for index, item in enumerate(questions, start=1):
        question = item.get("question") or ""
        progress.progress((index - 1) / total, text=f"{index}/{total}: {question[:60]}")
        try:
            payload = rag_api.api_rag_demo_run(question)
        except api_client.BackendError as exc:
            common.flash("error", f"Прогон прерван на вопросе {index}: {exc.message}")
            st.session_state.pop(RAG_DEMO_RESULTS_KEY, None)
            st.rerun()
        rows.extend(payload.get("rows") or [])
        progress.progress(index / total, text=f"{index}/{total}: {question[:60]}")
    st.session_state[RAG_DEMO_RESULTS_KEY] = {"rows": rows, "summary": _summary(rows)}
    st.rerun()


def _summary(rows: list) -> dict:
    """Сводка прогона по полям строк: режим, источники, цитаты и вердикт сервера."""
    return {
        "total": len(rows),
        "rag": sum(1 for row in rows if row.get("mode") == "rag"),
        "dont_know": sum(1 for row in rows if row.get("mode") == "dont_know"),
        "with_sources": sum(1 for row in rows if row.get("sources")),
        "with_quotes": sum(1 for row in rows if row.get("quotes")),
        "matched": sum(1 for row in rows
                       if row.get("verdict") in DEMO_MATCHED_VERDICTS),
    }


# ---------- отображение ----------
def _question_rows(questions: list) -> list:
    """Таблица контрольных вопросов: номер, вопрос, ожидание и ожидаемый режим."""
    return [{"№": index,
             "Вопрос": item.get("question") or DEMO_EMPTY,
             "Ожидание": item.get("expectation") or DEMO_EMPTY,
             "Ожидаемый режим": item.get("expected_mode") or DEMO_EMPTY}
            for index, item in enumerate(questions, start=1)]


def _result_rows(rows: list) -> list:
    """Итоговая таблица прогона: режим, срезанный ответ, источники, цитаты, вердикт."""
    return [{"Вопрос": row.get("question") or DEMO_EMPTY,
             "Режим": row.get("mode") or DEMO_EMPTY,
             "Ответ": _short(row.get("answer"), DEMO_ANSWER_CHARS),
             "Источники": _sources_caption(row.get("sources") or []),
             "Цитаты": _quotes_caption(row.get("quotes") or []),
             "Вердикт": row.get("verdict") or DEMO_EMPTY}
            for row in rows]


def _sources_caption(sources: list) -> str:
    """Первая колонка таблицы «Источники»: сколько их и какой первый."""
    if not sources:
        return DEMO_EMPTY
    return f"{len(sources)} · {sources[0].get('source') or DEMO_EMPTY}"


def _quotes_caption(quotes: list) -> str:
    """Первая колонка таблицы «Цитаты»: сколько их и начало первой."""
    if not quotes:
        return DEMO_EMPTY
    return f"{len(quotes)} · {_short(quotes[0].get('quote'), DEMO_QUOTE_CHARS)}"


def _short(text, limit: int = DEMO_ANSWER_CHARS) -> str:
    """Однострочная обрезка текста для таблицы (пустой текст — прочерк)."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return DEMO_EMPTY
    return flat if len(flat) <= limit else f"{flat[:limit]}…"


def _render_results() -> None:
    """Итоговая таблица последнего прогона и подпись со сводкой под ней."""
    result = st.session_state.get(RAG_DEMO_RESULTS_KEY)
    if not result:
        st.info("Нажмите «🚀 Прогнать демо»: прогон делает столько запросов, "
                "сколько вопросов в списке.")
        return
    rows = result.get("rows") or []
    summary = result.get("summary") or {}
    st.markdown(f"**Результат прогона: {summary.get('total', len(rows))} вопросов**")
    st.dataframe(_result_rows(rows), width="stretch", hide_index=True)
    st.caption(f"С источниками: {summary.get('with_sources', 0)} · "
               f"с цитатами: {summary.get('with_quotes', 0)} · "
               f"режим RAG: {summary.get('rag', 0)} · "
               f"«не знаю»: {summary.get('dont_know', 0)} · "
               f"совпало с ожиданием: {summary.get('matched', 0)} из "
               f"{summary.get('total', len(rows))}. Отчёт с ручной проверкой — "
               "`docs/reports/rag_quotes_eval.md`.")
