"""Блок контролируемых переходов и флагов-согласований (день 15).

Раздел «🧭 Состояние задачи» спрашивает не «что дальше», а «куда можно»: этот
модуль рисует кнопки по всем этапам, гасит недоступные и показывает причину
отказа в подсказке при наведении, а рядом — флаги-согласования (guard-условия
переходов вперёд). Правила берутся из ответа бэкенда (``allowed_next`` и
``blocked``): фронт их не повторяет, иначе две реализации правил допуска рано
или поздно разойдутся.

Единственная точка входа — ``render_transitions(state)``; панель задачи вызывает
её после карточки состояния. Мутации идут общим путём ``common.run_task_action``,
поэтому отказ правил допуска виден красным сообщением с объяснением, а не
«нажал — и ничего».
"""
import streamlit as st

from . import api_client, common


def _render_stage_buttons(state: dict) -> None:
    """Кнопки-этапы: доступные активны, недоступные погашены с причиной."""
    task_id = state["task_id"]
    stage = state["stage"]
    allowed = set(state.get("allowed_next") or [])

    st.markdown("**Переходы по этапам**")
    targets = [
        item for item in common.TASK_TRANSITION_STAGES if item != stage
    ]
    columns = st.columns(len(targets))
    for column, target in zip(columns, targets):
        with column:
            reason = common.blocked_reason(state, target)
            if st.button(
                common.stage_button_label(target),
                disabled=target not in allowed,
                key=f"task_transition_{target}_{task_id}",
                help="Переход разрешён правилами допуска." if target in allowed
                     else f"{reason} Проверьте флаги этапов ниже.",
            ):
                common.run_task_action(
                    lambda target=target: api_client.api_transition_task(
                        task_id, target
                    ),
                    f"Переход в {target} выполнен.",
                    "Переход не выполнен",
                )


def _render_blocked_reasons(state: dict) -> None:
    """Причины недоступности — словами, а не только в подсказке кнопки.

    Подсказка при наведении не видна на печатном экране и недоступна с
    телефона, поэтому причина отказа названа ещё и строкой.
    """
    blocked = state.get("blocked") or []
    if not blocked:
        st.caption("🔓 Ограничений нет: доступны все объявленные переходы.")
        return
    with st.expander("🔒 Почему часть переходов недоступна", expanded=False):
        for item in blocked:
            stage = item.get("stage", "")
            st.caption(
                f"🔒 {common.TASK_STAGE_LABELS.get(stage, stage)}: "
                f"{item.get('reason') or '—'}"
            )


def _render_step_and_pause(state: dict) -> None:
    """Кнопка «Следующий шаг» и пауза/продолжение в одном ряду."""
    task_id = state["task_id"]
    stage = state["stage"]

    column_next, column_pause = st.columns(2)
    with column_next:
        if st.button(
            "⏭ Следующий шаг",
            disabled=not state.get("is_active"),
            key=f"task_advance_{task_id}",
            help=(
                "Следующий шаг этапа, а с последнего шага — следующий этап по "
                "правилам допуска. Если этап не согласован, кнопка вернёт "
                "объяснение, какой флаг нужен."
            ),
        ):
            common.run_task_action(
                lambda: api_client.api_advance_task(task_id),
                "Задача перешла на следующий шаг.",
                "Шаг вперёд не выполнен",
            )
    with column_pause:
        if st.button(
            common.PAUSE_BUTTON_LABEL,
            disabled="paused" not in (state.get("allowed_next") or []),
            key=f"task_pause_{task_id}",
            help="Сохраняет этап и шаг: продолжение вернёт их же.",
        ):
            common.run_task_action(
                lambda: api_client.api_transition_task(task_id, "paused"),
                "Задача поставлена на паузу.",
                "Пауза не выполнена",
            )


def _render_resume(state: dict) -> None:
    """Продолжение из паузы: этап возврата либо другой доступный этап."""
    task_id = state["task_id"]
    options = list(state.get("allowed_next") or [])
    if not options:
        st.caption("⏸ Пауза без доступных этапов продолжения.")
        return

    resume_from = state.get("paused_from_stage")
    index = options.index(resume_from) if resume_from in options else 0
    st.caption(
        f"⏸ Пауза с этапа **{resume_from or '—'}**, шаг "
        f"`{state.get('current_step')}`: продолжение вернёт это место."
    )
    column_target, column_button = st.columns([3, 1])
    with column_target:
        target = st.selectbox(
            "Куда продолжить",
            options,
            index=index,
            key=f"task_resume_target_{task_id}",
            format_func=lambda value: common.TASK_STAGE_LABELS.get(value, value),
            help=(
                "По умолчанию — этап, откуда задачу поставили на паузу; другие "
                "значения доступны, потому что из этапа паузы они достижимы."
            ),
        )
    with column_button:
        if st.button("▶️ Продолжить", key=f"task_resume_{task_id}"):
            # Продолжение в СВОЙ этап возвращает то же место — ровно это обещает
            # подпись выше, поэтому идёт отдельным эндпоинтом /resume (он
            # сохраняет шаг). Прямой переход взял бы первый шаг этапа: у выбора
            # ДРУГОГО этапа семантика именно такая — начать его сначала.
            if target == resume_from:
                action = lambda: api_client.api_resume_task(task_id)
            else:
                action = lambda: api_client.api_transition_task(task_id, target)
            common.run_task_action(
                action,
                f"Задача продолжена в этап {target}.",
                "Продолжение не выполнено",
            )


def _render_flags(state: dict) -> None:
    """Флаги-согласования этапов: чекбоксы и одна кнопка сохранения.

    Значения выставляются явно: подтверждение этапа — действие пользователя, а
    не вывод из реплики, поэтому «сохранить» отправляет все три флага разом.
    """
    task_id = state["task_id"]
    context = state.get("context") or {}

    st.markdown("**Флаги этапа (guard-условия)**")
    st.caption(
        "Переход вперёд открывается только после согласования этапа: без флага "
        "правило ответит, чего не хватает."
    )
    values = {}
    columns = st.columns(len(common.TASK_FLAG_LABELS))
    for column, (flag, label) in zip(columns, common.TASK_FLAG_LABELS.items()):
        with column:
            values[flag] = st.checkbox(
                label,
                value=bool(context.get(flag)),
                key=f"task_flag_{flag}_{task_id}",
            )
    if st.button("💾 Сохранить флаги", key=f"task_flags_save_{task_id}"):
        common.run_task_action(
            lambda: api_client.api_set_task_flags(task_id, values),
            "Флаги задачи сохранены.",
            "Флаги не сохранены",
        )


def render_transitions(state: dict) -> None:
    """Блок переходов, паузы и флагов для состояния задачи."""
    _render_stage_buttons(state)
    _render_blocked_reasons(state)
    _render_step_and_pause(state)
    if state["stage"] == "paused":
        _render_resume(state)
    st.divider()
    _render_flags(state)
