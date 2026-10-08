"""Раздел «⚙️ Оптимизация локальной LLM» (день 29): профили и кванты на кейсе RAG.

Кейс — ответы локальной модели по корпусу проекта: тот же поиск дня 22 (FAISS с диска
плюс sentence-transformers) и те же десять контрольных вопросов демо, что у разделов
«🧪 RAG-демо» и «🏠 Локальный RAG». Меняется только генерация: профиль настройки
(температура, окно контекста, предел ответа, системный промпт) и тег модели (квант).

Прогон идёт по одному варианту «профиль × модель» за запрос: четыре варианта — это
десятки минут локальной модели, и один запрос на всё не влез бы в предел ожидания и не
показывал бы прогресса. Варианты накапливаются в состоянии сессии, а сводку считает тот
же домен, что и бэкенд (``backend.domain.local_tuning_eval``): второго правила средних
и вердиктов в интерфейсе нет.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import local_tuning, local_tuning_eval, rag_mode

from . import api_client, common, llm_api, rag_api

#: Ключ состояния сессии: варианты прогона и снимок ресурсов последнего ответа.
TUNE_RESULT_KEY = "local_tune_variants"

#: Обрезка ответа в таблице (полный текст — в раскрывашках под ней).
ANSWER_CHARS = 160

#: Подпись пустой ячейки.
EMPTY = "—"


def render_local_tuning_section() -> None:
    """Раздел: подпись прогона, выбор моделей и профилей, кнопка и результаты."""
    st.title("⚙️ Оптимизация локальной LLM")
    st.caption("Кейс — ответы локальной модели по корпусу проекта (русский язык). "
               "Поиск по корпусу не меняется: сравнивается только генерация — профиль "
               "настройки (temperature, окно контекста, предел ответа, промпт) и тег "
               "модели (квант).")
    info = _provider_caption()
    config = _config_caption()
    if config is None:
        return
    labels = (info or {}).get("profile_labels") or dict(local_tuning.PROFILE_LABELS)
    models = st.text_input(
        "Модели Ollama (теги через запятую)",
        value=str((info or {}).get("local_model") or ""), key="local_tune_models",
        help="Второй тег — сравнение кванта: например "
             "qwen2.5-coder:14b-instruct-q3_K_M")
    profiles = st.multiselect(
        "Профили настройки", list(local_tuning.PROFILES),
        default=list(local_tuning.PROFILES),
        format_func=lambda name: labels.get(name, name), key="local_tune_profiles")
    top_k = st.slider("Фрагментов в контексте (top_k)", 1, int(config["top_k_max"]),
                      int(config["top_k_default"]), key="local_tune_top_k")
    if st.button("🚀 Прогнать сравнение профилей", type="primary", key="local_tune_run"):
        _run(_parse(models), list(profiles or local_tuning.PROFILES), top_k)
    _render_results()


def _provider_caption() -> dict | None:
    """Подпись о профиле по умолчанию и его параметрах; сбой — тоже подписью."""
    try:
        info = llm_api.api_llm_provider()
    except api_client.BackendError as exc:
        st.caption(f"Профиль: неизвестен (бэкенд недоступен: {exc.message})")
        return None
    labels = info.get("profile_labels") or {}
    active = str(info.get("local_profile") or "")
    st.caption(f"Профиль локального провайдера по умолчанию: "
               f"{labels.get(active, active) or EMPTY} · модель: "
               f"{info.get('local_model') or EMPTY} · temperature: "
               f"{info.get('local_temperature')} · num_ctx: {info.get('local_num_ctx')} · "
               f"предел ответа: {info.get('local_chat_max_tokens')} токенов")
    return info


def _config_caption() -> dict | None:
    """Лимиты режима и состояние корпуса; ошибка бэкенда — плашкой и ``None``."""
    try:
        config = rag_api.api_rag_config()
    except api_client.BackendError as exc:
        st.warning(f"Состояние корпуса RAG недоступно: {exc.message}")
        return None
    st.caption(f"Чанков в индексах: {int(config.get('chunks_total') or 0)} · стратегия "
               f"по умолчанию: {config.get('default_strategy') or EMPTY} · порог "
               f"релевантности: {float(config.get('relevance_threshold') or 0.0):g} "
               "(поиск у всех профилей один и тот же)")
    return config


def _parse(value: str) -> list:
    """Теги моделей из поля ввода: через запятую, пустые пропускаются."""
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _questions() -> list:
    """Тексты контрольных вопросов демо: те же, что у отчёта и разделов RAG."""
    try:
        payload = rag_api.api_rag_demo_questions() or {}
    except api_client.BackendError as exc:
        st.warning(f"Список демо-вопросов недоступен: {exc.message}")
        return []
    return [str(item.get("question") or "").strip()
            for item in (payload.get("questions") or [])
            if str(item.get("question") or "").strip()]


def _run(models: list, profiles: list, top_k: int) -> None:
    """Прогон по одному варианту за запрос; результат — в состояние сессии."""
    questions = _questions()
    if not questions or not models or not profiles:
        st.info("Нужны вопросы, хотя бы одна модель и хотя бы один профиль.")
        return
    pairs = [(model, name) for model in models for name in profiles]
    variants: list = []
    payload: dict = {}
    progress = st.progress(0.0, text=f"0/{len(pairs)}")
    for index, (model, name) in enumerate(pairs, start=1):
        caption = f"{index}/{len(pairs)}: {model} · {name}"
        progress.progress((index - 1) / len(pairs), text=caption)
        try:
            payload = llm_api.api_local_tune({"questions": questions, "models": [model],
                                              "profiles": [name], "top_k": top_k})
        except api_client.BackendError as exc:
            common.flash("error", f"Прогон прерван на {model} · {name}: {exc.message}")
            st.session_state.pop(TUNE_RESULT_KEY, None)
            st.rerun()
        variants.extend(payload.get("variants") or [])
        progress.progress(index / len(pairs), text=caption)
    st.session_state[TUNE_RESULT_KEY] = {"variants": variants, "payload": payload}
    st.rerun()


# ---------- отображение ----------
def _seconds(ms) -> float:
    """Время в секундах с двумя знаками (миллисекунды приходят целыми)."""
    return round(int(ms or 0) / 1000, 2)


def _short(text, limit: int = ANSWER_CHARS) -> str:
    """Ответ одной строкой таблицы: длинный текст обрезается многоточием."""
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else f"{value[:limit]}…"


def _rows_table(variants: list) -> list:
    """Строки прогона одной таблицей: профиль, вердикт, цитаты, опора, время, скорость."""
    return [{"Вопрос": row.get("question") or EMPTY,
             "Профиль": row.get("profile") or EMPTY,
             "Модель": row.get("model") or EMPTY,
             "Режим": row.get("mode") or EMPTY,
             "Вердикт": row.get("verdict") or EMPTY,
             "Цитаты": "да" if row.get("quotes_verified") else "нет",
             "Опора": "да" if row.get("grounding_ok") else "нет",
             "Ответ": _short(row.get("answer")),
             "Время, с": _seconds(row.get("duration_ms")),
             "Токенов/с": row.get("tokens_per_second") or 0.0,
             "Токенов вывода": row.get("completion_tokens") or 0}
            for variant in variants for row in (variant.get("rows") or [])]


def _variant_table(variants: list, pairs: list) -> list:
    """Сводка по вариантам: качество, время и вердикт пары «до/после»."""
    verdicts = {(pair.get("model"), pair.get("profile")): pair.get("verdict")
                for pair in pairs}
    return [{"Профиль": (variant.get("params") or {}).get("label") or EMPTY,
             "Модель": (variant.get("params") or {}).get("model") or EMPTY,
             "Вопросов": variant["summary"].get("questions", 0),
             "Совпало": variant["summary"].get("verdict_ok", 0),
             "Цитаты": variant["summary"].get("quotes_verified", 0),
             "Опора": variant["summary"].get("grounding_ok", 0),
             "Ср. время, с": _seconds(variant["summary"].get("avg_ms")),
             "Токенов/с": variant["summary"].get("avg_tokens_per_second", 0.0),
             "Вердикт пары": verdicts.get(((variant.get("params") or {}).get("model"),
                                           (variant.get("params") or {}).get("profile")),
                                          EMPTY)}
            for variant in variants]


def _resources_caption(variants: list, before: dict, version: str) -> str:
    """Ресурсы: версия Ollama, снимок до прогона и после каждого варианта."""
    parts = []
    if version:
        parts.append(f"Ollama {version}")
    parts.append(f"до прогона: VRAM {before.get('vram_mb', 0)} МБ, "
                 f"модель {before.get('total_mb', 0)} МБ")
    if before.get("error"):
        parts.append(f"снимок ресурсов: {before['error']}")
    for variant in variants:
        data = variant.get("resources") or {}
        first = (data.get("models") or [{}])[0]
        parts.append(f"{(variant.get('params') or {}).get('profile')}: "
                     f"VRAM {data.get('vram_mb', 0)} МБ, GPU "
                     f"{first.get('gpu_percent', 0.0)} %, окно "
                     f"{first.get('context_length', 0)}, прогрев "
                     f"{_seconds(data.get('load_ms'))} с, "
                     f"{data.get('tokens_per_second', 0.0)} токенов/с")
    return " · ".join(parts)


def _render_results() -> None:
    """Таблицы прогона и сводки, промпты до/после и полные ответы в раскрывашках."""
    stored = st.session_state.get(TUNE_RESULT_KEY)
    if not stored:
        st.info("Нажмите «🚀 Прогнать сравнение профилей»: каждый вариант прогонит "
                "контрольные вопросы через локальную модель. Первый запрос грузит веса "
                "(~30–60 с), дальше вопрос идёт 3–10 с, — поэтому прогон идёт по "
                "варианту за запрос, а полный прогон занимает десятки минут.")
        return
    variants = stored.get("variants") or []
    payload = stored.get("payload") or {}
    summary = local_tuning_eval.summary(variants)
    st.markdown(f"**Результат прогона: {len(variants)} вариантов** · лучший: "
                f"{summary['best'] or EMPTY} · суммарно "
                f"{_seconds(summary['total_ms'])} с ответов модели")
    st.caption(_resources_caption(variants, payload.get("ps_before") or {},
                                 str(payload.get("ollama_version") or "")))
    st.dataframe(_rows_table(variants), width="stretch", hide_index=True)
    st.dataframe(_variant_table(variants, summary["pairs"]), width="stretch",
                 hide_index=True)
    for pair in summary["pairs"]:
        st.caption(f"Вердикт пары {pair['model']}: {pair['verdict']} · разница "
                   f"совпавших строк {pair['quality_delta']:+d} · ускорение "
                   f"{pair['speedup']}×")
    _render_prompts()
    for variant in variants:
        _render_variant(variant)


def _render_prompts() -> None:
    """Промпт до и после оптимизации: видно, что именно изменилось в инструкции."""
    with st.expander("Промпт: до и после"):
        st.markdown("**До оптимизации (`rag_mode.RAG_SYSTEM_PROMPT`, день 26)**")
        st.code(rag_mode.RAG_SYSTEM_PROMPT)
        st.markdown("**После оптимизации (`local_tuning.LOCAL_TUNED_RAG_PROMPT`)**")
        st.code(local_tuning.LOCAL_TUNED_RAG_PROMPT)


def _render_variant(variant: dict) -> None:
    """Полные ответы варианта: источники, цитаты и предупреждения каждой строки."""
    params = variant.get("params") or {}
    with st.expander(f"{params.get('label') or EMPTY} · {params.get('model') or EMPTY} "
                     f"({variant['summary'].get('questions', 0)} вопросов)"):
        for index, row in enumerate(variant.get("rows") or [], start=1):
            st.markdown(f"**{index}. {row.get('question') or EMPTY}** · "
                        f"{row.get('mode') or EMPTY} · {row.get('verdict') or EMPTY} · "
                        f"{_seconds(row.get('duration_ms'))} с · "
                        f"{row.get('tokens_per_second') or 0.0} токенов/с")
            st.markdown(common.esc(row.get("answer") or EMPTY))
            st.caption(_sources(row.get("sources") or []))
            if row.get("warning"):
                st.warning(row["warning"])


def _sources(sources: list) -> str:
    """Источники строки одной строкой: ``источник · раздел`` на каждый фрагмент."""
    if not sources:
        return "Источников нет"
    return " · ".join(f"{item.get('source') or EMPTY} · {item.get('section') or EMPTY}"
                      for item in sources)
