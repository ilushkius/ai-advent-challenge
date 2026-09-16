"""Раздел «🧭 Состояние задачи» дня 13: этап, шаг, пауза и журнал переходов.

Единственная точка входа — ``render_task_panel(active)``: показывает состояние
активной задачи агента (этап, шаг, ожидаемое действие), схему переходов, пять
кнопок управления и журнал переходов. Если состояния у активной задачи ещё нет,
панель предлагает его завести.
"""
import streamlit as st

from . import api_client, common

# Схема FSM в виде текста: библиотек для диаграмм в requirements нет, а ASCII
# читается и в браузере, и в отчёте. Единственный источник правды о переходах —
# backend/task_fsm.py: здесь та же картина словами.
FSM_DIAGRAM = "\n".join([
    "прямой ход:    planning -> execution -> validation -> done",
    "откат:         validation -> execution;  execution -> planning",
    "пауза:         planning|execution|validation|done -> paused",
    "возобновление: paused -> тот же этап и шаг, с которого встали",
    "",
    "шаги по этапам:",
    "  planning   : gather_requirements, define_scope, create_plan",
    "  execution  : implement, test_locally",
    "  validation : review, run_tests, finalize",
    "  done       : (шагов нет, current_step остаётся finalize)",
    "  paused     : (текущий шаг сохраняется)",
])

START_STAGES = ["planning", "execution", "validation"]


def _current_state(active):
    """Состояние активной задачи агента (``None`` — состояние не заведено)."""
    try:
        return api_client.api_task_state(active.get("task_id"))
    except api_client.BackendError as exc:
        if exc.status_code == 404:
            return None
        raise


def _call(action, success: str, failure: str) -> None:
    """Мутирующий эндпоинт задачи: флеш-сообщение и перерисовка страницы."""
    try:
        action()
    except api_client.BackendError as exc:
        common.flash("error", f"{failure}: {exc.message}")
    else:
        common.flash("success", success)
        # Состояние задачи менялось — диалог перечитается на следующем проходе.
        st.session_state["chat_agent_id"] = None
    common.load_agents()
    st.rerun()


def _render_create_form(active) -> None:
    """Форма заведения состояния для активной задачи агента."""
    agent_id = active.get("agent_id")
    st.info(
        f"Состояние задачи не заведено. Активная задача агента — "
        f"`{active.get('task_id')}`; создание сделает её активной и подключит "
        "блок состояния к системному промпту каждого запроса."
    )
    with st.form(key=f"task_create_form_{agent_id}"):
        task_id = st.text_input("Новая задача (task_id)",
                                value=active.get("task_id", "default"))
        stage = st.selectbox("Начальный этап", START_STAGES)
        submitted = st.form_submit_button("➕ Создать задачу", type="primary")
    if not submitted:
        return
    clean = task_id.strip()
    if not clean:
        st.error("task_id не может быть пустым.")
        return
    _call(
        lambda: api_client.api_create_task(agent_id, clean, stage),
        f"Задача {clean} заведена на этапе {stage}.",
        "Создание задачи не выполнено",
    )


