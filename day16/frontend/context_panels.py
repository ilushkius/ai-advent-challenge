"""Панели контекста дня 16 (наследовано из дня 12): токены, сжатие, сравнение режимов, ветки, факты.

Панели, зависящие от стратегии агента, и «📊 Токены диалога»: показывают, что
ушло в запрос и сколько удалось сэкономить.
"""
import pandas as pd
import streamlit as st

from . import api_client, common


def render_token_panel(active) -> None:
    """Панель «📊 Токены диалога»: счётчики, лимит, экономия, график, таблица."""
    agent_id = active.get("agent_id")
    try:
        summary = api_client.api_usage(agent_id)
        rows = api_client.api_usage_graph(agent_id)
    except api_client.BackendError:
        return  # бэкенд недоступен/ошибка — панель пропускается, чат живёт

    st.subheader("📊 Токены диалога")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Использовано за диалог",
                f"{common.fmt_int(summary.get('total_tokens'))} токенов")
    col2.metric("Запросов", common.fmt_int(summary.get("total_requests")))
    col3.metric("Стоимость", f"${summary.get('total_cost', 0.0):.6f}")
    col4.metric("Сэкономлено сжатием",
                f"{common.fmt_int(summary.get('total_saved_tokens'))} токенов",
                help="Разница между полной историей и отправленным контекстом; "
                     "чистая экономия (минус стоимость конспектов) — в панели "
                     "«🗜 Сжатие контекста».")

    limit = int(summary.get("context_limit_tokens") or 0)
    current = int(summary.get("current_history_tokens") or 0)
    remaining = int(summary.get("remaining_tokens") or 0)
    ratio = min(1.0, current / limit) if limit else 0.0
    st.progress(ratio)
    st.caption(f"Контекст диалога: занято **{common.fmt_int(current)}** из "
               f"**{common.fmt_int(limit)}** токенов · до лимита осталось "
               f"**{common.fmt_int(remaining)}**")
    if limit and remaining < limit * 0.1:
        st.warning("⚠️ Контекст почти заполнен. Со сжатием агент отправит конспект "
                   "старых реплик — включите сжатие или очистите историю.")

    if rows:
        df = pd.DataFrame([
            {
                "time": common.fmt_time(r.get("timestamp")),
                "prompt_tokens": r.get("prompt_tokens", 0),
                "completion_tokens": r.get("completion_tokens", 0),
                "total_tokens": r.get("total_tokens", 0),
                "full_context_tokens": r.get("full_context_tokens", 0),
                "sent_context_tokens": r.get("sent_context_tokens", 0),
                "saved_tokens": r.get("saved_tokens", 0),
                "mode": "🗜 сжатие" if r.get("summary_used") else "📜 полная",
                "cost": r.get("cost", 0.0),
            }
            for r in rows
        ])
        df["cumulative"] = df["total_tokens"].cumsum()
        df["saved_cumulative"] = df["saved_tokens"].cumsum()
        chart = df.set_index("time")[["cumulative", "saved_cumulative",
                                      "sent_context_tokens"]]
        st.markdown("**📈 Рост токенов и накопленная экономия** "
                    "(total за диалог · сэкономлено · отправлено в последнем запросе):")
        st.line_chart(chart)
        with st.expander("Таблица записей token_usage"):
            st.dataframe(df.rename(columns={
                "time": "время", "prompt_tokens": "запрос",
                "completion_tokens": "ответ", "total_tokens": "всего",
                "full_context_tokens": "без сжатия",
                "sent_context_tokens": "отправлено",
                "saved_tokens": "сэкономлено", "mode": "режим",
                "cost": "стоимость $", "cumulative": "накоплено",
                "saved_cumulative": "накопл. экономия",
            }))
    else:
        st.info("Записей токенов пока нет — отправьте первый запрос, и здесь "
                "появится график и таблица.")


