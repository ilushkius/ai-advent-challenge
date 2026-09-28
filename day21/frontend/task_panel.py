"""Раздел «🧭 Состояние задачи» дня 17: этап, шаг, переходы и журнал попыток.

Единственная точка входа — ``render_task_panel(active)``: показывает состояние
активной задачи агента (этап, шаг, ожидаемое действие, допустимые переходы),
схему графа, блок переходов и флагов (``frontend/task_transitions.py``) и журнал
в двух разрезах — состоявшиеся переходы и отклонённые попытки. Если состояния у
активной задачи ещё нет, панель предлагает его завести.
"""
import streamlit as st

from . import api_client, common, task_transitions

# Схема графа допуска в виде текста: библиотек для диаграмм в зависимостях дня
# нет, а ASCII читается и в браузере, и в отчёте. Единственный источник правды о
# переходах — backend/domain/task_state_machine.py: здесь та же картина словами.
FSM_DIAGRAM = "\n".join([
    "прямой ход:    planning -> execution -> validation -> done",
    "откат:         execution -> planning;  validation -> execution",
    "пауза:         planning|execution|validation -> paused",
    "возобновление: paused -> planning|execution|validation",
    "терминал:      done -> переходов нет",
    "guards:        planning->execution: plan_approved",
    "               execution->validation: implementation_complete",
    "               validation->done: validation_passed",
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


def _render_create_form(active) -> None:
    """Форма заведения состояния для активной задачи агента."""
    agent_id = active.get("agent_id")
    st.info(
        f"Состояние задачи не заведено. Активная задача агента — "
        f"`{active.get('task_id')}`; создание сделает её активной и подключит "
        "блок состояния к системному промпту каждого запроса."
    )
    # Ключи виджетов Streamlit глобальны для скрипта, а не локальны контейнеру:
    # форма боковой панели (sidebar.py) уже занимает `task_create_form_*`, поэтому
    # у формы состояния своё пространство имён — иначе StreamlitDuplicateElementKey.
    with st.form(key=f"task_state_create_{agent_id}"):
        task_id = st.text_input("Новая задача (task_id)",
                                value=active.get("task_id", "default"),
                                key=f"task_state_new_id_{agent_id}")
        stage = st.selectbox("Начальный этап", START_STAGES,
                             key=f"task_state_stage_{agent_id}")
        submitted = st.form_submit_button("➕ Создать задачу", type="primary",
                                          key=f"task_state_create_btn_{agent_id}")
    if not submitted:
        return
    clean = task_id.strip()
    if not clean:
        st.error("task_id не может быть пустым.")
        return
    common.run_task_action(
        lambda: api_client.api_create_task(agent_id, clean, stage),
        f"Задача {clean} заведена на этапе {stage}.",
        "Создание задачи не выполнено",
    )


def render_task_panel(active) -> None:
    """Раздел «🧭 Состояние задачи»: состояние, граф, переходы, флаги и журнал."""
    st.title("🧭 Состояние задачи · контролируемые переходы")
    st.caption(
        "Задача проходит этапы planning → execution → validation → done и шаги "
        "внутри этапа. Куда задачу пускают правила допуска (граф этапов плюс "
        "флаги-согласования), решает бэкенд: панель гасит недоступные переходы и "
        "показывает причину отказа. Состояние хранится в SQLite (task_states и "
        "task_transitions), подключается к системному промпту каждого запроса и "
        "меняется по реплике («пауза», «продолжи», «подтверждаю»)."
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

    allowed = state.get("allowed_next") or []
    st.markdown(
        "**Допустимые следующие этапы:** "
        + (", ".join(f"`{item}`" for item in allowed)
           if allowed else "нет — переходов из этого этапа не объявлено")
    )
    task_transitions.render_transitions(state)

    try:
        entries = api_client.api_task_history(task_id).get("entries") or []
    except api_client.BackendError as exc:
        st.warning(f"Журнал не загружен: {exc.message}")
        entries = []
    accepted = [item for item in entries if item.get("accepted", True)]
    rejected = [item for item in entries if not item.get("accepted", True)]

    tabs = st.tabs([
        "📜 Журнал переходов",
        "🚫 Попытки недопустимых переходов",
        "🧩 Блок в системном промпте",
    ])
    with tabs[0]:
        st.caption("Каждый состоявшийся переход: откуда, куда, причина и время.")
        if not accepted:
            st.info("Журнал пуст.")
        else:
            rows = [{
                "#": index,
                "из": (f"{item.get('from_stage')}/{item.get('from_step')}"
                       if item.get("from_stage") else "— (создание)"),
                "в": f"{item.get('to_stage')}/{item.get('to_step')}",
                "причина": item.get("reason"),
                "время": common.fmt_time(item.get("created_at")),
            } for index, item in enumerate(accepted, start=1)]
            st.dataframe(rows, use_container_width=True, hide_index=True)
    with tabs[1]:
        st.caption(
            "Попытки, отклонённые правилами допуска: состояние задачи они не "
            "меняли, но причина отказа сохранена — видно, что именно пробовали "
            "сделать и почему нельзя."
        )
        if not rejected:
            st.info("Отклонённых попыток нет.")
        else:
            rows = [{
                "#": index,
                "этап": item.get("from_stage"),
                "шаг": item.get("from_step"),
                "цель": item.get("to_stage") or "— (этап не назван)",
                "причина отказа": item.get("reason"),
                "время": common.fmt_time(item.get("created_at")),
            } for index, item in enumerate(rejected, start=1)]
            st.dataframe(rows, use_container_width=True, hide_index=True)
    with tabs[2]:
        st.caption(
            "Этот блок идёт последним в системное сообщение каждого запроса "
            "агента — по нему модель понимает, с какого места продолжать и куда "
            "переходить нельзя."
        )
        st.code(state.get("prompt_block") or "")
