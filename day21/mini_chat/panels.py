"""Разметка мини-чата дня 25: ход диалога, источники и цитаты, панель памяти задачи.

Приложение отдельное от песочницы: вкладок, инвариантов, MCP и планировщика здесь нет —
только чат, разбор ответа (источники, цитаты, предупреждения) и память задачи.

Состояние страницы лежит в ``st.session_state``: ``mc_session`` (сессия бэкенда),
``mc_messages`` (ход диалога как он показан) и ``mc_memory`` (последняя память задачи).
Сессия открывается на отрисовке боковой панели, а не в области чата: панель памяти
читает её же, и разойтись им нельзя.

Ни одного вызова ``st.*`` на уровне модуля: разметка собирается при отрисовке страницы.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import llm_provider

from . import api

#: Режим ответа человеческими словами: подпись под источниками и предупреждения.
_MODE_LABELS = {"rag": "ответ по корпусу", "dont_know": "не знаю",
                "error": "ошибка модели"}
#: Ключи состояния страницы: сессия, ход диалога, последняя память задачи.
_SESSION_KEY = "mc_session"
_MESSAGES_KEY = "mc_messages"
_MEMORY_KEY = "mc_memory"


def render_sidebar() -> None:
    """Боковая панель: сессия, ``top_k``, показ цитат и панель «Память задачи»."""
    st.sidebar.title("💬 Мини-чат")
    st.sidebar.caption("Отдельное приложение дня 25: поиск по корпусу плюс память "
                       "задачи.")
    if st.sidebar.button("✨ Новая сессия", key="mc_new_session", width="stretch"):
        _start_new_session()
    session = ensure_session()
    # Провайдер ответа (день 26): ключ свой (`mc_provider`), а не общий с основной
    # песочницей — приложения независимы, и общее значение путало бы два радио.
    st.sidebar.subheader("🤖 Провайдер ответа")
    st.sidebar.radio("Провайдер ответа", list(llm_provider.PICKER_PROVIDERS),
                     format_func=llm_provider.label, label_visibility="collapsed",
                     key="mc_provider")
    st.sidebar.slider("Фрагментов в контексте (top_k)", api.TOP_K_MIN, api.TOP_K_MAX,
                      api.TOP_K_DEFAULT, key="mc_top_k",
                      help="Сколько фрагментов корпуса идёт в контекст ответа")
    st.sidebar.checkbox("Показывать цитаты", value=True, key="mc_show_quotes")
    _render_memory_panel(session)


def ensure_session() -> dict:
    """Сессия мини-чата со страницы; при открытии страницы открывается сама.

    Сессия нужна уже на отрисовке боковой панели: панель памяти и чат должны
    показывать одно и то же состояние. Недоступный бэкенд останавливает страницу —
    без бэкенда мини-чат не работает ни в одной своей части.
    """
    session = st.session_state.get(_SESSION_KEY)
    if session is not None:
        return session
    try:
        session = api.start_session()
    except api.BackendError as exc:
        st.sidebar.error(f"Бэкенд недоступен: {exc}")
        st.sidebar.caption("Запустите из папки day21/: "
                           "uvicorn backend.api.main:app --port 8000")
        st.stop()
    st.session_state[_SESSION_KEY] = session
    st.session_state.setdefault(_MESSAGES_KEY, [])
    st.session_state.setdefault(_MEMORY_KEY, None)
    return session


def _start_new_session() -> None:
    """Новая сессия: старые реплики удаляются, память начинается с нового ``task_id``."""
    session = st.session_state.get(_SESSION_KEY)
    if session is not None:
        try:
            api.close_session(session["session_id"])
        except api.BackendError:
            pass  # закрытие сессии — уборка: сбой не должен мешать новой сессии
    for key in (_SESSION_KEY, _MESSAGES_KEY, _MEMORY_KEY):
        st.session_state.pop(key, None)
    st.rerun()


def _render_memory_panel(session: dict) -> None:
    """Панель «Память задачи»: четыре ключа, счётчик реплик и метка обновления."""
    memory = st.session_state.get(_MEMORY_KEY)
    if memory is None or memory.get("session_id") != session["session_id"]:
        try:
            memory = api.fetch_memory(session["session_id"])
        except api.BackendError as exc:
            st.sidebar.warning(f"Память задачи недоступна: {exc}")
            return
        st.session_state[_MEMORY_KEY] = memory
    st.sidebar.subheader("🧠 Память задачи")
    st.sidebar.markdown(f"**Цель:** {memory.get('goal') or '—'}")
    st.sidebar.markdown(f"**Термины:** {_list_text(memory.get('terms'))}")
    st.sidebar.markdown(f"**Ограничения:** {_list_text(memory.get('constraints'))}")
    st.sidebar.markdown(f"**Уточнения:** {_list_text(memory.get('clarifications'))}")
    st.sidebar.caption(f"Реплик в истории: {memory.get('message_count', 0)} · "
                       f"{_updated_text(memory)}")
    st.sidebar.caption(f"Задача: {memory.get('task_id') or '—'}")


def _list_text(items) -> str:
    """Список памяти одной строкой через «;»; пустой список — прочерк."""
    values = [str(item).strip() for item in (items or []) if str(item).strip()]
    return "; ".join(values) if values else "—"


def _updated_text(memory: dict) -> str:
    """Метка обновления памяти: если извлечение не прошло, так и написано."""
    if not memory.get("updated"):
        return "память ещё не извлечена"
    return f"обновлено {memory.get('updated_at') or '—'}"


def render_chat() -> None:
    """Основная область: ход диалога, поле ввода и разбор последнего ответа."""
    st.title("💬 Мини-чат с RAG и памятью")
    st.caption("Ответ приходит с источниками и цитатами из корпуса, а память задачи "
               "обновляется после каждой реплики: цель, термины, ограничения, уточнения.")
    session = ensure_session()
    for entry in st.session_state[_MESSAGES_KEY]:
        _render_turn(entry)
    prompt = st.chat_input("Спросите по корпусу проекта…")
    if prompt:
        _ask(session, prompt)


def _render_turn(entry: dict) -> None:
    """Одна реплика хода: текст, а у ответа — предупреждения, источники и цитаты."""
    role = "user" if entry.get("role") == "user" else "assistant"
    with st.chat_message(role):
        st.markdown(entry.get("content") or "")
        if role == "assistant":
            _render_notices(entry)
            _render_sources(entry)
            _render_quotes(entry)
            _render_provider(entry)


def _render_provider(entry: dict) -> None:
    """Кто отвечал и какая модель: подпись под ответом (день 26).

    Токенов расхода у локальной модели нет (``tokens`` — словарь с нулями), модель
    приходит из ответа Ollama, поэтому подпись собирается из двух полей записи.
    """
    tokens = entry.get("tokens") or {}
    st.caption(f"Провайдер: {entry.get('provider') or '—'} · "
               f"модель: {tokens.get('model') or '—'}")


def _ask(session: dict, prompt: str) -> None:
    """Реплика пользователя: ответ бэкенда, память задачи из ответа, перерисовка.

    Неудачный запрос в историю не попадает: показанный ход диалога остаётся ровно
    тем, что действительно сохранено в краткосрочной памяти сессии.
    """
    with st.chat_message("user"):
        st.markdown(prompt)
    try:
        with st.spinner("Ищу по корпусу и обновляю память задачи…"):
            record = api.send_message(session["session_id"], prompt,
                                      top_k=st.session_state["mc_top_k"],
                                      provider=st.session_state.get("mc_provider"))
    except api.BackendError as exc:
        st.error(f"Ответ не получен: {exc}")
        return
    st.session_state[_MESSAGES_KEY].append({"role": "user", "content": prompt})
    st.session_state[_MESSAGES_KEY].append(
        {"role": "assistant", "content": record.get("answer") or "", **record})
    st.session_state[_MEMORY_KEY] = record.get("task_memory")
    st.rerun()  # боковая панель перерисуется с обновлённой памятью задачи


def _render_notices(record: dict) -> None:
    """Предупреждения ответа: слабый контекст, сбой модели, неудача извлечения памяти."""
    mode = record.get("mode")
    if mode == "dont_know":
        st.warning(record.get("warning") or "Недостаточно контекста в корпусе")
    elif mode == "error":
        st.error(record.get("warning") or record.get("answer")
                 or "Модель не ответила")
    if record.get("memory_warning"):
        st.info(record["memory_warning"])


def _render_sources(record: dict) -> None:
    """Источники ответа: фрагмент, раздел и балл — то, чем ответ подтверждён."""
    sources = record.get("sources") or []
    if not sources:
        return
    with st.expander(f"📚 Источники ({len(sources)})"):
        st.dataframe([_source_row(source) for source in sources],
                     width="stretch", hide_index=True)
        verified = "да" if record.get("quotes_verified") else "нет"
        st.caption(f"{_mode_label(record.get('mode'))} · цитаты проверены: {verified} "
                   f"· уверенность: {float(record.get('confidence') or 0.0):.2f}")


def _source_row(source: dict) -> dict:
    """Строка таблицы источников: только то, что нужно для проверки ответа."""
    return {"source": source.get("source") or "",
            "section": source.get("section") or "",
            "chunk_id": source.get("chunk_id") or "",
            "score": round(float(source.get("score") or 0.0), 4)}


def _mode_label(mode) -> str:
    """Режим ответа словами; незнакомый режим показывается как есть."""
    return _MODE_LABELS.get(str(mode), str(mode or "—"))


def _render_quotes(record: dict) -> None:
    """Цитаты из корпуса: показываются по флажку, с адресом фрагмента."""
    if not st.session_state.get("mc_show_quotes"):
        return
    quotes = record.get("quotes") or []
    if not quotes:
        return
    with st.expander(f"❝ Цитаты ({len(quotes)})"):
        for quote in quotes:
            st.markdown(f"- {quote.get('quote') or ''} · {quote.get('source') or ''} "
                        f"· {quote.get('chunk_id') or ''}")