def render_compression_panel(active) -> None:
    """Панель «🗜 Сжатие контекста»: конспект, watermark, экономика, кнопка сжатия."""
    agent_id = active.get("agent_id")
    try:
        state = api_client.api_summary(agent_id)
    except api_client.BackendError:
        return

    st.subheader("🗜 Сжатие контекста")
    keep_last = int(state.get("keep_last_messages") or 0)
    every = int(state.get("summarize_every") or 0)
    st.caption(f"Состояние процесса: **{common.STATE_LABELS.get(state.get('state'), state.get('state'))}** "
               f"· режим: {'включено' if state.get('enabled') else 'выключено'} "
               f"· последние **{keep_last}** "
               f"{common.plural(keep_last, 'реплика', 'реплики', 'реплик')} — как есть "
               f"· сжатие каждые **{every}** "
               f"{common.plural(every, 'новая реплика', 'новые реплики', 'новых реплик')}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Конспектов", common.fmt_int(state.get("summary_count")))
    col2.metric("Реплик в конспекте", common.fmt_int(state.get("covered_messages")),
                help="Сколько реплик заменено конспектом в запросах.")
    col3.metric("Сэкономлено", f"{common.fmt_int(state.get('saved_tokens'))} токенов")
    col4.metric("Чистая экономия",
                f"{common.fmt_int(state.get('net_saved_tokens'))} токенов",
                help="Сэкономленные токены запросов минус токены вызовов "
                     "суммаризации (стоимость конспектов).")

    total = int(state.get("message_count") or 0)
    covered = int(state.get("covered_messages") or 0)
    ratio = min(1.0, covered / total) if total else 0.0
    st.progress(ratio)
    st.caption(f"Покрыто конспектом: **{common.fmt_int(covered)}** из "
               f"**{common.fmt_int(total)}** реплик · до следующего сжатия осталось "
               f"**{common.fmt_int(state.get('next_compression_in'))}** непокрытых "
               f"· стоимость конспектов ${state.get('summary_cost', 0.0):.6f}")

    current = state.get("current")
    if current:
        covered_n = int(current.get("covered_messages") or 0)
        with st.expander(f"📝 Текущий конспект ({covered_n} "
                         f"{common.plural(covered_n, 'реплика', 'реплики', 'реплик')}, "
                         f"{common.fmt_int(current.get('summary_tokens'))} токенов):"):
            st.markdown(common.esc(current.get("content")))
            st.caption(f"Создан: {common.fmt_time(current.get('created_at'))} · "
                       f"исходный текст: {common.fmt_int(current.get('source_tokens'))} "
                       f"токенов · сжатие ×"
                       f"{(current.get('source_tokens') or 0) / max(1, current.get('summary_tokens') or 1):.1f}")
    else:
        st.info("Конспекта пока нет: истории не хватает для порога сжатия. "
                "Кнопка ниже сжимает принудительно (демо).")

    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button("🗜 Сжать сейчас", help="Принудительное сжатие: всё, кроме "
                                             "последних N реплик, уходит в конспект"):
            try:
                report = api_client.api_summarize(agent_id, force=True)
            except api_client.BackendError as exc:
                common.flash("error", f"Сжатие не выполнено: {exc.message}")
            else:
                if report.get("created"):
                    common.flash("success",
                           f"Конспект обновлён: в него ушло "
                           f"{report.get('summarized_messages')} реплик. "
                           f"Состояние: {common.STATE_LABELS.get(report.get('state'), report.get('state'))}")
                else:
                    common.flash("info", f"Сжимать пока нечего: {report.get('error') or 'нет данных'}")
            st.rerun()
    with col_left:
        if state.get("enabled"):
            if st.button("⏸ Отключить сжатие",
                         help="Агент снова начнёт отправлять всю историю (день 8)"):
                try:
                    api_client.api_patch_agent(agent_id, {"summary_enabled": False})
                except api_client.BackendError as exc:
                    common.flash("error", f"Не удалось изменить режим: {exc.message}")
                else:
                    common.flash("info", "Сжатие выключено: в запрос снова идёт вся история.")
                st.rerun()
        else:
            if st.button("▶️ Включить сжатие",
                         help="Агент будет отправлять конспект + последние N реплик"):
                try:
                    api_client.api_patch_agent(agent_id, {"summary_enabled": True})
                except api_client.BackendError as exc:
                    common.flash("error", f"Не удалось изменить режим: {exc.message}")
                else:
                    common.flash("success", "Сжатие включено.")
                st.rerun()


def render_compare(active) -> None:
    """Блок «⚖️ Сравнить режимы»: один промпт в двух вариантах контекста."""
    agent_id = active.get("agent_id")
    with st.expander("⚖️ Сравнить режимы: без сжатия и со сжатием",
                     expanded=False):
        st.caption("Один и тот же промпт считается (и, по желанию, отправляется) "
                   "дважды: со всей историей и с конспектом + последними "
                   "репликами. История диалога при этом не меняется.")
        compare_prompt = st.text_area(
            "Промпт для сравнения", key=f"compare_{agent_id}", height=80,
            placeholder="Например: что мы решили по лимитам контекста?",
        )
        call_api = st.checkbox(
            "Вызвать DeepSeek дважды (сравнить и ответы, и токены)",
            value=False, key=f"compare_api_{agent_id}",
            help="Без галочки считаются только токены — это работает без ключа API.",
        )
        if st.button("⚖️ Сравнить", disabled=not (compare_prompt or "").strip(),
                     key=f"compare_btn_{agent_id}"):
            try:
                result = api_client.api_compare(agent_id, compare_prompt.strip(),
                                     call_api=call_api)
            except api_client.BackendError as exc:
                st.error(f"Сравнение не выполнено: {exc.message}")
            else:
                st.session_state["compare_result"] = result

        result = st.session_state.get("compare_result")
        if result and result.get("agent_id") == agent_id:
            del st.session_state["compare_result"]  # показываем один раз
            col_full, col_comp = st.columns(2)
            full = result.get("full", {})
            comp = result.get("compressed", {})
            with col_full:
                st.markdown("**📜 Без сжатия** (вся история)")
                st.metric("Токенов контекста", common.fmt_int(full.get("sent_context_tokens")))
                if full.get("total_tokens") is not None:
                    st.caption(f"usage: вход {full.get('prompt_tokens')} · "
                               f"выход {full.get('completion_tokens')} · "
                               f"${full.get('cost', 0):.6f}")
                if full.get("error"):
                    st.error(full["error"])
                elif full.get("response"):
                    st.markdown(common.esc(full["response"]))
            with col_comp:
                st.markdown("**🗜 Со сжатием** (конспект + последние реплики)")
                st.metric("Токенов контекста", common.fmt_int(comp.get("sent_context_tokens")),
                          delta=f"-{common.fmt_int(result.get('saved_tokens'))}")
                if comp.get("total_tokens") is not None:
                    st.caption(f"usage: вход {comp.get('prompt_tokens')} · "
                               f"выход {comp.get('completion_tokens')} · "
                               f"${comp.get('cost', 0):.6f}")
                if comp.get("error"):
                    st.error(comp["error"])
                elif comp.get("response"):
                    st.markdown(common.esc(comp["response"]))
            st.success(
                f"Экономия контекста: **{common.fmt_int(result.get('saved_tokens'))}** токенов "
                f"(**{result.get('saved_percent')}%**) · "
                f"конспект: {'использован' if comp.get('summary_used') else 'не использован'}"
                f" · покрыто реплик: {common.fmt_int(comp.get('summarized_messages'))}"
            )
            if result.get("warning"):
                st.warning(result["warning"])


