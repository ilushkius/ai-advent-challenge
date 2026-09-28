"""Вкладка «💰 Расходы» (день 21): сколько стоит работа агентов и что её удешевляет.

Что здесь видно и зачем:

* **пик или непик сейчас** — по этому окну планировщик ставит тяжёлые задачи
  (`prefer_off_peak`), и здесь же показан прогноз экономии, если задача уедет в
  дешёвое окно;
* **кэш контекста** — доля ввода, который DeepSeek отдал из префиксного кэша, и
  статистика стабильных префиксов промпта: сколько раз префикс собирался заново, а
  сколько раз взят из кэша приложения;
* **сжатие промптов** — сколько токенов снято с динамической части;
* **расход по дням** — график по журналу `llm_usage`;
* **последние запросы** — таблица с моделью, типом задачи, токенами и раздельно
  `cache_hit`/`cache_miss` (именно по ней видно, работает ли кэш);
* **маршрутизация моделей** — какая модель и какой предел длины ответа выбраны
  каждому типу задачи.

Числа приходят из API (``frontend/cost_api.py``): формулы стоимости и доля кэша
считаются в домене дня, чтобы вкладка и отчёт не расходились.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, cost_api

#: Периоды агрегации (значение → подпись в интерфейсе).
PERIODS = {
    "За сутки": "day",
    "За неделю": "week",
    "За месяц": "month",
    "За всё время": "all",
}

#: Сколько последних запросов показывать в таблице (больше — в отчёте и API).
RECENT_LIMIT = 25

#: Подписи типов задач: значения те же, что в конфиге бэкенда.
TASK_LABELS = {
    "chat": "ответ в диалоге",
    "summarize": "конспект истории",
    "classify": "проверка инвариантов",
    "keywords": "ключевые слова и факты",
    "orchestration": "план оркестрации",
    "code": "длинная генерация",
    "indexing": "пакетная обработка",
}


def render_cost_section() -> None:
    """Вкладка «💰 Расходы»: состояние рычагов, статистика, график и журнал."""
    st.title("💰 Расходы на LLM")
    st.caption(
        "Каждый запрос к модели пишется в журнал `llm_usage`: модель, тип задачи, "
        "токены ввода и вывода и **раздельно попадания и промахи кэша контекста**. "
        "Экономию дают четыре рычага: кэш стабильного префикса промпта, сжатие "
        "динамической части, предел длины ответа и непиковые часы DeepSeek."
    )
    status = _load(cost_api.api_llm_status, "Состояние оптимизации недоступно")
    period_label = st.selectbox("Период", list(PERIODS), index=1, key="cost_period")
    usage = _load(lambda: cost_api.api_llm_usage(period=PERIODS[period_label]),
                  "Журнал расходов недоступен")
    if status:
        _render_peak(status)
    if usage:
        _render_totals(usage.get("stats") or {}, status or {})
        _render_daily(usage.get("stats") or {})
    if status:
        _render_prompt_cache(status)
    if usage:
        _render_requests(usage.get("requests") or [])
    if status:
        _render_routing(status)


# ---------- рычаг 1: непиковые часы ----------
def _render_peak(status: dict) -> None:
    """Пик/непик, окно и прогноз экономии на переносе тяжёлых задач."""
    st.subheader("Непиковые часы DeepSeek")
    discount = int(status.get("discount_percent") or 0)
    columns = st.columns([2, 3])
    with columns[0]:
        if status.get("off_peak"):
            st.success(f"🌙 Непик — скидка провайдера ~{discount}%")
        else:
            st.warning("⚡ Пик — тяжёлые задачи лучше отложить")
        st.caption(status.get("description") or "")
    with columns[1]:
        next_moment = status.get("next_off_peak")
        if status.get("off_peak"):
            st.metric("Следующее дешёвое окно", "уже идёт",
                      help=f"Текущее окно: {status.get('window_label') or '—'}")
        else:
            st.metric("Следующее дешёвое окно",
                      common.fmt_time(next_moment) or "—",
                      help=f"Через {int(status.get('next_off_peak_in_seconds') or 0)} с")
        st.caption(
            "Тяжёлые задачи (сводки, индексация, пакетная обработка) ставятся с "
            "флагом `prefer_off_peak`: планировщик переносит первый запуск в ближайшее "
            "дешёвое окно."
        )


# ---------- рычаги 2–4: токены, кэш и стоимость ----------
def _render_totals(stats: dict, status: dict) -> None:
    """Итоги периода: токены, доля кэша, стоимость и прогноз экономии."""
    st.subheader("Итоги периода")
    columns = st.columns(4)
    columns[0].metric("Запросов", common.fmt_int(stats.get("requests") or 0))
    columns[1].metric("Токенов", common.fmt_int(stats.get("total_tokens") or 0),
                      help="ввод + вывод")
    columns[2].metric("Кэш контекста", f"{float(stats.get('cache_hit_percent') or 0):.1f}%",
                      help="доля ввода, взятого из кэша: попадание дешевле обычного ввода")
    columns[3].metric("Оценка стоимости", f"${float(stats.get('cost_estimate') or 0):.6f}")
    if not stats.get("requests"):
        st.info("За период записей нет: сделайте ход в чате или запустите демонстрацию.")
        return
    _render_forecast(stats, status)


def _render_forecast(stats: dict, status: dict) -> None:
    """Прогноз экономии: расчёт «сейчас» и «если перенести в непик» рядом."""
    models = _load(cost_api.api_llm_models, "Тарифы недоступны") or {}
    model = (models.get("default_model") or "deepseek-chat")
    prompt_tokens = int(stats.get("prompt_tokens") or 0)
    saved = int((status.get("compressor") or {}).get("saved_tokens") or 0)
    now = _load(lambda: cost_api.api_llm_estimate(
        model, "chat", prompt_tokens, int(stats.get("completion_tokens") or 0),
        int(stats.get("cache_hit_tokens") or 0), saved, 0, 0.0), "Прогноз недоступен")
    if not now:
        return
    off = _load(lambda: cost_api.api_llm_estimate(
        model, "chat", prompt_tokens, int(stats.get("completion_tokens") or 0),
        int(stats.get("cache_hit_tokens") or 0), saved, 0, 1.0), "Прогноз недоступен")
    columns = st.columns([4, 1, 1])
    with columns[0]:
        st.markdown(
            f"**Экономия измеряемых рычагов: {now['core_saving_percent']}%** "
            f"(кэш ${now['cache']['saving']:.6f} + сжатие ${now['compression']['saving']:.6f})"
        )
        if off:
            st.caption(
                f"Если бы весь период шёл в непиковые часы, экономия была бы "
                f"{off['core_saving_percent']}% (скидка {discount_text(status)})."
            )
    columns[1].metric("Без оптимизации", f"${now['baseline_cost']:.6f}")
    columns[2].metric("С оптимизацией", f"${now['cost']:.6f}")


def discount_text(status: dict) -> str:
    """Скидка словами (используется в подписи прогноза)."""
    return f"{int(status.get('discount_percent') or 0)}%"


def _render_daily(stats: dict) -> None:
    """График расхода токенов по дням (из журнала)."""
    daily = stats.get("daily") or []
    st.subheader("Расход по дням")
    if not daily:
        st.caption("Данных по дням нет: журнал пока пуст.")
        return
    st.bar_chart([{"дата": item.get("date"), "токенов": int(item.get("total_tokens") or 0)}
                  for item in daily], x="дата", y="токенов", height=240)
    st.dataframe(
        [{
            "дата": item.get("date"),
            "запросов": item.get("requests"),
            "токенов": item.get("total_tokens"),
            "кэш-хитов": item.get("cache_hit_tokens"),
            "кэш-промахов": item.get("cache_miss_tokens"),
            "стоимость, $": item.get("cost_estimate"),
        } for item in daily],
        width="stretch", hide_index=True,
    )


# ---------- кэш префиксов и сжатие ----------
def _render_prompt_cache(status: dict) -> None:
    """Статистика стабильного префикса промптов и сжатия динамической части."""
    st.subheader("Кэш промптов и сжатие")
    prompt = status.get("prompt") or {}
    compressor = status.get("compressor") or {}
    columns = st.columns(4)
    columns[0].metric("Префикс из кэша приложения",
                      f"{float(prompt.get('cache_hit_percent') or 0):.1f}%",
                      help="сколько сборок промпта переиспользовали готовый стабильный префикс")
    columns[1].metric("Попаданий / промахов",
                      f"{common.fmt_int(prompt.get('cache_hits') or 0)} / "
                      f"{common.fmt_int(prompt.get('cache_misses') or 0)}")
    columns[2].metric("Токенов снято сжатием",
                      common.fmt_int(compressor.get("saved_tokens") or 0),
                      help="динамическая часть промпта после сжатия")
    columns[3].metric("Стабильный префикс, токенов",
                      common.fmt_int(prompt.get("stable_tokens") or 0),
                      help="его сервер отдаёт из кэша контекста")
    st.caption(
        "Стабильный префикс — профиль, системный промпт, инварианты, каталог "
        "инструментов и примеры. Он не сжимается и не меняется между запросами: "
        "именно поэтому сервер DeepSeek может отдать его из кэша. Динамическая часть "
        "(память, факты, состояние задачи, результаты инструментов) сжимается."
    )


# ---------- журнал ----------
def _render_requests(requests: list) -> None:
    """Таблица последних запросов: видно, где кэш сработал, а где нет."""
    st.subheader("Последние запросы")
    if not requests:
        st.caption("Записей ещё нет.")
        return
    st.dataframe([_request_row(item) for item in requests[:RECENT_LIMIT]],
                 width="stretch", hide_index=True)
    st.caption(
        "`cache_hit` — токены ввода, отданные из кэша контекста (дешевле), "
        "`cache_miss` — по полной цене. Запросы без полей кэша (старые сборки API) "
        "считаются полностью промахнувшимися, чтобы доля попаданий не завышалась."
    )


def _request_row(row: dict) -> dict:
    """Строка журнала для таблицы (подписи интерфейса, а не значения API)."""
    return {
        "когда": common.fmt_time(row.get("timestamp")),
        "агент": (row.get("agent_id") or "—"),
        "тип": TASK_LABELS.get(row.get("request_type"), row.get("request_type")),
        "модель": row.get("model"),
        "ввод": row.get("prompt_tokens"),
        "cache_hit": row.get("cache_hit_tokens"),
        "cache_miss": row.get("cache_miss_tokens"),
        "вывод": row.get("completion_tokens"),
        "стоимость, $": row.get("cost_estimate"),
    }


# ---------- маршрутизация моделей ----------
def _render_routing(status: dict) -> None:
    """Таблица «тип задачи → модель и предел длины ответа»."""
    st.subheader("Модель и предел ответа по типу задачи")
    models = status.get("task_models") or {}
    limits = status.get("task_max_tokens") or {}
    if not models:
        return
    st.dataframe(
        [{
            "тип задачи": TASK_LABELS.get(kind, kind),
            "ключ": kind,
            "модель": model,
            "предел ответа, токенов": limits.get(kind, "—"),
        } for kind, model in models.items()],
        width="stretch", hide_index=True,
    )
    st.caption(
        "Простые задачи (сводка, классификация, ключевые слова) идут на дешёвую "
        "модель, сложные (план оркестрации, длинная генерация, пакетная обработка) — "
        "на основную. Таблица — те же данные конфига, по которым работает `LLMClient`."
    )


def cost_note(record: dict) -> str:
    """Строка «💰 LLM: …» для сводки хода (``""`` — вызова не было)."""
    llm = record.get("llm") or {}
    if not llm:
        return ""
    percent = float(llm.get("cache_hit_percent") or 0)
    return (f"💰 LLM: {llm.get('model') or '—'} · "
            f"{common.fmt_int(llm.get('prompt_tokens') or 0)} ввод "
            f"(кэш {percent:.0f}%) · {common.fmt_int(llm.get('completion_tokens') or 0)} "
            f"вывод · ${float(llm.get('cost_estimate') or 0):.6f}")


def _load(call, failure: str) -> dict | None:
    """Запрос к бэкенду; ошибка — плашкой и ``None`` (без падения страницы)."""
    try:
        return call()
    except api_client.BackendError as exc:
        st.warning(f"{failure}: {exc.message}")
        return None
