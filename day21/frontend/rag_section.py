"""Панель «🔍 RAG-запрос по корпусу» и раздел «🆚 RAG-сравнение» (день 22).

RAG живёт в процессе бэкенда: интерфейс задаёт вопрос, показывает ответ, метрики
(время, токены, число фрагментов, доля ввода из кэша контекста) и использованные
фрагменты корпуса — источник, заголовок, раздел, ``chunk_id`` и оценку близости.
Разметку ответа и работу с индексом интерфейс не повторяет: он только показывает
то, что вернул ``POST /rag/query``.

Два места использования одного и того же отображения:

* панель в разделе «💬 Чат и память» — вопрос к корпусу, переключатель RAG и топ-K,
  ответ и список фрагментов; выключенный переключатель даёт ответ по памяти модели
  на тот же вопрос (различие ровно одно — блок контекста, как и на бэкенде);
* раздел «🆚 RAG-сравнение» — один вопрос, два ответа рядом и их метрики, чтобы
  видеть разницу «с корпусом» и «без корпуса» на одном экране.

Источник данных корпуса — ``documents/rag_corpus``: производные данные, их
собирают скрипты дня (``scripts/prepare_rag_corpus.py`` и
``scripts/index_rag_corpus.py``), а не ручная выкладка файлов.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, rag_api

#: Границы и значение по умолчанию для размера контекста (лимит бэкенда — 10).
RAG_TOP_K_MIN = 1
RAG_TOP_K_MAX = 10
RAG_TOP_K_DEFAULT = 5

#: Стратегии поиска по корпусу: имя namespace индекса → подпись для человека.
RAG_STRATEGIES = (
    ("rag_corpus_structural", "структурная (по разделам)"),
    ("rag_corpus_fixed", "фиксированное окно"),
)

#: Ключи состояния сессии: последний ответ панели и последнее сравнение.
RAG_RESULT_KEY = "rag_last"
RAG_COMPARE_KEY = "rag_compare_last"

#: Метрики ответа: подпись и как её посчитать (``tokens`` — словарь расхода или {}).
METRICS = {
    "time": ("Время", lambda record, tokens: f"{int(record.get('duration_ms') or 0) / 1000:.2f} с"),
    "tokens": ("Токены", lambda record, tokens: common.fmt_int(_token_total(tokens)) if tokens else "—"),
    "chunks": ("Фрагментов", lambda record, tokens: str(int(record.get("chunks_used") or 0))),
    "context": ("Контекст", lambda record, tokens: f"{common.fmt_int(record.get('context_tokens') or 0)} токенов"),
    "cache": ("Кэш контекста",
              lambda record, tokens: f"{float(tokens.get('cache_hit_percent') or 0):.1f} %"
              if tokens else "—"),
}


def render_chat_rag_panel() -> None:
    """Панель «🔍 RAG-запрос по корпусу»: вопрос, ответ, метрики и фрагменты."""
    st.subheader("🔍 RAG-запрос по корпусу")
    st.caption("Вопрос ищет фрагменты в корпусе документов дня 21 и уходит модели "
               "вместе с ними; выключенный переключатель отправляет тот же вопрос "
               "без контекста — это видно по числу фрагментов и по ответу.")
    _config_caption(_load_config())
    use_rag = st.toggle("RAG: включён", value=True, key="rag_use_rag",
                        help="Выключить — ответ придёт по памяти модели, без корпуса.")
    top_k = _top_k_slider("rag_top_k", disabled=not use_rag)
    strategy = _strategy_select("rag_strategy", disabled=not use_rag)
    with st.form("rag_form", clear_on_submit=True):
        question = st.text_area("Вопрос к корпусу RAG", height=80,
                                placeholder="Например: чему равен CHARS_PER_PAGE "
                                            "в day21/backend/services/document_loader.py?")
        submitted = st.form_submit_button("🔎 Найти ответ", type="primary")
    if submitted:
        _ask(question, top_k, strategy, use_rag)
    record = st.session_state.get(RAG_RESULT_KEY)
    if record:
        _render_result(record, show_sources=True)
    else:
        st.info("Задайте вопрос по документам дня 21: ответ придёт вместе со "
                "списком использованных фрагментов корпуса.")


def render_rag_compare_section() -> None:
    """Раздел «🆚 RAG-сравнение»: один вопрос, два ответа рядом с метриками."""
    st.title("🆚 RAG-сравнение")
    st.caption("Один и тот же вопрос задаётся модели дважды: слева — без корпуса, "
               "справа — с фрагментами индекса RAG. Сравнение показывает, что "
               "добавляет корпус, а отчёт по десяти контрольным вопросам лежит в "
               "`docs/reports/rag_eval.md`.")
    _config_caption(_load_config())
    columns = st.columns([1, 2])
    with columns[0]:
        top_k = _top_k_slider("rag_compare_top_k")
    with columns[1]:
        strategy = _strategy_select("rag_compare_strategy")
    with st.form("rag_compare_form", clear_on_submit=True):
        question = st.text_area("Вопрос для сравнения", height=80,
                                placeholder="Например: какие хосты пропускает "
                                            "тестовый гвард no_real_network?")
        submitted = st.form_submit_button("🆚 Сравнить", type="primary")
    if submitted:
        _compare(question, top_k, strategy)
    record = st.session_state.get(RAG_COMPARE_KEY)
    if not record:
        st.info("Задайте вопрос и нажмите «🆚 Сравнить»: ответы появятся рядом.")
        return
    st.markdown(f"**Вопрос:** {record.get('question') or '—'}")
    left, right = st.columns(2)
    with left:
        st.markdown("**🚫 Без RAG**")
        _render_result(record.get("no_rag") or {},
                       keys=("time", "tokens", "chunks"))
    with right:
        st.markdown("**✅ С RAG**")
        _render_result(record.get("rag") or {}, show_sources=True)


# ---------- действия ----------
def _ask(question: str, top_k: int, strategy: str, use_rag: bool) -> None:
    """Отправляет вопрос и кладёт ответ в состояние сессии (пустой — плашкой)."""
    if not question.strip():
        common.flash("error", "Введите вопрос: пустой запрос бэкенд отвергает.")
        st.rerun()
    try:
        record = rag_api.api_rag_query(question, top_k, strategy, use_rag)
    except api_client.BackendError as exc:
        common.flash("error", f"RAG-запрос не выполнен: {exc.message}")
    else:
        st.session_state[RAG_RESULT_KEY] = record
    st.rerun()


def _compare(question: str, top_k: int, strategy: str) -> None:
    """Отправляет вопрос на сравнение и кладёт оба ответа в состояние сессии."""
    if not question.strip():
        common.flash("error", "Введите вопрос: пустой запрос бэкенд отвергает.")
        st.rerun()
    try:
        record = rag_api.api_rag_compare(question, top_k, strategy)
    except api_client.BackendError as exc:
        common.flash("error", f"Сравнение не выполнено: {exc.message}")
    else:
        st.session_state[RAG_COMPARE_KEY] = record
    st.rerun()


# ---------- отображение ----------
def _render_result(record: dict, show_sources: bool = False,
                   keys=("time", "tokens", "chunks", "cache")) -> None:
    """Ответ одного запроса: текст, предупреждение отката, метрики и фрагменты."""
    st.markdown(common.esc(record.get("answer") or "—"))
    if record.get("fallback"):
        st.warning(record.get("warning")
                   or "Ответ получен без контекста: вызов модели с корпусом не удался.")
    if record.get("grounding"):
        st.caption(f"Опора в контексте: {record['grounding']}")
    _render_metrics(record, keys)
    if show_sources:
        _render_sources(record.get("sources") or [])


def _render_metrics(record: dict, keys) -> None:
    """Метрики ответа столбцами: время, токены, фрагменты, контекст и кэш."""
    tokens = record.get("tokens") or {}
    columns = st.columns(len(keys))
    for column, key in zip(columns, keys):
        label, builder = METRICS[key]
        column.metric(label, builder(record, tokens))


def _render_sources(sources: list) -> None:
    """Использованные фрагменты корпуса: источник, заголовок, раздел, id, оценка."""
    with st.expander("📚 Использованные источники", expanded=False):
        if not sources:
            st.info("Поиск не дал источников: включите RAG или проиндексируйте корпус.")
            return
        st.dataframe([_source_row(source) for source in sources],
                     width="stretch", hide_index=True)


def _source_row(source: dict) -> dict:
    """Строка таблицы источников (подписи интерфейса, а не значения API)."""
    return {
        "источник": source.get("source"),
        "заголовок": source.get("title"),
        "раздел": source.get("section") or "—",
        "chunk_id": source.get("chunk_id"),
        "score": source.get("score"),
    }


def _config_caption(config: dict | None) -> None:
    """Подпись о корпусе: документы, страницы и фрагменты индекса (или предупреждение)."""
    if not config:
        return
    corpus = config.get("corpus") or {}
    if config.get("ready"):
        st.caption(f"Корпус: {corpus.get('documents')} документов · "
                   f"{corpus.get('pages')} страниц · "
                   f"{common.fmt_int(config.get('chunks_total') or 0)} фрагментов "
                   f"в индексе · топ-K до {config.get('top_k_max')}")
        return
    st.warning("Корпус RAG не готов: соберите и проиндексируйте его командами "
               "`python scripts/prepare_rag_corpus.py` и "
               "`python scripts/index_rag_corpus.py`.")


def _load_config() -> dict | None:
    """Состояние корпуса; ошибка бэкенда — плашкой и ``None`` (страница цела)."""
    try:
        return rag_api.api_rag_config()
    except api_client.BackendError as exc:
        st.warning(f"Состояние корпуса RAG недоступно: {exc.message}")
        return None


# ---------- общее ----------
def _top_k_slider(key: str, disabled: bool = False) -> int:
    """Слайдер размера контекста: сколько фрагментов уходит в промпт."""
    return st.slider("Сколько фрагментов (top_k)", RAG_TOP_K_MIN, RAG_TOP_K_MAX,
                     RAG_TOP_K_DEFAULT, key=key, disabled=disabled,
                     help="Значение выше лимита бэкенд урезает до 10.")


def _strategy_select(key: str, disabled: bool = False) -> str:
    """Выбор стратегии поиска по корпусу (имя namespace индекса)."""
    labels = dict(RAG_STRATEGIES)
    return st.selectbox("Стратегия поиска", [value for value, _ in RAG_STRATEGIES],
                        format_func=lambda value: labels.get(value, value),
                        key=key, disabled=disabled)


def _token_total(tokens: dict) -> int:
    """Токены запроса и ответа вместе (0 — счётчика нет)."""
    return int(tokens.get("prompt_tokens") or 0) + int(tokens.get("completion_tokens") or 0)
