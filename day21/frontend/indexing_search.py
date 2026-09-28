"""Форма ручного поиска по индексу документов (день 21).

Отдельный модуль, потому что это единственная часть раздела, которая работает БЕЗ
прогона: индекс уже построен, и вопрос к нему задаётся вручную. Так видно, что
найденное — это не «специально подобранные запросы демо», а обычный поиск.

Запрос уходит в бэкенд целиком (``GET /indexing/search``): кодирование запроса
моделью, поиск по FAISS и подстановка метаданных живут там, и повторять их здесь
нельзя — иначе интерфейс и API отвечали бы по-разному.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, indexing_api

#: Подписи стратегий (значения домена: frontend не импортирует backend).
STRATEGY_LABELS = {"fixed": "fixed — окно по токенам", "structural": "structural — по секциям"}

#: Границы топ-k: верхняя совпадает с лимитом бэкенда (``INDEX_MAX_TOP_K``).
MIN_TOP_K = 1
MAX_TOP_K = 20
DEFAULT_TOP_K = 5


def render_search() -> None:
    """Форма поиска: запрос, стратегия, топ-k и таблица попаданий."""
    st.markdown("**Поиск по индексу**")
    columns = st.columns([3, 2, 1])
    with columns[0]:
        query = st.text_input("Запрос", value="переходы состояния задачи",
                              key="index_query")
    with columns[1]:
        strategy_label = st.selectbox("Стратегия", list(STRATEGY_LABELS),
                                      key="index_query_strategy")
    with columns[2]:
        top_k = st.slider("Топ-k", MIN_TOP_K, MAX_TOP_K, DEFAULT_TOP_K,
                          key="index_query_top_k")
    if not st.button("🔎 Найти", key="index_query_go"):
        return
    strategy = STRATEGY_LABELS[strategy_label]
    try:
        report = indexing_api.api_indexing_search(query, top_k=top_k,
                                                  strategy=strategy)
    except api_client.BackendError as exc:
        st.warning(f"Поиск не выполнен: {exc.message}")
        return
    results = report.get("results") or []
    if not results:
        st.info("Ничего не найдено: попробуйте другой запрос или другую стратегию.")
        return
    st.caption(
        f"Стратегия {report.get('strategy')} · топ-{report.get('top_k')} · "
        f"найдено {report.get('count')}"
    )
    st.dataframe([_hit_row(hit) for hit in results], width="stretch", hide_index=True)
    for hit in results:
        with st.expander(
            f"#{hit.get('rank')} · {hit.get('source')} · "
            f"{hit.get('section') or '—'} · оценка {hit.get('score')}"
        ):
            st.caption(
                f"{hit.get('chunk_id')} · {hit.get('token_count', 0)} токенов · "
                f"символы {hit.get('start_char')}–{hit.get('end_char')}"
            )
            st.code(hit.get("content") or "", language=None)


def _hit_row(hit: dict) -> dict:
    """Строка попадания для таблицы интерфейса."""
    return {
        "ранг": hit.get("rank"),
        "оценка": hit.get("score"),
        "документ": hit.get("source"),
        "заголовок": hit.get("title"),
        "секция": hit.get("section") or "—",
        "токенов": hit.get("token_count"),
    }
