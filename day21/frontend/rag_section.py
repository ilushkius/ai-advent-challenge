"""Панель «🔍 RAG-запрос по корпусу» и раздел «🆚 RAG-сравнение» (дни 22–24).

RAG живёт в процессе бэкенда: интерфейс задаёт вопрос, показывает ответ, метрики
(время, токены, число фрагментов до и после отсечения, порог, доля ввода из кэша
контекста) и использованные фрагменты корпуса — источник, заголовок, раздел,
``chunk_id`` и все четыре балла отбора: гибридный, векторный, лексический и от
кросс-энкодера, а также цитаты фрагментов и уверенность ответа (день 24). Разметку
ответа и работу с индексом он не повторяет: только то, что вернул ``POST /rag/query``.

Два места использования одного и того же отображения:

* панель в разделе «💬 Чат и память» — вопрос к корпусу, переключатель RAG, топ-K,
  ступени отбора дня 23 (переформулировка вопроса, реранкер, порог отсечения),
  ответ и список фрагментов; выключенный переключатель даёт ответ по памяти модели
  на тот же вопрос (различие ровно одно — блок контекста, как и на бэкенде);
* раздел «🆚 RAG-сравнение» — один вопрос, два ответа рядом и их метрики, чтобы
  видеть разницу «с корпусом» и «без корпуса»; ниже — сравнение режимов отбора
  (``POST /rag/compare_modes``): до четырёх ответов на один вопрос, чтобы отдельно
  от ответа было видно, что добавляет переформулировка, реранкер и порог.

Источник данных корпуса — ``documents/rag_corpus``: производные данные, их
собирают скрипты дня (``scripts/prepare_rag_corpus.py`` и
``scripts/index_rag_corpus.py``), а не ручная выкладка файлов.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import llm_provider

from . import api_client, common, rag_api

#: Границы и значение по умолчанию для размера контекста (лимит бэкенда — 10).
RAG_TOP_K_MIN = 1
RAG_TOP_K_MAX = 10
RAG_TOP_K_DEFAULT = 5

#: Ступени отбора дня 23: режимы сравнения по умолчанию и порог «без отсечения».
RAG_MODE_DEFAULTS = ("baseline", "rerank_filter")
RAG_MIN_SCORE_MIN = 0.0
RAG_MIN_SCORE_MAX = 1.0

#: Стратегии поиска по корпусу: имя namespace индекса → подпись для человека.
RAG_STRATEGIES = (
    ("rag_corpus_structural", "структурная (по разделам)"),
    ("rag_corpus_fixed", "фиксированное окно"),
)

#: Ключи состояния сессии: последний ответ панели, сравнение и сравнение режимов.
RAG_RESULT_KEY = "rag_last"
RAG_COMPARE_KEY = "rag_compare_last"
RAG_MODES_KEY = "rag_modes_last"

#: Метрики ответа: подпись и как её посчитать (``tokens`` — словарь расхода или {}).
METRICS = {
    "provider": ("Провайдер",
                 lambda record, tokens: llm_provider.label(record.get("provider")) or "—"),
    "time": ("Время", lambda record, tokens: f"{int(record.get('duration_ms') or 0) / 1000:.2f} с"),
    "tokens": ("Токены", lambda record, tokens: common.fmt_int(_token_total(tokens)) if tokens else "—"),
    "chunks": ("Фрагментов", lambda record, tokens: str(int(record.get("chunks_used") or 0))),
    "candidates": ("До фильтра", lambda record, tokens: str(int(record.get("candidates") or 0))),
    "kept": ("После фильтра", lambda record, tokens: str(int(record.get("kept") or 0))),
    "min_score": ("Порог", lambda record, tokens: _score_caption(record)),
    "context": ("Контекст", lambda record, tokens: f"{common.fmt_int(record.get('context_tokens') or 0)} токенов"),
    "cache": ("Кэш контекста",
              lambda record, tokens: f"{float(tokens.get('cache_hit_percent') or 0):.1f} %"
              if tokens else "—"),
}

#: Пустой блок источников: причина зависит от режима (``""`` — прочие случаи).
NO_SOURCES_HINTS = {
    "dont_know": ("Источников нет: контекст слабее порога релевантности, ответ в режиме "
                  "«не знаю» — модель не вызывалась."),
    "no_rag": "Поиск не дал источников: включите RAG или проиндексируйте корпус.",
    "": "Поиск не дал источников: проиндексируйте корпус.",
}


def render_chat_rag_panel() -> None:
    """Панель «🔍 RAG-запрос по корпусу»: вопрос, ответ, метрики и фрагменты."""
    st.subheader("🔍 RAG-запрос по корпусу")
    st.caption("Вопрос ищет фрагменты в корпусе документов дня 21 и уходит модели "
               "вместе с ними; выключенный переключатель отправляет тот же вопрос "
               "без контекста — это видно по числу фрагментов и по ответу.")
    config = _load_config()
    _config_caption(config)
    use_rag = st.toggle("RAG: включён", value=True, key="rag_use_rag",
                        help="Выключить — ответ придёт по памяти модели, без корпуса.")
    top_k = _top_k_slider("rag_top_k", disabled=not use_rag)
    strategy = _strategy_select("rag_strategy", disabled=not use_rag)
    rewrite, rerank, min_score = _selection_widgets("rag", config, disabled=not use_rag)
    with st.form("rag_form", clear_on_submit=True):
        question = st.text_area("Вопрос к корпусу RAG", height=80,
                                placeholder="Например: чему равен CHARS_PER_PAGE "
                                            "в day21/backend/services/document_loader.py?")
        submitted = st.form_submit_button("🔎 Найти ответ", type="primary")
    if submitted:
        _ask(question, top_k, strategy, use_rag, rewrite, rerank, min_score)
    record = st.session_state.get(RAG_RESULT_KEY)
    if record:
        _render_result(record, show_sources=True)
    else:
        st.info("Задайте вопрос по документам дня 21: ответ придёт вместе со "
                "списком использованных фрагментов корпуса.")


def render_rag_compare_section() -> None:
    """Раздел «🆚 RAG-сравнение»: один вопрос — ответы без RAG и с RAG, затем режимы."""
    st.title("🆚 RAG-сравнение")
    st.caption("Один и тот же вопрос задаётся модели дважды: слева — без корпуса, "
               "справа — с фрагментами индекса RAG. Сравнение показывает, что "
               "добавляет корпус, а отчёт по десяти контрольным вопросам лежит в "
               "`docs/reports/rag_modes.md`.")
    config = _load_config()
    _config_caption(config)
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
    _render_modes_form(config, top_k, strategy)
    record = st.session_state.get(RAG_COMPARE_KEY)
    if record:
        st.markdown(f"**Вопрос:** {record.get('question') or '—'}")
        left, right = st.columns(2)
        with left:
            st.markdown("**🚫 Без RAG**")
            _render_result(record.get("no_rag") or {},
                           keys=("provider", "time", "tokens", "chunks"))
        with right:
            st.markdown("**✅ С RAG**")
            _render_result(record.get("rag") or {}, show_sources=True)
    else:
        st.info("Задайте вопрос и нажмите «🆚 Сравнить»: ответы появятся рядом.")
    _render_modes_result()


def _render_modes_form(config: dict | None, top_k: int, strategy: str) -> None:
    """Форма сравнения режимов отбора: мультиселект четырёх ступеней и кнопка."""
    modes = config.get("modes") or []
    names = [mode.get("name") for mode in modes if mode.get("name")]
    if not names:
        return
    labels = {mode["name"]: mode.get("label") or mode["name"] for mode in modes}
    st.divider()
    st.markdown("**Сравнение режимов отбора** — что добавляет каждая ступень дня 23")
    with st.form("rag_modes_form"):
        chosen = st.multiselect(
            "Режимы для сравнения", options=names,
            default=[name for name in RAG_MODE_DEFAULTS if name in names],
            format_func=lambda name: f"{name} — {labels.get(name, name)}",
            key="rag_modes_choice",
            help="baseline — порядок дня 22; rewrite — переформулировка вопроса; "
                 "rerank — кросс-энкодер; rerank_filter — реранкер и порог отсечения.",
        )
        question = st.text_area("Вопрос для сравнения режимов", height=80,
                                key="rag_modes_question",
                                placeholder="Например: чему равен CHARS_PER_PAGE "
                                            "в day21/backend/services/document_loader.py?")
        submitted = st.form_submit_button("🆚 Сравнить режимы", type="primary")
    if submitted:
        _compare_modes(question, top_k, strategy, chosen)


def _render_modes_result() -> None:
    """Ответы всех выбранных режимов рядом: у каждого свои метрики и источники."""
    record = st.session_state.get(RAG_MODES_KEY)
    if not record:
        return
    entries = record.get("modes") or []
    if not entries:
        st.info("Ни один режим не сравнивался: выберите хотя бы один.")
        return
    st.markdown(f"**Вопрос:** {record.get('question') or '—'}")
    for column, entry in zip(st.columns(len(entries)), entries):
        with column:
            st.markdown(f"**{entry.get('label') or entry.get('mode')}**")
            _render_result(entry.get("result") or {}, show_sources=True)


# ---------- действия ----------
def _ask(question: str, top_k: int, strategy: str, use_rag: bool, rewrite: bool,
         rerank: bool, min_score: float | None) -> None:
    """Отправляет вопрос и кладёт ответ в состояние сессии (пустой — плашкой).

    Провайдер берётся из боковой панели: она рисуется раньше основной области.
    """
    if not question.strip():
        common.flash("error", "Введите вопрос: пустой запрос бэкенд отвергает.")
        st.rerun()
    try:
        record = rag_api.api_rag_query(question, top_k, strategy, use_rag, rewrite,
                                       rerank, min_score,
                                       provider=st.session_state.get("llm_provider"))
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


def _compare_modes(question: str, top_k: int, strategy: str, modes: list) -> None:
    """Отправляет вопрос на сравнение режимов и кладёт записи в состояние сессии."""
    if not question.strip():
        common.flash("error", "Введите вопрос: пустой запрос бэкенд отвергает.")
        st.rerun()
    try:
        record = rag_api.api_rag_compare_modes(question, top_k, strategy, modes)
    except api_client.BackendError as exc:
        common.flash("error", f"Сравнение режимов не выполнено: {exc.message}")
    else:
        st.session_state[RAG_MODES_KEY] = record
    st.rerun()


# ---------- отображение ----------
def _render_result(record: dict, show_sources: bool = False,
                   keys=("provider", "time", "tokens", "chunks", "candidates", "kept",
                         "min_score", "cache")) -> None:
    """Ответ одного запроса: текст, предупреждения отбора, метрики и фрагменты."""
    st.markdown(common.esc(record.get("answer") or "—"))
    if record.get("rewritten") and record.get("query_used"):
        st.caption(f"Поиск шёл по переформулированному запросу: {record['query_used']}")
    if record.get("fallback"):
        st.warning(record.get("warning")
                   or "Ответ получен без контекста: вызов модели с корпусом не удался.")
    for key in ("rewrite_warning", "rerank_warning", "filter_warning"):
        if record.get(key):
            st.warning(record[key])
    if record.get("grounding"):
        st.caption(f"Опора в контексте: {record['grounding']}")
    if record.get("mode") == "dont_know":
        st.warning(record.get("warning") or "Недостаточно контекста в корпусе.")
    if record.get("mode") == "rag" and float(record.get("confidence") or 0.0) < 1.0:
        st.caption(f"⚠️ Уверенность {float(record.get('confidence') or 0.0):.1f}: "
                   "ответ не подтверждён цитатами")
    _render_quotes(record.get("quotes") or [])
    _render_metrics(record, keys)
    if show_sources:
        _render_sources(record.get("sources") or [], record.get("mode") or "")


def _render_quotes(quotes: list) -> None:
    """Цитаты из использованных фрагментов: источник, раздел, id и текст (день 24).

    Цитаты собирает бэкенд из текста фрагментов, а не модель: показывать их пусто
    нечем, поэтому при отсутствии цитат блок не выводится вовсе.
    """
    if not quotes:
        return
    with st.expander("📝 Цитаты из корпуса", expanded=False):
        for quote in quotes:
            st.caption(f"{quote.get('source') or '—'} · {quote.get('section') or '—'} · "
                       f"{quote.get('chunk_id') or '—'}")
            st.markdown(f"> {common.esc(quote.get('quote') or '')}")


def _render_metrics(record: dict, keys) -> None:
    """Метрики ответа столбцами: время, токены, фрагменты, контекст и кэш."""
    tokens = record.get("tokens") or {}
    columns = st.columns(len(keys))
    for column, key in zip(columns, keys):
        label, builder = METRICS[key]
        column.metric(label, builder(record, tokens))


def _render_sources(sources: list, mode: str = "") -> None:
    """Использованные фрагменты корпуса: источник, заголовок, раздел, id, оценка.

    Пустой блок объясняется по режиму: в ``dont_know`` поиск шёл, но контекст слабее
    порога, а совет включить RAG или проиндексировать корпус там просто неверен.
    """
    with st.expander("📚 Использованные источники", expanded=False):
        if not sources:
            st.info(NO_SOURCES_HINTS.get(mode, NO_SOURCES_HINTS[""]))
            return
        st.dataframe([_source_row(source) for source in sources],
                     width="stretch", hide_index=True)


def _source_row(source: dict) -> dict:
    """Строка таблицы источников (подписи интерфейса, а не значения API).

    Четыре балла показываются рядом намеренно: ``score`` — тот, по которому шёл
    отбор (реранкер, если он работал, иначе гибридный), ``vector``/``lexical`` —
    из чего собран гибридный, ``rerank`` — второй этап отбора. Пустой балл
    реранкера печатается прочерком: этап не выполнялся.
    """
    rerank_score = source.get("rerank_score")
    return {
        "источник": source.get("source"),
        "заголовок": source.get("title"),
        "раздел": source.get("section") or "—",
        "chunk_id": source.get("chunk_id"),
        "score": source.get("score"),
        "vector": source.get("vector_score"),
        "lexical": source.get("lexical_score"),
        "rerank": "—" if rerank_score is None else rerank_score,
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


def _selection_widgets(prefix: str, config: dict | None,
                       disabled: bool = False) -> tuple[bool, bool, float]:
    """Ступени отбора дня 23: переформулировка, реранкер и порог отсечения.

    Значение порога по умолчанию — измеренное ``min_score_default`` бэкенда
    (``GET /rag/config``): при смене модели реранкера калибровка повторяется на
    бэкенде, и интерфейс подхватывает новое значение сам. Ноль означает «без
    отсечения» и в запрос не отправляется.
    """
    rewrite = st.toggle("Переформулировать запрос моделью", value=False,
                        key=f"{prefix}_rewrite", disabled=disabled,
                        help="Модель переписывает вопрос в поисковый запрос; поиск "
                             "идёт по переформулировке, ответ — по исходному вопросу.")
    rerank = st.toggle("Реранкер: кросс-энкодер", value=True,
                       key=f"{prefix}_rerank", disabled=disabled,
                       help="Второй этап отбора: кросс-энкодер пересортировывает "
                            "кандидатов гибридного поиска.")
    default = float((config or {}).get("min_score_default") or RAG_MIN_SCORE_MIN)
    min_score = st.slider("Порог отсечения (min_score)", RAG_MIN_SCORE_MIN,
                          RAG_MIN_SCORE_MAX, value=default,
                          step=0.01, key=f"{prefix}_min_score", disabled=disabled,
                          help="0.00 — без отсечения. Шкала реранкера — 0…1; без "
                               "реранкера порог сравнивается с гибридным баллом, "
                               "у которого шкала выше единицы.")
    return rewrite, rerank, min_score


def _score_caption(record: dict) -> str:
    """Порог отсечения для метрики: ``None`` (отсечения не было) печатается прочерком."""
    min_score = record.get("min_score")
    return "—" if min_score is None else f"{float(min_score):.2f}"


def _token_total(tokens: dict) -> int:
    """Токены запроса и ответа вместе (0 — счётчика нет)."""
    return int(tokens.get("prompt_tokens") or 0) + int(tokens.get("completion_tokens") or 0)
