"""Раздел «👤 Профиль пользователя» дня 17 (наследовано из дня 12): выбор, форма, переключение, сравнение.

Организует CRUD профилей через API, предпросмотр блока персонализации и запуск
сравнения двух профилей на одном вопросе.
"""
from typing import List

import streamlit as st

from backend.core import config
from backend.domain.demo_profiles import DEMO_PROFILES
from backend.domain.profiles import (
    CUSTOM_INSTRUCTION_EXAMPLE, PREFERENCE_OPTIONS, ProfileValueError,
    build_profile_prompt,
)

from . import api_client, common, profile_comparison


# ================= UI: профиль пользователя (день 12) =================
NO_VALUE = "— не задано —"

# Поля preferences в порядке отображения: ключ → подпись в форме.
PREFERENCE_WIDGETS = (
    ("tone", "Стиль общения (tone)"),
    ("verbosity", "Длина ответа (verbosity)"),
    ("language", "Язык ответа (language)"),
    ("format", "Формат ответа (format)"),
)


def _split_list(raw: str) -> List[str]:
    """«политика, религия» или строки текста → список значений без дублей."""
    result: List[str] = []
    for line in str(raw or "").splitlines():
        for chunk in line.replace(";", ",").split(","):
            text = chunk.strip()
            if text and text not in result:
                result.append(text)
    return result


def _profile_payload(name: str, preferences: dict, max_length: int,
                     topics: str, disclaimers: str,
                     instructions: str) -> dict:
    """Собирает тело профиля для API из значений формы.

    «— не задано —» превращается в None: такое поле не попадает в системный
    промпт (профиль не навязывает настройку, которую пользователь не выбирал).
    """
    return {
        "name": name.strip(),
        "preferences": {
            key: (value if value != NO_VALUE else None)
            for key, value in preferences.items()
        },
        "constraints": {
            "max_response_length": int(max_length) or None,
            "forbidden_topics": _split_list(topics),
            "required_disclaimers": _split_list(disclaimers),
        },
        "custom_instructions": instructions,
    }


def _save_profile(user_id: str, payload: dict, exists: bool) -> None:
    """Сохраняет профиль (POST/PUT) и перезагружает страницу с сообщением."""
    try:
        if exists:
            result = api_client.api_update_profile(user_id, payload)
            common.flash(
                "success",
                f"Профиль **{user_id}** обновлён · {result.get('summary')} · "
                f"применён к агентам: {result.get('applied_to_agents', 0)}",
            )
        else:
            result = api_client.api_create_profile(user_id, payload)
            common.flash(
                "success",
                f"Профиль **{user_id}** создан · {result.get('summary')}",
            )
    except api_client.BackendError as exc:
        common.flash("error", f"Профиль не сохранён: {exc.message}")
    common.load_agents()
    st.session_state["chat_agent_id"] = None  # перечитаем диалог и промпт
    st.rerun()


def _render_profile_form(user_id: str, existing, key_prefix: str) -> None:
    """Форма профиля: имя, стиль, формат, длина, ограничения, инструкции."""
    data = existing or {}
    prefs = data.get("preferences") or {}
    cons = data.get("constraints") or {}
    with st.form(f"{key_prefix}_form"):
        name = st.text_input(
            "Имя для обращения", value=data.get("name") or "",
            key=f"{key_prefix}_name",
            placeholder="Илья",
            help="Если заполнено, в промпт добавится «Обращайся к пользователю "
                 "по имени: …».",
        )
        columns = st.columns(2)
        chosen: dict = {}
        for index, (field, label) in enumerate(PREFERENCE_WIDGETS):
            options = [NO_VALUE] + list(PREFERENCE_OPTIONS[field])
            current = prefs.get(field) or NO_VALUE
            chosen[field] = columns[index % 2].selectbox(
                label, options,
                index=options.index(current) if current in options else 0,
                key=f"{key_prefix}_{field}",
            )
        max_length = st.number_input(
            "Максимальная длина ответа, символов (0 — без ограничения)",
            min_value=0, max_value=config.MAX_RESPONSE_LENGTH_MAX,
            value=int(cons.get("max_response_length") or 0), step=50,
            key=f"{key_prefix}_maxlen",
        )
        topics = st.text_input(
            "Запрещённые темы (через запятую)",
            value=", ".join(cons.get("forbidden_topics") or []),
            key=f"{key_prefix}_topics", placeholder="политика, религия",
        )
        disclaimers = st.text_area(
            "Обязательные дисклеймеры (по одному в строке)",
            value="\n".join(cons.get("required_disclaimers") or []),
            height=68, key=f"{key_prefix}_disclaimers",
            placeholder="Это оценка, а не гарантия",
        )
        instructions = st.text_area(
            "Произвольные инструкции (по одной в строке)",
            value=data.get("custom_instructions") or "",
            height=110, key=f"{key_prefix}_instructions",
            placeholder=CUSTOM_INSTRUCTION_EXAMPLE,
            help="Выполняются буквально и попадают в каждый запрос. Пример: "
                 "«При запросе «напиши фичу» спавни агентов в порядке: сначала "
                 "аналитик, потом разработчик, потом тестировщик».",
        )
        saved = st.form_submit_button("💾 Сохранить профиль", type="primary")
    if saved:
        payload = _profile_payload(name, chosen, max_length, topics,
                                   disclaimers, instructions)
        _save_profile(user_id, payload, exists=existing is not None)


