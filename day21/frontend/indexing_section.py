"""Раздел «📦 Индексация» дня 21: демо одной кнопкой, прогресс, история, поиск.

Индексация живёт в процессе бэкенда: Streamlit её только запускает и показывает.
Прогон идёт в фоновом потоке (модель считает эмбеддинги десятками секунд), поэтому
прогресс читается фрагментом с ``run_every="1s"``: страница не держит прогон у
себя, а подтягивает его след из ``GET /indexing/status`` — запуск, сделанный из
скрипта или из теста, виден здесь же, если он последний.

Что здесь есть:

* большая кнопка «🚀 Запустить демо-индексацию» — тот же путь, что у CLI-прогона и
  теста (обе стратегии, пять тестовых запросов, метрики сравнения);
* прогресс активного запуска: полоса этапа (загрузка → чанкинг → эмбеддинги →
  индекс → поиск → сравнение), подпись этапа и счётчики документов, чанков и
  эмбеддингов;
* сравнение стратегий (``frontend/indexing_compare.py``): таблица метрик,
  гистограммы размеров чанков, примеры чанков и результаты тестовых запросов;
* форма ручного поиска (``frontend/indexing_search.py``) — вопрос к уже
  построенному индексу, без запуска прогона;
* история запусков и очистка индекса: очистка нужна потому, что прогон индекс
  ДОПИСЫВАЕТ, а не перестраивает.

Данные тянутся только через ``frontend/indexing_api.py``: правила прогона живут на
бэкенде, и раскладывать их по интерфейсу нельзя.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, indexing_api, indexing_compare, indexing_search

#: Подписи этапов прогона (копия значений ``IndexingState``: frontend не импортирует
#: backend) и «ширина» полосы прогресса на каждом этапе.
STAGE_LABELS = {
    "loading": "загрузка документов",
    "chunking": "чанкинг документа",
    "embedding": "расчёт эмбеддингов",
    "indexing": "запись индекса",
    "searching": "поиск по индексу",
    "comparing": "сравнение стратегий",
    "completed": "завершено",
    "failed": "ошибка",
}

#: Периоды опроса: прогресс — раз в секунду (его видно глазами), история — реже.
POLL_RUN_SECONDS = "1s"
POLL_HISTORY_SECONDS = "5s"

#: Значения стратегий (копия ``ChunkStrategy``: см. выше).
STRATEGIES = ("fixed", "structural")

#: Ключ состояния сессии, в котором лежит номер запуска, по которому считалось сравнение.
REPORT_KEY = "index_report_ready"


def render_indexing_section() -> None:
    """Раздел «📦 Индексация»: кнопка демо, прогресс, сравнение, поиск, история."""
    st.title("📦 Индексация документов")
    st.caption(
        "Документы режутся на чанки двумя стратегиями: **fixed** — окнами по 512 "
        "токенов с перекрытием 50, **structural** — по заголовкам markdown, "
        "секциям кода (top-level def/class) и абзацам. Эмбеддинги считает "
        "sentence-transformers и кладёт в FAISS, метаданные чанков — в SQLite "
        "(document_chunks), журнал прогонов — в index_runs. Документы собираются "
        "из источников репозитория автоматически: папку documents/ готовить не нужно."
    )
    _render_actions()
    st.divider()
    _render_progress()
    st.divider()
    _render_search()
    st.divider()
    _render_history()


# ---------- действия ----------
def _render_actions() -> None:
    """Кнопка демо-прогона и вспомогательные действия (одна стратегия, очистка)."""
    columns = st.columns([2, 3])
    with columns[0]:
        if st.button("🚀 Запустить демо-индексацию", type="primary",
                     key="index_start_demo"):
            _start(indexing_api.api_indexing_demo, "Демо-индексация")
    with columns[1]:
        with st.expander("Только одна стратегия и очистка индекса"):
            st.caption(
                "Прогон ДОПИСЫВАЕТ индекс: чтобы перестроить его с нуля после "
                "изменения документов, сначала очистите индекс."
            )
            for strategy in STRATEGIES:
                if st.button(f"Индексировать {strategy}",
                             key=f"index_run_{strategy}"):
                    _start(lambda s=strategy: indexing_api.api_indexing_run(s),
                           f"Индексация {strategy}")
            if st.button("🧹 Очистить обе стратегии", key="index_clear"):
                _start(lambda: indexing_api.api_indexing_clear("all"),
                       "Очистка индекса")


def _start(call, title: str) -> None:
    """Запускает прогон; номер запуска кладётся в состояние сессии для опроса."""
    try:
        report = call()
    except api_client.BackendError as exc:
        common.flash("error", f"{title} не запущена: {exc.message}")
    else:
        st.session_state[REPORT_KEY] = report.get("run_id")
        common.flash("success",
                     f"{title}: запуск №{report.get('run_id')} "
                     f"({report.get('status')})")
    st.rerun()


# ---------- прогресс ----------
@st.fragment(run_every=POLL_RUN_SECONDS)
def _render_progress() -> None:
    """Прогресс последнего запуска и сравнение стратегий по его окончании."""
    payload = _load(indexing_api.api_indexing_status, "Статус индексации недоступен")
    if payload is None:
        return
    run = payload.get("run")
    st.subheader("Прогон индексации")
    if not run:
        st.info("Прогонов ещё не было. Нажмите «🚀 Запустить демо-индексацию».")
        return
    status = str(run.get("status") or "")
    st.progress(stage_progress(run), text=f"Этап: {STAGE_LABELS.get(status, status)}")
    st.markdown(
        f"Запуск №{run.get('id')} · стратегия {run.get('strategy')} · "
        f"**{STAGE_LABELS.get(status, status)}**"
    )
    st.caption(
        f"документы {run.get('documents_done', 0)}/{run.get('documents_total', 0)} · "
        f"чанков fixed/structural: {run.get('chunks_fixed', 0)}/"
        f"{run.get('chunks_structural', 0)} · "
        f"эмбеддингов {run.get('embeddings_done', 0)}/"
        f"{run.get('embeddings_total', 0)}"
    )
    if run.get("error"):
        st.error(f"Прогон остановлен: {run['error']}")
    if status in ("completed", "failed"):
        _render_report(run.get("id"))


def stage_progress(run: dict) -> float:
    """Доля готовности прогона по его этапу (кусочно-линейная шкала).

    Этапы идут не равномерно по времени: расчёт эмбеддингов занимает основную часть
    прогона, поэтому у ``embedding`` своя полоса (0.40–0.80), которая заполняется по
    счётчику эмбеддингов — иначе полоса стояла бы на месте почти всё время.
    """
    status = str(run.get("status") or "")
    if status == "loading":
        return 0.10
    if status == "chunking":
        return 0.35
    if status == "embedding":
        total = int(run.get("embeddings_total") or 0)
        done = int(run.get("embeddings_done") or 0)
        return 0.40 + 0.40 * (done / total if total else 0.0)
    if status == "indexing":
        return 0.85
    if status == "searching":
        return 0.90
    if status == "comparing":
        return 0.95
    if status in ("completed", "failed"):
        return 1.0
    return 0.0


def _render_report(run_id) -> None:
    """Сравнение стратегий по завершённому запуску (метрики, графики, запросы)."""
    detail = _load(lambda: indexing_api.api_indexing_run_detail(run_id),
                   "Отчёт о запуске недоступен")
    if detail is None:
        return
    stats = _load(indexing_api.api_indexing_stats, "Статистика недоступна") or {}
    indexing_compare.render_comparison(detail, stats)


# ---------- поиск ----------
def _render_search() -> None:
    """Форма ручного поиска по построенному индексу."""
    indexing_search.render_search()


# ---------- история ----------
@st.fragment(run_every=POLL_HISTORY_SECONDS)
def _render_history() -> None:
    """История запусков индексации и детали выбранного запуска."""
    st.subheader("История запусков")
    payload = _load(indexing_api.api_indexing_runs, "История запусков недоступна")
    if payload is None:
        return
    runs = payload.get("runs") or []
    if not runs:
        st.caption("Запусков пока нет.")
        return
    st.dataframe([_run_row(run) for run in runs], width="stretch", hide_index=True)
    labels = {f"№{run['id']} · {run['strategy']} · "
              f"{STAGE_LABELS.get(run['status'], run['status'])}": run["id"]
              for run in runs}
    chosen = st.selectbox("Детали запуска", list(labels), key="index_history_run")
    run_id = labels[chosen]
    detail = _load(lambda: indexing_api.api_indexing_run_detail(run_id),
                   "Детали запуска недоступны")
    if detail is None:
        return
    metrics = detail.get("metrics") or {}
    if not metrics:
        st.caption("Метрик у этого запуска нет: их считает демо-прогон.")
        return
    documents = metrics.get("documents") or []
    st.caption(f"модель: {metrics.get('embedding_model') or '—'} · "
               f"документов: {len(documents)} · "
               f"символов: {common.fmt_int(metrics.get('documents_total_chars', 0))}")
    rows = metrics.get("comparison") or []
    if rows:
        st.dataframe(rows[1:], width="stretch", hide_index=True)
    if st.button("🧹 Очистить обе стратегии", key=f"index_clear_{run_id}"):
        _start(lambda: indexing_api.api_indexing_clear("all"), "Очистка индекса")


def _run_row(run: dict) -> dict:
    """Строка таблицы истории (подписи интерфейса, а не значения API)."""
    return {
        "№": run.get("id"),
        "дата": common.fmt_time(run.get("started_at")),
        "стратегия": run.get("strategy"),
        "статус": STAGE_LABELS.get(run.get("status"), run.get("status")),
        "документы": f"{run.get('documents_done')}/{run.get('documents_total')}",
        "чанки fixed/structural": f"{run.get('chunks_fixed')}/"
                                  f"{run.get('chunks_structural')}",
        "эмбеддинги": f"{run.get('embeddings_done')}/{run.get('embeddings_total')}",
        "длительность, мс": run.get("duration_ms"),
        "ошибка": run.get("error") or "",
    }


# ---------- общее ----------
def _load(call, failure: str) -> dict | None:
    """Запрос к бэкенду; ошибка — плашкой и ``None`` (без падения страницы)."""
    try:
        return call()
    except api_client.BackendError as exc:
        st.warning(f"{failure}: {exc.message}")
        return None


def indexing_note(report: dict) -> str:
    """Строка «📦 Индексация: …» для сводки хода (``""`` — поиска не было)."""
    if not report or not report.get("detected"):
        return ""
    if report.get("error"):
        return f"📦 Индексация: ошибка поиска — {report['error']}"
    hits = int(report.get("hits") or 0)
    tail = "в промпте" if report.get("used_in_prompt") else "без промпта"
    sources = report.get("sources") or []
    suffix = f" ({', '.join(str(item) for item in sources[:2])})" if sources else ""
    return (f"📦 Индексация: {report.get('strategy') or '—'} — {hits} "
            f"{common.plural(hits, 'фрагмент', 'фрагмента', 'фрагментов')} "
            f"{tail}{suffix}")
