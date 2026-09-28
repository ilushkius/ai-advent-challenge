"""Раздел сравнения стратегий (день 21): таблица метрик, гистограммы, примеры.

Всё, что показывает РАЗНИЦУ между стратегиями, живёт здесь отдельным модулем:
таблица метрик прогона, распределение размеров чанков, примеры чанков одного и
того же документа под двумя стратегиями и результаты пяти тестовых запросов.
Раздел «📦 Индексация» только собирает страницу и зовёт ``render_comparison`` —
иначе он вышел бы за лимит 400 строк (та же причина, по которой подписи
оркестрации дня 20 живут в ``orchestration_steps.py``).

Данные приходят уже посчитанными: таблица — из ``metrics["comparison"]`` прогона
(её строки собирает домен ``index_metrics.comparison_rows``), гистограмма — из
``GET /indexing/stats``, примеры чанков и попадания — из API. Никакая арифметика
метрик в интерфейсе не повторяется.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, indexing_api

#: Сколько примеров чанков и попаданий показывать (больше — в отчёт, не на экран).
CHUNK_SAMPLES = 5
TOP_HITS = 3

#: Подписи бакетов гистограммы в порядке домена (ключи приходят из метрик).
BUCKET_ORDER = ("0-128", "129-256", "257-384", "385-512", "513+")

#: Подписи стратегий (значения домена: frontend не импортирует backend).
STRATEGY_LABELS = {"fixed": "fixed — окно по токенам", "structural": "structural — по секциям"}


def render_comparison(report: dict, stats: dict) -> None:
    """Таблица сравнения, гистограммы, примеры чанков и результаты запросов."""
    metrics = report.get("metrics") or {}
    st.subheader("Сравнение стратегий")
    rows = metrics.get("comparison") or []
    if rows:
        st.dataframe(rows[1:], width="stretch", hide_index=True,
                     column_config={
                         0: "метрика", 1: "fixed", 2: "structural", 3: "комментарий",
                     })
        st.caption(
            "Числа — из прогона: покрытие считается по объединению интервалов чанков "
            "(перекрытие окон не удваивается), precision@k и recall@k — по пяти "
            "тестовым запросам и ожидаемым источникам из домена."
        )
    else:
        st.info("Метрик сравнения нет: их считает демо-прогон, а не одиночная стратегия.")
    _render_histograms(stats)
    _render_samples()
    _render_queries(metrics)


def _render_histograms(stats: dict) -> None:
    """Распределение размеров чанков по бакетам: два графика рядом."""
    fixed = (stats.get("fixed") or {}).get("histogram") or {}
    structural = (stats.get("structural") or {}).get("histogram") or {}
    if not fixed and not structural:
        st.caption("Гистограмма появится после первой индексации.")
        return
    columns = st.columns(2)
    with columns[0]:
        st.markdown("**fixed: размеры чанков (токенов)**")
        st.bar_chart(_chart_rows(fixed), x="бакет", y="чанков", height=220)
    with columns[1]:
        st.markdown("**structural: размеры чанков (токенов)**")
        st.bar_chart(_chart_rows(structural), x="бакет", y="чанков", height=220)


def _chart_rows(histogram: dict) -> list[dict]:
    """Строки графика в порядке бакетов (незнакомый бакет дописывается в конец)."""
    order = [bucket for bucket in BUCKET_ORDER if bucket in histogram]
    order += [bucket for bucket in histogram if bucket not in BUCKET_ORDER]
    return [{"бакет": bucket, "чанков": int(histogram.get(bucket) or 0)}
            for bucket in order]


def _render_samples() -> None:
    """Примеры первых чанков каждой стратегии: чем они отличаются на одном документе."""
    st.markdown("**Примеры чанков**")
    columns = st.columns(2)
    for column, strategy in zip(columns, STRATEGY_LABELS):
        with column:
            st.caption(STRATEGY_LABELS[strategy])
            payload = _load(lambda s=strategy: indexing_api.api_indexing_chunks(
                s, CHUNK_SAMPLES), "Примеры чанков недоступны")
            chunks = (payload or {}).get("chunks") or []
            if not chunks:
                st.info("Чанков нет — выполните индексацию.")
                continue
            for chunk in chunks:
                section = chunk.get("section") or "—"
                with st.expander(
                    f"{chunk.get('source')} · {section} · "
                    f"{chunk.get('token_count', 0)} токенов"
                ):
                    st.caption(
                        f"{chunk.get('chunk_id')} · символов: "
                        f"{chunk.get('end_char', 0) - chunk.get('start_char', 0)} "
                        f"({chunk.get('start_char')}–{chunk.get('end_char')})"
                    )
                    preview = chunk.get("content") or ""
                    st.code(preview[:600] + ("…" if len(preview) > 600 else ""),
                            language=None)


def _render_queries(metrics: dict) -> None:
    """Результаты пяти тестовых запросов: что нашла каждая стратегия."""
    queries = metrics.get("queries") or []
    st.markdown("**Тестовые запросы (ground truth — ожидаемые источники)**")
    if not queries:
        st.caption("Результаты запросов появятся после демо-прогона.")
        return
    for entry in queries:
        expected = ", ".join(entry.get("expected_sources") or []) or "—"
        with st.expander(f"❓ {entry.get('query')} · ожидалось: {expected}"):
            if entry.get("note"):
                st.caption(entry["note"])
            for strategy in STRATEGY_LABELS:
                block = entry.get(strategy) or {}
                hits = (block.get("hits") or [])[:TOP_HITS]
                st.markdown(
                    f"*{strategy}* — релевантных чанков в индексе: "
                    f"{block.get('relevant_total', 0)}"
                )
                if not hits:
                    st.caption("попаданий нет")
                    continue
                st.dataframe([_hit_row(hit) for hit in hits], width="stretch",
                             hide_index=True)


def _hit_row(hit: dict) -> dict:
    """Строка попадания для таблицы интерфейса."""
    return {
        "ранг": hit.get("rank"),
        "оценка": hit.get("score"),
        "документ": hit.get("source"),
        "секция": hit.get("section") or "—",
        "токенов": hit.get("token_count"),
    }


def _load(call, failure: str) -> dict | None:
    """Запрос к бэкенду; ошибка — плашкой и ``None`` (без падения страницы)."""
    try:
        return call()
    except api_client.BackendError as exc:
        st.warning(f"{failure}: {exc.message}")
        return None
