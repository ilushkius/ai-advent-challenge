"""Панели трёх слоёв памяти дня 17 (наследовано из дня 12): краткосрочная, рабочая и долговременная.

Плюс индикатор того, что из слоёв ушло в контекст последнего запроса.
"""
import streamlit as st

from . import api_client, common


# ---------- панели слоёв памяти (день 11) ----------
def render_short_term_panel(active) -> None:
    """Панель «👤 Краткосрочная память»: реплики текущей сессии и её очистка."""
    agent_id = active.get("agent_id")
    try:
        data = api_client.api_short_term(agent_id)
    except api_client.BackendError:
        return  # бэкенд недоступен/ошибка — панель пропускается, чат живёт

    messages = data.get("messages") or []
    st.subheader("👤 Краткосрочная память (текущая сессия)")
    st.caption(f"Сессия **{data.get('session_id')}** · реплик: "
               f"**{len(messages)}** · слой очищается кнопкой «🆕 Новая сессия» "
               "и командой ниже.")
    if not messages:
        st.info("Краткосрочная память пуста. Реплики появятся здесь после "
                "первого сообщения (или добавьте их кнопкой «Отправить»).")
    else:
        rows = [{
            "роль": common.ROLE_LABELS.get(m.get("role"), m.get("role")),
            "текст": (m.get("content") or "")[:200],
            "создано": common.fmt_time(m.get("created_at")),
        } for m in messages]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if st.button("🧹 Очистить краткосрочную память",
                 key=f"short_term_clear_{agent_id}",
                 help="Удаляет реплики текущей сессии. Рабочая и долговременная "
                      "память не затрагиваются."):
        try:
            result = api_client.api_clear_short_term(agent_id)
        except api_client.BackendError as exc:
            common.flash("error", f"Не удалось очистить сессию: {exc.message}")
        else:
            common.flash("success",
                   f"Краткосрочная память очищена: удалено реплик "
                   f"{result.get('deleted', 0)}.")
            st.session_state["chat_agent_id"] = None
        common.load_agents()
        st.rerun()


def render_working_panel(active) -> None:
    """Панель «🗂 Рабочая память»: записи активной задачи и их сохранение."""
    agent_id = active.get("agent_id")
    try:
        data = api_client.api_working(agent_id)
    except api_client.BackendError:
        return

    entries = data.get("entries") or []
    task_id = data.get("task_id", "default")
    st.subheader("🗂 Рабочая память (текущая задача)")
    st.caption(f"Задача **{task_id}** · записей: **{len(entries)}** · слой "
               "переживает смену сессии и очищается только вручную "
               "(или сменой задачи).")

    with st.form(f"working_add_{agent_id}"):
        st.markdown("**Добавить/обновить запись** (ввод существующего ключа "
                    "перезапишет значение — upsert)")
        col_key, col_value = st.columns([2, 3])
        w_key = col_key.text_input("Ключ", placeholder="например: цель")
        w_value = col_value.text_area("Значение", height=80,
                                      placeholder="например: портал для ТЗ")
        if st.form_submit_button("💾 Сохранить"):
            if not w_key.strip() or not w_value.strip():
                st.warning("Нужны и ключ, и значение.")
            else:
                try:
                    api_client.api_add_working(agent_id, w_key.strip(), w_value.strip())
                except api_client.BackendError as exc:
                    st.error(f"Не удалось сохранить: {exc.message}")
                else:
                    common.flash("success",
                           f"Рабочая память задачи {task_id}: записан ключ "
                           f"«{w_key.strip()}».")
                    st.rerun()

    if not entries:
        st.info("Записей нет. Сохраните цель, ограничения или решения задачи — "
                "они будут подставляться в каждый запрос этой задачи.")
    else:
        rows = [{"ключ": e.get("key"), "значение": e.get("value"),
                 "обновлено": common.fmt_time(e.get("updated_at"))} for e in entries]
        st.dataframe(rows, use_container_width=True, hide_index=True)