def render_task_panel(active) -> None:
    """Раздел «🧭 Состояние задачи»: состояние, схема, кнопки и журнал."""
    st.title("🧭 Состояние задачи · конечный автомат")
    st.caption(
        "Задача проходит этапы planning → execution → validation → done и шаги "
        "внутри этапа. Состояние хранится в SQLite (таблицы task_states и "
        "task_transitions), подключается к системному промпту каждого запроса и "
        "обновляется по реплике («пауза», «продолжи», «подтверждаю», «вернись "
        "на предыдущий этап»)."
    )
    if active is None:
        st.info("Агентов пока нет — создайте первого в боковой панели.")
        return

    try:
        state = _current_state(active)
    except api_client.BackendError as exc:
        st.warning(f"Состояние задачи не загружено: {exc.message}")
        return
    if state is None:
        _render_create_form(active)
        return

    task_id = state["task_id"]
    stage = state["stage"]
    rollback_stage = state.get("rollback_stage")

    st.subheader("🧭 Состояние задачи")
    st.caption(
        f"Задача **{task_id}** · агент **{active.get('agent_id')}** · "
        f"обновлено **{common.fmt_time(state.get('updated_at'))}**"
    )
    st.markdown(f"**Текущий этап:** {common.TASK_STAGE_LABELS.get(stage, stage)}")
    st.markdown(f"**Текущий шаг:** `{state.get('current_step')}`")
    st.markdown(f"**Ожидаемое действие:** {state.get('expected_action') or '—'}")
    if state.get("paused_from_stage"):
        st.caption(
            f"⏸ Пауза с этапа **{state['paused_from_stage']}**: «Продолжить» "
            f"вернёт в него на шаг `{state.get('current_step')}`."
        )

    st.code(FSM_DIAGRAM)
    st.markdown(f"**Активный этап:** {common.TASK_STAGE_LABELS.get(stage, stage)}")

    col_pause, col_resume, col_next, col_back, col_done = st.columns(5)
    with col_pause:
        if st.button("⏸ Пауза", disabled=stage == "paused",
                     key=f"task_pause_{task_id}",
                     help="Сохраняет этап и шаг: продолжение вернёт их же."):
            _call(
                lambda: api_client.api_pause_task(task_id),
                "Задача поставлена на паузу.",
                "Пауза не выполнена",
            )
    with col_resume:
        if st.button("▶️ Продолжить", disabled=stage != "paused",
                     key=f"task_resume_{task_id}",
                     help="Возвращает задачу на сохранённый этап и шаг."):
            _call(
                lambda: api_client.api_resume_task(task_id),
                "Задача продолжена с сохранённого шага.",
                "Продолжение не выполнено",
            )
    with col_next:
        if st.button("⏭ Следующий шаг", disabled=not state.get("is_active"),
                     key=f"task_advance_{task_id}",
                     help="Следующий шаг этапа, а с последнего шага — следующий этап."):
            _call(
                lambda: api_client.api_advance_task(task_id),
                "Задача перешла на следующий шаг.",
                "Шаг вперёд не выполнен",
            )
    with col_back:
        if st.button("↩️ Откат на предыдущий этап", disabled=rollback_stage is None,
                     key=f"task_rollback_{task_id}",
                     help="Сбрасывает шаг на первый шаг предыдущего этапа."):
            _call(
                lambda: api_client.api_rollback_task(task_id, rollback_stage),
                f"Откат на этап {rollback_stage} выполнен.",
                "Откат не выполнен",
            )
    with col_done:
        if st.button("✅ Завершить задачу", disabled=stage == "done",
                     key=f"task_done_{task_id}",
                     help="Переводит задачу в done (шаг — finalize)."):
            _call(
                lambda: api_client.api_transition_task(
                    task_id, "done", reason="задача завершена"
                ),
                "Задача завершена.",
                "Завершение задачи не выполнено",
            )

    tabs = st.tabs(["📜 Журнал переходов", "🧩 Блок в системном промпте"])
    with tabs[0]:
        st.caption("Каждый переход: откуда, куда, причина и время.")
        try:
            entries = api_client.api_task_history(task_id).get("entries") or []
        except api_client.BackendError as exc:
            st.warning(f"Журнал не загружен: {exc.message}")
            entries = []
        if not entries:
            st.info("Журнал пуст.")
        else:
            rows = [{
                "#": index,
                "из": (f"{item.get('from_stage')}/{item.get('from_step')}"
                       if item.get("from_stage") else "— (создание)"),
                "в": f"{item.get('to_stage')}/{item.get('to_step')}",
                "причина": item.get("reason"),
                "время": common.fmt_time(item.get("created_at")),
            } for index, item in enumerate(entries, start=1)]
            st.dataframe(rows, use_container_width=True, hide_index=True)
    with tabs[1]:
        st.caption(
            "Этот блок идёт последним в системное сообщение каждого запроса "
            "агента — по нему модель понимает, с какого места продолжать."
        )
        st.code(state.get("prompt_block") or "")