def render_branching_panel(active) -> None:
    """Панель «🌿 Ветвление»: дерево веток, создать ветку, переключиться."""
    agent_id = active.get("agent_id")
    try:
        tree = api_client.api_branches(agent_id)
    except api_client.BackendError:
        return

    st.subheader("🌿 Ветвление истории")
    branches = tree.get("branches") or []
    active_id = tree.get("active_branch_id")

    if not branches:
        st.info("Веток пока нет. Отправьте сообщение в режиме branching — "
                "создастся корневой чекпоинт, от которого можно ветвиться.")
        return

    # Дерево: чекпоинт → parent_id. Отрисовываем список с отступом по глубине.
    by_id = {b["id"]: b for b in branches}

    def _depth(branch, memo=None):
        memo = memo or {}
        if branch["id"] in memo:
            return 0
        memo[branch["id"]] = True
        parent = branch.get("parent_id")
        if parent is not None and parent in by_id:
            return 1 + _depth(by_id[parent], memo)
        return 0

    st.caption(f"Активная ветка: **{active_id}** · всего чекпоинтов: "
               f"{len(branches)}")
    for branch in branches:
        depth = _depth(branch)
        marker = "🟢" if branch["id"] == active_id else "  "
        label = (f"{marker} {'·  ' * depth}ветка {branch['id']} "
                 f"({branch['message_count']} "
                 f"{common.plural(branch['message_count'], 'реплика', 'реплики', 'реплик')})"
                 f" · {common.fmt_time(branch.get('created_at'))}")
        col_label, col_switch = st.columns([5, 1])
        with col_label:
            st.markdown(label)
        with col_switch:
            if branch["id"] != active_id:
                if st.button("↩", key=f"switch_{branch['id']}",
                             help=f"Переключиться на ветку {branch['id']}"):
                    try:
                        api_client.api_switch_branch(agent_id, branch["id"])
                    except api_client.BackendError as exc:
                        common.flash("error", f"Не удалось переключить ветку: {exc.message}")
                    else:
                        common.flash("info", f"Переключено на ветку {branch['id']}.")
                    st.rerun()

    col_new, _ = st.columns([3, 1])
    with col_new:
        if st.button("🌱 Новая ветка от текущего сообщения",
                     help="Снимок текущей истории становится новой веткой; "
                          "старая ветка замораживается, новая — активна."):
            try:
                api_client.api_create_branch(agent_id, None)
            except api_client.BackendError as exc:
                common.flash("error", f"Не удалось создать ветку: {exc.message}")
            else:
                common.flash("success", "Создана новая ветка от текущего сообщения.")
            st.rerun()


def render_facts_panel(active) -> None:
    """Панель «📌 Факты» для sticky_facts: ключ-значение в реальном времени."""
    agent_id = active.get("agent_id")
    try:
        facts = api_client.api_facts(agent_id).get("facts", [])
    except api_client.BackendError:
        return

    st.subheader("📌 Факты диалога (sticky_facts)")
    if not facts:
        st.info("Фактов пока нет. Пишите реплики вида «ключ: значение» — "
                "эвристика извлечёт их и отправит в LLM вместе с последними "
                "сообщениями.")
        return
    rows = [{"ключ": f.get("key"), "значение": f.get("value"),
             "обновлено": common.fmt_time(f.get("updated_at"))} for f in facts]
    st.dataframe(rows, use_container_width=True, hide_index=True)
