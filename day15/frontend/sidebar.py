"""Боковая панель дня 15 (наследовано из дня 12): список агентов, создание агента, стратегия, задача.

Единственная точка входа — ``render_sidebar()``; порядок блоков сохранён из
монолитного ``app.py``: список агентов → создание агента → стратегия → задача
и сессия.
"""
import streamlit as st

from . import api_client, common


def render_sidebar() -> None:
    """Рисует боковую панель: список агентов, создание, стратегия, задача."""
    common.load_agents()
    st.sidebar.title("🧠 Память агента")
    if st.session_state["backend_ok"]:
        st.sidebar.caption(f"🟢 Бэкенд: {api_client.BACKEND_URL} · агентов: "
                           f"{len(st.session_state['agents'])}")
    else:
        st.sidebar.caption(f"🔴 Бэкенд недоступен: {api_client.BACKEND_URL}")
    if st.sidebar.button("🔄 Обновить список"):
        common.load_agents()

    # --- создание нового агента ---
    st.sidebar.subheader("➕ Новый агент")
    try:
        profile_ids = [user["user_id"] for user in api_client.api_list_users()]
    except api_client.BackendError:
        profile_ids = []
    profile_options = ["default"] + [
        user_id for user_id in profile_ids if user_id != "default"
    ]
    with st.sidebar.form("create_agent_form", clear_on_submit=True):
        form_name = st.text_input("Имя агента", placeholder="Например: Конспектёр")
        form_user = st.selectbox(
            "Профиль пользователя (user_id)", profile_options,
            help="Чей профиль подключать к системным промптам агента. Профили "
                 "создаются и правятся в разделе «👤 Профиль пользователя».",
        )
        form_model = st.selectbox(
            "Модель",
            ["deepseek-chat", "deepseek-reasoner"],
            help="deepseek-reasoner может игнорировать temperature.",
        )
        form_temp = st.slider("Температура", 0.0, 2.0, 0.7, 0.1)
        form_system = st.text_area(
            "Системный промпт (роль)", height=90,
            placeholder="Пусто — системное сообщение не добавляется.",
        )
        form_max_tokens = st.number_input("max_tokens", 1, 8192, 2048, step=128)
        st.markdown("**🗜 Сжатие истории**")
        form_summary = st.checkbox("Сжимать историю в конспект", value=True)
        form_keep_last = st.slider(
            "Последних реплик «как есть»", 2, 20, 6,
            help="Столько последних сообщений всегда уходит в запрос дословно.",
        )
        form_summarize_every = st.slider(
            "Сжимать каждые N новых реплик", 2, 40, 10,
            help="Порог: когда непокрытых реплик накопилось N, старые уходят в конспект.",
        )
        form_submit = st.form_submit_button("Создать агента")

    if form_submit:
        if not form_name.strip():
            st.sidebar.error("Укажите имя агента.")
        else:
            try:
                info = api_client.api_create_agent({
                    "name": form_name,
                    "model": form_model,
                    "temperature": float(form_temp),
                    "system_prompt": form_system,
                    "max_tokens": int(form_max_tokens),
                    "summary_enabled": bool(form_summary),
                    "keep_last_messages": int(form_keep_last),
                    "summarize_every": int(form_summarize_every),
                    "user_id": form_user,
                })
            except api_client.BackendError as exc:
                st.sidebar.error(f"Не удалось создать: {exc.message}")
            else:
                common.load_agents()
                st.session_state["active_agent_id"] = info["agent_id"]
                st.session_state["chat_agent_id"] = None  # перечитаем диалог
                st.sidebar.success(
                    f"Создан: {info['name']} ({info['agent_id']}) · профиль "
                    f"{info.get('user_id', 'default')}"
                )


    # --- стратегия контекста активного агента (день 11) ---
    if st.session_state["backend_ok"] and st.session_state["agents"]:
        active = common.active_agent()
        if active is not None:
            st.sidebar.subheader("⚙️ Стратегия контекста")
            st.sidebar.caption(f"Агент: **{active['name']}**")
            current_strategy = active.get("strategy", "summary")
            current_window = int(active.get("window_size", 10))
            options = list(common.STRATEGY_LABELS.keys())
            if current_strategy not in options:
                current_strategy = "summary"
            with st.sidebar.form(f"strategy_form_{active['agent_id']}"):
                chosen = st.selectbox(
                    "Стратегия", options, index=options.index(current_strategy),
                    format_func=lambda s: common.STRATEGY_LABELS[s],
                )
                window = st.slider("window_size (последних реплик)", 2, 50,
                                   current_window,
                                   help="Для sliding_window и sticky_facts: сколько "
                                        "последних реплик уходит в запрос.")
                apply_strategy = st.form_submit_button("Применить стратегию")
            if apply_strategy:
                try:
                    api_client.api_set_strategy(active["agent_id"], chosen, window)
                except api_client.BackendError as exc:
                    st.sidebar.error(f"Не удалось сменить стратегию: {exc.message}")
                else:
                    common.load_agents()
                    st.session_state["chat_agent_id"] = None  # перечитаем диалог
                    st.rerun()

            # --- задача и сессия (слои памяти, день 11) ---
            st.sidebar.subheader("🗂 Задача и сессия")
            agent_id = active["agent_id"]
            st.sidebar.caption(
                f"Сессия: **{active.get('session_id', '—')}** · задача: "
                f"**{active.get('task_id', 'default')}**"
            )
            try:
                tasks = api_client.api_working(agent_id).get("tasks") or []
            except api_client.BackendError:
                tasks = []
            if active.get("task_id") and active["task_id"] not in tasks:
                tasks = [active["task_id"]] + tasks
            if not tasks:
                tasks = [active.get("task_id") or "default"]

            with st.sidebar.form(f"task_switch_form_{agent_id}"):
                task_choice = st.selectbox(
                    "Активная задача", tasks, index=0,
                    help="Рабочая память фильтруется по задаче: переключение меняет "
                         "набор записей, которые уходят в контекст.",
                )
                switch_task = st.form_submit_button("🔀 Переключить задачу")
            if switch_task:
                try:
                    api_client.api_set_task(agent_id, task_choice)
                except api_client.BackendError as exc:
                    st.sidebar.error(f"Не удалось переключить задачу: {exc.message}")
                else:
                    common.flash("info", f"Активная задача: {task_choice}.")
                    common.load_agents()
                    st.rerun()

            with st.sidebar.form(f"task_create_form_{agent_id}",
                                clear_on_submit=True):
                new_task = st.text_input("Новая задача (task_id)",
                                         placeholder="например: tz-portal")
                create_task = st.form_submit_button("➕ Создать задачу")
            if create_task:
                if not new_task.strip():
                    st.sidebar.warning("Укажите идентификатор задачи.")
                else:
                    try:
                        result = api_client.api_set_task(agent_id, new_task.strip())
                    except api_client.BackendError as exc:
                        st.sidebar.error(f"Не удалось создать задачу: {exc.message}")
                    else:
                        common.flash("success",
                               f"Активная задача: {result.get('task_id')} "
                               f"(записей: {result.get('entries', 0)}).")
                        common.load_agents()
                        st.rerun()

            if st.sidebar.button("🆕 Новая сессия",
                                 help="Краткосрочная память обнуляется (диалог, "
                                      "конспекты и факты), рабочая и долговременная "
                                      "память сохраняются."):
                try:
                    session = api_client.api_new_session(agent_id)
                except api_client.BackendError as exc:
                    st.sidebar.error(f"Не удалось начать сессию: {exc.message}")
                else:
                    st.session_state["chat_agent_id"] = None
                    st.session_state["last_memory"] = {}
                    common.flash("success",
                           f"Новая сессия {session.get('session_id')}: удалено "
                           f"реплик {session.get('deleted_messages', 0)}. Рабочая и "
                           "долговременная память сохранены.")
                    common.load_agents()
                    st.rerun()