def render_long_term_panel(active) -> None:
    """Панель «🧠 Долговременная память»: записи между сессиями, CRUD."""
    agent_id = active.get("agent_id")
    st.subheader("🧠 Долговременная память (между сессиями)")
    categories = list(common.MEMORY_CATEGORY_LABELS.keys())
    all_label = "все категории"
    chosen = st.selectbox(
        "Фильтр по категории", [all_label] + categories,
        format_func=lambda c: all_label if c == all_label
        else common.MEMORY_CATEGORY_LABELS[c],
        key=f"long_term_filter_{agent_id}",
    )
    try:
        data = api_client.api_long_term(agent_id, None if chosen == all_label else chosen)
    except api_client.BackendError:
        return

    entries = data.get("entries") or []
    st.caption("Устойчивые данные о пользователе: профиль, предпочтения, "
               "решения, знания. Не очищаются ни «Новой сессией», ни сменой "
               "задачи — удаляются только вручную.")

    with st.form(f"long_term_add_{agent_id}"):
        st.markdown("**Добавить/обновить запись** (upsert по категории и ключу)")
        lt_category = st.selectbox(
            "Категория", categories,
            format_func=lambda c: common.MEMORY_CATEGORY_LABELS[c],
        )
        lt_key = st.text_input("Ключ", placeholder="например: язык_интерфейса")
        lt_value = st.text_area("Значение", height=80,
                                placeholder="например: русский")
        lt_confidence = st.slider("Уверенность", 0.0, 1.0, 1.0, 0.05)
        if st.form_submit_button("💾 Сохранить"):
            if not lt_key.strip() or not lt_value.strip():
                st.warning("Нужны и ключ, и значение.")
            else:
                try:
                    api_client.api_add_long_term(agent_id, lt_category, lt_key.strip(),
                                      lt_value.strip(), lt_confidence)
                except api_client.BackendError as exc:
                    st.error(f"Не удалось сохранить: {exc.message}")
                else:
                    common.flash("success",
                           f"Долговременная память: записан ключ "
                           f"«{lt_key.strip()}» ({lt_category}).")
                    st.rerun()

    if not entries:
        st.info("Записей нет. Добавьте профиль пользователя или устойчивое "
                "предпочтение — такие записи учитываются в каждом запросе.")
        return

    rows = [{
        "id": e.get("id"),
        "категория": common.MEMORY_CATEGORY_LABELS.get(e.get("category"),
                                                e.get("category")),
        "ключ": e.get("key"),
        "значение": e.get("value"),
        "уверенность": e.get("confidence"),
    } for e in entries]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    col_id, col_del = st.columns([2, 1])
    entry_ids = [e.get("id") for e in entries]
    entry_id = col_id.selectbox("Удалить запись по id", entry_ids,
                                key=f"long_term_del_{agent_id}")
    if col_del.button("🗑 Удалить", key=f"long_term_del_btn_{agent_id}",
                      help="Удаляет запись долговременной памяти безвозвратно."):
        try:
            api_client.api_delete_long_term(agent_id, entry_id)
        except api_client.BackendError as exc:
            common.flash("error", f"Не удалось удалить запись {entry_id}: {exc.message}")
        else:
            common.flash("success", f"Запись {entry_id} удалена из долговременной памяти.")
        st.rerun()


def render_memory_panels(active) -> None:
    """Три вкладки панелей памяти: краткосрочная, рабочая, долговременная."""
    st.subheader("🧠 Слои памяти агента")
    tab_short, tab_working, tab_long = st.tabs(
        ["👤 Краткосрочная", "🗂 Рабочая", "🧠 Долговременная"]
    )
    with tab_short:
        render_short_term_panel(active)
    with tab_working:
        render_working_panel(active)
    with tab_long:
        render_long_term_panel(active)


def render_memory_indicator(active) -> None:
    """Индикатор слоёв: что именно ушло в контекст последнего запроса.

    Данные берутся из ответа генерации (``record["memory"]``), который
    сохраняется в ``st.session_state["last_memory"]``: до первого сообщения
    показывать нечего.
    """
    agent_id = active.get("agent_id")
    memory = (st.session_state.get("last_memory") or {}).get(agent_id)
    st.subheader("🧭 Что ушло в последний запрос")
    if not memory:
        st.caption("Слои памяти: индикация появится после первого сообщения.")
        return

    layers = {layer.get("layer"): layer for layer in memory.get("layers") or []}
    col1, col2, col3 = st.columns(3)
    for column, key in ((col1, "short_term"), (col2, "working"),
                        (col3, "long_term")):
        layer = layers.get(key) or {}
        entries = int(layer.get("entries") or 0)
        tokens = int(layer.get("tokens") or 0)
        column.metric(
            common.LAYER_LABELS[key],
            f"{entries} записей · {common.fmt_int(tokens)} токенов",
            help=layer.get("details") or "",
        )
    st.caption(
        f"Сессия **{memory.get('session_id')}** · задача "
        f"**{memory.get('task_id')}** · всего по слоям: "
        f"**{common.fmt_int(memory.get('total_tokens'))}** токенов "
        f"(короткая {common.fmt_int(memory.get('short_term_tokens'))} + рабочая "
        f"{common.fmt_int(memory.get('working_tokens'))} + долговременная "
        f"{common.fmt_int(memory.get('long_term_tokens'))})"
    )
    used = [common.LAYER_LABELS[key] for key in ("short_term", "working", "long_term")
            if (layers.get(key) or {}).get("used")]
    if used:
        st.caption("Использованы в запросе: " + " · ".join(used))
    keywords = memory.get("keywords") or []
    if keywords:
        st.caption("Ключевые слова запроса (отбор долговременных записей): "
                   + ", ".join(keywords))