def _apply_demo_profile(item: dict) -> None:
    """Создаёт/обновляет готовый профиль демонстрации одним нажатием."""
    user_id = item["user_id"]
    payload = item["profile"]
    try:
        api_client.api_get_profile(user_id)
    except api_client.BackendError as exc:
        if exc.status_code != 404:
            common.flash("error", f"Профиль {user_id} недоступен: {exc.message}")
            st.rerun()
        _save_profile(user_id, payload, exists=False)
    else:
        _save_profile(user_id, payload, exists=True)


def render_profile_section(active) -> None:
    """Вкладка «👤 Профиль пользователя»: выбор, форма, переключение, сравнение."""
    st.subheader("👤 Профиль пользователя")
    st.caption(
        "Профиль применяется ко ВСЕМ запросам выбранного пользователя: "
        "системный промпт каждого запроса собирается из обращения, стиля "
        "(tone), формата (format), длины (verbosity), языка, ограничений "
        "(constraints) и произвольных инструкций (custom_instructions). "
        "Изменения действуют сразу — агент перечитывает профиль, перезапуск "
        "не нужен."
    )
    try:
        users = api_client.api_list_users()
    except api_client.BackendError as exc:
        st.error(f"Профили не загружены: {exc.message}")
        return
    by_id = {user["user_id"]: user for user in users}

    # --- выбор профиля + создание нового ---
    col_pick, col_new = st.columns([3, 2])
    with col_pick:
        selected = None
        if by_id:
            selected = st.selectbox(
                "Профиль", list(by_id),
                format_func=lambda uid: f"{uid} · {by_id[uid]['summary']}",
                key="profile_select",
            )
            st.caption(
                f"Обновлён: {common.fmt_time(by_id[selected].get('updated_at'))} · "
                f"пользователь `{by_id[selected]['user_id']}`"
            )
        else:
            st.info("Профилей пока нет. Создайте первый — он начнёт влиять на "
                    "запросы сразу, без перезапуска агентов.")
    with col_new:
        with st.form("create_profile_form", clear_on_submit=True):
            new_user_id = st.text_input(
                "Новый профиль: user_id", placeholder="ivan",
                help="Идентификатор пользователя: латиница/цифры, до 64 символов.",
            )
            create = st.form_submit_button("➕ Создать профиль")
        if create:
            user_id = new_user_id.strip()
            if not user_id:
                st.warning("Укажите user_id нового профиля.")
            else:
                _save_profile(user_id, _profile_payload(
                    "", {key: NO_VALUE for key, _ in PREFERENCE_WIDGETS},
                    0, "", "", "",
                ), exists=False)

    # --- готовые профили: один клик до демонстрации ---
    st.markdown("**⚡ Готовые профили** (создаются или обновляются одним нажатием)")
    preset_columns = st.columns(len(DEMO_PROFILES))
    for column, item in zip(preset_columns, DEMO_PROFILES):
        with column:
            if st.button(item["title"], key=f"preset_{item['user_id']}",
                         help=f"{item['expectation']} Профиль: {item['user_id']}",
                         use_container_width=True):
                _apply_demo_profile(item)

    # --- форма редактирования выбранного профиля ---
    st.divider()
    if selected is not None:
        st.markdown(f"**✏️ Редактирование профиля `{selected}`**")
        _render_profile_form(selected, by_id[selected],
                             key_prefix=f"edit_{selected}")
        col_preview, col_delete = st.columns([4, 1])
        with col_preview:
            prompt_block = _profile_prompt_preview(by_id[selected])
            if prompt_block:
                st.caption("Что уходит в системный промпт (блок профиля):")
                st.code(prompt_block, language="text")
            else:
                st.caption("Профиль пуст: в системный промпт ничего не "
                           "добавляется, агент отвечает как обычно.")
        with col_delete:
            if st.button("🗑 Удалить профиль", key=f"delete_{selected}"):
                try:
                    api_client.api_delete_profile(selected)
                except api_client.BackendError as exc:
                    common.flash("error", f"Профиль не удалён: {exc.message}")
                else:
                    common.flash("success",
                           f"Профиль **{selected}** удалён: агенты этого "
                           "пользователя снова работают без персонализации.")
                common.load_agents()
                st.rerun()
    else:
        st.caption("Выберите профиль слева, чтобы отредактировать его настройки.")

    # --- профиль активного агента и быстрое переключение ---
    if active is None or not by_id:
        return
    st.divider()
    st.markdown("**🔀 Профиль активного агента** (быстрое переключение)")
    agent_id = active["agent_id"]
    current_user = active.get("user_id", "default")
    st.caption(
        f"Агент **{active['name']}** (`{agent_id}`) использует профиль "
        f"`{current_user}`. Переключите пользователя — и следующий запрос "
        "уйдёт с другим системным промптом."
    )
    col_switch, col_apply = st.columns([3, 1])
    target = col_switch.selectbox(
        "Профиль для агента", list(by_id),
        index=list(by_id).index(current_user) if current_user in by_id else 0,
        format_func=lambda uid: f"{uid} · {by_id[uid]['summary']}",
        key=f"switch_{agent_id}",
    )
    if col_apply.button("Применить", key=f"apply_{agent_id}"):
        try:
            api_client.api_set_agent_user(agent_id, target)
        except api_client.BackendError as exc:
            common.flash("error", f"Профиль не переключён: {exc.message}")
        else:
            common.flash("success",
                   f"Агент **{active['name']}** теперь использует профиль "
                   f"`{target}`.")
        common.load_agents()
        st.session_state["chat_agent_id"] = None
        st.rerun()

    try:
        applied = api_client.api_agent_profile(agent_id)
    except api_client.BackendError as exc:
        st.caption(f"Профиль агента не получен: {exc.message}")
        return
    if applied.get("personalized"):
        st.caption(f"Применён профиль: **{applied.get('summary')}**")
        st.dataframe(
            [{"элемент": el["label"], "значение": el["value"]}
             for el in applied.get("elements") or []],
            hide_index=True, use_container_width=True,
        )
        with st.expander("Итоговый системный промпт (без блоков памяти задачи)"):
            st.code(applied.get("system_prompt") or "", language="text")
    else:
        st.info("У профиля нет заполненных полей: персонализация не "
                "применяется.")

    # --- сравнение двух профилей на одном вопросе ---
    st.divider()
    profile_comparison.render_profile_comparison(by_id)


def _profile_prompt_preview(profile: dict) -> str:
    """Блок промпта, который даст профиль (считается локально, без API).

    Вызывается та же функция, что и на бэкенде (``backend/profiles.py``): иначе
    текст предпросмотра в интерфейсе мог бы разойтись с промптом реального
    запроса.
    """
    try:
        return build_profile_prompt(
            name=profile.get("name") or "",
            preferences=profile.get("preferences"),
            constraints=profile.get("constraints"),
            custom_instructions=profile.get("custom_instructions") or "",
        ).text
    except ProfileValueError as exc:
        return f"⚠️ Настройки профиля не собираются в промпт: {exc}"
