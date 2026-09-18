"""Раздел «💬 Чат и память» дня 15: карточка агента, панели, диалог и ввод.

Единственная точка входа — ``render_main_area()``: заголовок и подпись,
флеш-сообщение предыдущего прохода, ветка «бэкенд недоступен», переключатель
разделов (чат, профиль, состояние задачи, инварианты), карточка активного
агента, панели стратегии и слоёв памяти, диалог, сравнение режимов, блок
предупреждения/отказа по инвариантам последнего хода, форма ввода и очистка
истории.
"""
import streamlit as st

from . import (
    api_client, common, context_panels, invariant_panel, memory_panels,
    profile_section, task_panel,
)


def _ensure_chat(active):
    """Подгружает диалог активного агента, если он ещё не в состоянии."""
    if active is None:
        return
    if st.session_state.get("chat_agent_id") == active["agent_id"]:
        return
    try:
        st.session_state["chat_messages"] = api_client.api_history(active["agent_id"])
        st.session_state["chat_agent_id"] = active["agent_id"]
    except api_client.BackendError as exc:
        st.session_state["chat_messages"] = []
        st.session_state["chat_agent_id"] = active["agent_id"]
        st.warning(f"Диалог не загружен: {exc.message}")


def render_main_area() -> None:
    """Рисует основную область: карточка агента, панели, диалог и ввод."""
    st.title("💬 Чат с агентами DeepSeek · три слоя памяти")
    st.caption("Агент помнит диалог в SQLite и раскладывает память по трём слоям: "
               "краткосрочная (текущая сессия), рабочая (текущая задача) и "
               "долговременная (профиль и предпочтения). Слои памяти — в панелях "
               "ниже, переключатель задачи и кнопка новой сессии — в боковой панели.")

    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        if kind == "success":
            st.success(message)
        elif kind == "error":
            st.error(message)
        elif kind == "warning":
            st.warning(message)
        else:
            st.info(message)

    if not st.session_state["backend_ok"]:
        st.warning("🔌 Бэкенд недоступен. Запустите его из папки day15/:")
        st.code("uvicorn backend.api.main:app --port 8000", language="bash")
        if st.session_state.get("backend_error"):
            st.caption(f"Причина: {st.session_state['backend_error']}")
    else:
        agents = st.session_state["agents"]
        # Разделы переключаются st.radio, а не st.tabs: выбор вкладки Streamlit не
        # сохраняет между перезапусками скрипта, а после «Сохранить профиль» нужен
        # st.rerun — с radio пользователь остаётся в том же разделе.
        section = st.radio(
            "Раздел",
            ["💬 Чат и память", "👤 Профиль пользователя", "🧭 Состояние задачи",
             "📏 Инварианты"],
            horizontal=True, key="main_section", label_visibility="collapsed",
        )
        if section.startswith("👤"):
            profile_section.render_profile_section(common.active_agent())
        elif section.startswith("🧭"):
            task_panel.render_task_panel(common.active_agent())
        elif section.startswith("📏"):
            # Инварианты глобальны: активный агент разделу не нужен.
            invariant_panel.render_invariant_panel()
        else:
            if not agents:
                st.info("Агентов пока нет — создайте первого в боковой панели. "
                        "Его диалог, слои памяти и метрики сохранятся в "
                        "day15/agents.db.")
            else:
                # --- выбор агента (список с числом сообщений и режимом сжатия) ---
                labels = [common.label_agent(a) for a in agents]
                active = common.active_agent()
                idx = next(i for i, a in enumerate(agents)
                           if a["agent_id"] == active["agent_id"])
                chosen = st.selectbox("Агент", labels, index=idx,
                                      help="Переключение загружает диалог агента.")
                active = agents[labels.index(chosen)]
                st.session_state["active_agent_id"] = active["agent_id"]

                col_card, col_del = st.columns([5, 1])
                with col_card:
                    st.subheader(f"🤖 {active['name']}")
                    strategy = active.get("strategy", "summary")
                    strategy_label = common.STRATEGY_LABELS.get(strategy, strategy)
                    st.caption(
                        f"id `{active['agent_id']}` · модель **{active['model']}** · "
                        f"температура {active.get('temperature', '—')} · "
                        f"max_tokens {active.get('max_tokens', '—')}"
                    )
                    st.markdown(
                        f"**Стратегия:** {strategy_label} · window_size "
                        f"{active.get('window_size', '—')}"
                    )
                    st.markdown(
                        f"**Профиль пользователя (день 12):** "
                        f"`{active.get('user_id', 'default')}` — настройки и "
                        "кастомные инструкции во вкладке «👤 Профиль пользователя»"
                    )
                    if strategy == "branching":
                        try:
                            tree = api_client.api_branches(active["agent_id"])
                            active_id = tree.get("active_branch_id")
                        except api_client.BackendError:
                            active_id = None
                        st.caption(f"🌿 Активная ветка: **{active_id}**")
                    if active.get("system_prompt"):
                        st.caption(f"Роль: _{active['system_prompt']}_")
                with col_del:
                    if st.button("🗑 Удалить агента",
                                 help="Удалить вместе с диалогом, конспектами и метриками"):
                        try:
                            api_client.api_delete_agent(active["agent_id"])
                        except api_client.BackendError as exc:
                            st.error(f"Не удалось удалить: {exc.message}")
                        else:
                            common.load_agents()
                            st.session_state["chat_agent_id"] = None
                            st.success("Агент удалён.")

                # --- панели по стратегии + панель токенов ---
                strategy = active.get("strategy", "summary")
                if strategy == "summary":
                    context_panels.render_compression_panel(active)
                elif strategy == "sticky_facts":
                    context_panels.render_facts_panel(active)
                elif strategy == "branching":
                    context_panels.render_branching_panel(active)
                context_panels.render_token_panel(active)

                # --- слои памяти агента: три панели + индикация последнего запроса ---
                memory_panels.render_memory_panels(active)
                memory_panels.render_memory_indicator(active)

                st.divider()

                # --- диалог: роль + текст каждого сообщения + маркер сжатия ---
                _ensure_chat(active)
                st.subheader("💬 Диалог")
                chat_box = st.container(height=420, border=False)
                messages = st.session_state.get("chat_messages") or []
                with chat_box:
                    if not messages:
                        st.info("Диалог пуст. Напишите первое сообщение — и агент "
                                "запомнит его после перезапуска.")
                    # Маркер ставим на границе: где кончаются покрытые конспектом
                    # реплики и начинается отправляемый «как есть» хвост.
                    marker_done = False
                    for msg in messages:
                        if (not marker_done and msg.get("summarized") is False
                                and any(m.get("summarized") for m in messages)):
                            covered = sum(1 for m in messages if m.get("summarized"))
                            try:
                                state = api_client.api_summary(active["agent_id"])
                                summary_tokens = (state.get("current") or {}).get(
                                    "summary_tokens", 0)
                            except api_client.BackendError:
                                summary_tokens = 0
                            common.render_summary_marker(covered, summary_tokens)
                            marker_done = True
                        common.render_message(msg.get("role", ""),
                                       msg.get("content", ""),
                                       msg.get("created_at", ""))

                # --- сравнение режимов (день 9) ---
                context_panels.render_compare(active)

                # --- поле ввода и кнопки внизу ---
                # Инварианты (день 14): предупреждение или отказ по последнему
                # ходу — рядом с диалогом и вводом, а не только в плашке сверху.
                notice = st.session_state.get("invariant_notice")
                if notice:
                    notice_verdict, notice_text = notice
                    if notice_verdict == "refusal":
                        st.error(notice_text)
                    else:
                        st.warning(notice_text)
                # Форма: значения виджетов уходят на сервер по нажатию «Отправить», а не
                # по потере фокуса, поэтому отправка работает сразу после набора текста.
                with st.form(key=f"chat_form_{active['agent_id']}", clear_on_submit=True):
                    prompt = st.text_area(
                        "Сообщение агенту", key=f"prompt_{active['agent_id']}",
                        height=90, placeholder="Введите сообщение и нажмите «Отправить»…",
                    )
                    sent = st.form_submit_button(
                        "🚀 Отправить", type="primary",
                        help="Контекст собирается текущей стратегией "
                             "(окно / факты / ветка / конспект).",
                    )
                if sent and not prompt.strip():
                    st.info("Пустое сообщение не отправлено: введите текст.")
                elif sent:
                    with st.spinner("🤖 Агент думает… это занимает несколько секунд"):
                        try:
                            record = api_client.api_generate(active["agent_id"], prompt)
                        except api_client.BackendError as exc:
                            common.flash("error", f"Запрос не выполнен: {exc.message}")
                            st.rerun()
                        else:
                            if record.get("status") == "ok":
                                # Сервер вернул актуальную историю — рисуем из неё.
                                st.session_state["chat_messages"] = record.get("messages", [])
                                st.session_state["chat_agent_id"] = active["agent_id"]
                                common.load_agents()  # обновить счётчики в боковой панели
                                tm = record.get("token_metrics") or {}
                                ctx = record.get("context") or {}
                                comp = ctx.get("compression") or {}
                                mem = record.get("memory") or {}
                                st.session_state["last_memory"][active["agent_id"]] = mem
                                notes = []
                                inv = record.get("invariants") or {}
                                verdict = inv.get("verdict", "allowed")
                                if verdict in ("warning", "refusal"):
                                    st.session_state["invariant_notice"] = (
                                        verdict, common.invariant_notice(inv))
                                    notes.append(
                                        "📏 инварианты: "
                                        + common.INVARIANT_VERDICT_LABELS.get(
                                            verdict, verdict))
                                else:
                                    st.session_state["invariant_notice"] = None
                                if comp.get("summary_used"):
                                    notes.append(
                                        f"🗜 конспект: сэкономлено "
                                        f"{common.fmt_int(comp.get('saved_tokens'))} токенов "
                                        f"({comp.get('saved_percent')}%)")
                                if mem:
                                    notes.append(
                                        f"слои: короткая "
                                        f"{common.fmt_int(mem.get('short_term_tokens'))} / рабочая "
                                        f"{common.fmt_int(mem.get('working_tokens'))} / "
                                        f"долговременная "
                                        f"{common.fmt_int(mem.get('long_term_tokens'))} токенов")
                                applied_profile = record.get("profile") or {}
                                if applied_profile.get("personalized"):
                                    notes.append(
                                        f"👤 профиль {applied_profile.get('user_id')}: "
                                        f"{len(applied_profile.get('elements') or [])} "
                                        "элементов")
                                else:
                                    notes.append("👤 профиль: без персонализации")
                                if ctx.get("trimmed_messages"):
                                    notes.append(f"⚠️ пропущено реплик в запросе: "
                                                 f"{ctx['trimmed_messages']}")
                                if ctx.get("warning"):
                                    notes.append(ctx["warning"])
                                if comp.get("error"):
                                    notes.append(f"⚠️ сжатие не выполнено: {comp['error']}")
                                note_text = (" · " + " · ".join(notes)) if notes else ""
                                # Одна плашка на ход: ошибка сжатия — красная, остальное —
                                # успешная сводка (иначе второе сообщение затирает первое).
                                kind = "error" if comp.get("error") else "success"
                                common.flash(kind,
                                       f"Ответ получен за {record.get('duration_sec', 0):.2f} с · "
                                       f"токены {common.format_usage(record.get('usage'))} · "
                                       f"стоимость ~${tm.get('cost', 0):.6f} · "
                                       f"finish_reason {record.get('finish_reason') or '—'}"
                                       f"{note_text}")
                            else:
                                common.flash("error", f"Генерация завершилась ошибкой: "
                                                f"{record.get('error')}")
                            st.rerun()
                if st.button("🧹 Очистить историю",
                             help="Удаляет диалог, конспекты и метрики. "
                                  "Конфигурация агента не меняется."):
                    try:
                        api_client.api_clear_history(active["agent_id"])
                    except api_client.BackendError as exc:
                        common.flash("error", f"Не удалось очистить: {exc.message}")
                        st.rerun()
                    else:
                        st.session_state["chat_messages"] = []
                        st.session_state["chat_agent_id"] = active["agent_id"]
                        common.load_agents()
                        common.flash("success", "История, конспекты и метрики очищены. "
                                          "Новый диалог начнётся с нуля.")
                        st.rerun()
