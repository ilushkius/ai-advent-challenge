"""Раздел «📏 Инварианты» дня 14: правила проекта, их правка и проверка текста.

Единственная точка входа — ``render_invariant_panel()``: аргументов нет, потому
что инварианты глобальны (описывают проект, а не агента). Панель показывает
список правил, форму создания, блок редактирования с включением-выключением и
удалением, а также проверку произвольного текста — тем же способом, которым
агент проверяет свой ход (детерминированные правила, при неоднозначности — LLM).

Почему отдельный модуль: раздел не зависит от активного агента и не трогает
память/профиль, поэтому его данные (список инвариантов и проверка текста) не
должны смешиваться с панелями агента.
"""
import streamlit as st

from . import api_client, common


def _load() -> list:
    """Список инвариантов с бэкенда (при сбое — пустой список и предупреждение)."""
    try:
        return api_client.api_invariants() or []
    except api_client.BackendError as exc:
        st.warning(f"Инварианты не загружены: {exc.message}")
        return []


def _mutate(action, success: str, failure: str) -> None:
    """Мутирующий эндпоинт инварианта: флеш-сообщение и перерисовка страницы."""
    try:
        action()
    except api_client.BackendError as exc:
        if exc.status_code == 409:
            common.flash("error", "Инвариант с таким именем уже есть.")
        else:
            common.flash("error", f"{failure}: {exc.message}")
    else:
        common.flash("success", success)
    st.rerun()


def _render_table(invariants: list) -> None:
    """Таблица правил: имя, категория, важность и активность."""
    if not invariants:
        st.info(
            "Инвариантов пока нет — добавьте первый: он сразу попадёт в системный "
            "промпт агентов и в проверку их ответов."
        )
        return
    rows = [{
        "id": item["id"],
        "имя": item["name"],
        "категория": common.INVARIANT_CATEGORY_LABELS.get(
            item["category"], item["category"]
        ),
        "важность": common.INVARIANT_SEVERITY_LABELS.get(
            item["severity"], item["severity"]
        ),
        "активен": "✅" if item["is_active"] else "⏸ выключен",
    } for item in invariants]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_create_form() -> None:
    """Форма «➕ Добавить инвариант»: имя, категория, важность, описание."""
    with st.form(key="invariant_create_form", clear_on_submit=True):
        name = st.text_input("Имя", key="invariant_create_name")
        category = st.selectbox(
            "Категория", list(common.INVARIANT_CATEGORY_LABELS),
            key="invariant_create_category",
        )
        severity = st.selectbox(
            "Важность", list(common.INVARIANT_SEVERITY_LABELS),
            help="hard — нарушение даёт отказ, soft — предупреждение",
            key="invariant_create_severity",
        )
        description = st.text_area(
            "Описание", key="invariant_create_description",
            help="Формулировка правила; по ней же работают детерминированные правила",
        )
        submitted = st.form_submit_button("➕ Добавить инвариант", type="primary")
    if not submitted:
        return
    if not name.strip() or not description.strip():
        st.error("Имя и описание не могут быть пустыми.")
        return
    _mutate(
        lambda: api_client.api_create_invariant({
            "name": name.strip(), "description": description.strip(),
            "category": category, "severity": severity,
        }),
        f"Инвариант «{name.strip()}» добавлен.",
        "Создание инварианта не выполнено",
    )


def _render_editor(invariants: list) -> None:
    """Блок «✏️ Редактировать»: правка полей, включение-выключение, удаление."""
    if not invariants:
        return
    st.subheader("✏️ Редактировать инвариант")
    st.caption("Ключи виджетов включают id правила — Streamlit не переиспользует состояние.")
    labels = {
        item["id"]: (
            f"#{item['id']} · {item['name']} · "
            f"{common.INVARIANT_CATEGORY_LABELS.get(item['category'], item['category'])}"
            f" · {'активен' if item['is_active'] else 'выключен'}"
        )
        for item in invariants
    }
    selected_id = st.selectbox(
        "Инвариант", list(labels), format_func=lambda key: labels[key],
        key="invariant_edit_select",
    )
    current = next(item for item in invariants if item["id"] == selected_id)

    with st.expander("✏️ Редактировать", expanded=False):
        with st.form(key=f"invariant_edit_form_{selected_id}"):
            name = st.text_input("Имя", value=current["name"],
                                 key=f"invariant_edit_name_{selected_id}")
            category = st.selectbox(
                "Категория", list(common.INVARIANT_CATEGORY_LABELS),
                index=list(common.INVARIANT_CATEGORY_LABELS).index(current["category"]),
                key=f"invariant_edit_category_{selected_id}",
            )
            severity = st.selectbox(
                "Важность", list(common.INVARIANT_SEVERITY_LABELS),
                index=list(common.INVARIANT_SEVERITY_LABELS).index(current["severity"]),
                key=f"invariant_edit_severity_{selected_id}",
            )
            description = st.text_area("Описание", value=current["description"],
                                       key=f"invariant_edit_description_{selected_id}")
            saved = st.form_submit_button("💾 Сохранить")
        if saved:
            if not name.strip() or not description.strip():
                st.error("Имя и описание не могут быть пустыми.")
            else:
                _mutate(
                    lambda: api_client.api_update_invariant(selected_id, {
                        "name": name.strip(), "description": description.strip(),
                        "category": category, "severity": severity,
                    }),
                    f"Инвариант «{name.strip()}» сохранён.",
                    "Сохранение инварианта не выполнено",
                )

    col_toggle, col_delete = st.columns(2)
    with col_toggle:
        toggle_label = "⏸ Деактивировать" if current["is_active"] else "▶️ Активировать"
        if st.button(toggle_label, key=f"invariant_toggle_{selected_id}",
                     help="Выключенное правило не уходит в промпт и не проверяется."):
            _mutate(
                lambda: api_client.api_update_invariant(
                    selected_id, {"is_active": not current["is_active"]}
                ),
                "Инвариант выключен." if current["is_active"] else "Инвариант включён.",
                "Изменение активности не выполнено",
            )
    with col_delete:
        if st.button("🗑 Удалить", key=f"invariant_delete_{selected_id}",
                     help="Удаляет правило из таблицы invariants."):
            _mutate(
                lambda: api_client.api_delete_invariant(selected_id),
                f"Инвариант «{current['name']}» удалён.",
                "Удаление инварианта не выполнено",
            )


def _render_check(invariants: list) -> None:
    """Проверка произвольного текста тем же способом, что и ход агента."""
    st.subheader("🔎 Проверка текста на инварианты")
    st.caption(
        "Проверка идёт как у агента: сначала детерминированные правила, при "
        "неоднозначности — вызов LLM."
    )
    text = st.text_area("Текст для проверки", key="invariant_check_text", height=120)
    use_llm = st.checkbox("Спрашивать LLM при неоднозначности", value=True,
                          key="invariant_check_use_llm")
    if not st.button("🔎 Проверить текст на инварианты", type="primary",
                     key="invariant_check_btn"):
        return
    if not text.strip():
        st.info("Введите текст для проверки.")
        return
    try:
        result = api_client.api_check_invariants(text, use_llm)
    except api_client.BackendError as exc:
        st.error(f"Проверка не выполнена: {exc.message}")
        return
    _render_check_result(result)


def _render_check_result(result: dict) -> None:
    """Вывод проверки: вердикт, таблица нарушений и что именно проверялось."""
    verdict = result.get("verdict")
    violations = result.get("violations") or []
    if verdict == "refusal":
        st.error("Отказ: текст нарушает hard-инварианты проекта.")
    elif verdict == "warning":
        st.warning("Предупреждение: текст нарушает soft-инварианты проекта.")
    else:
        st.success("Нарушений нет.")
    if not result.get("checked"):
        st.caption("Активных инвариантов нет: проверять нечего.")
        return
    if violations:
        rows = [{
            "инвариант": item.get("name"),
            "важность": common.INVARIANT_SEVERITY_LABELS.get(
                item.get("severity"), item.get("severity")
            ),
            "почему": item.get("reason"),
            "источник": ("правила" if item.get("source") == "deterministic"
                         else "LLM"),
        } for item in violations]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        f"Проверено правил: {len(result['checked'])} · "
        f"LLM {'использован' if result.get('llm_used') else 'не использован'}"
        + (f" · {result['note']}" if result.get("note") else "")
    )


def render_invariant_panel() -> None:
    """Раздел «📏 Инварианты»: список, создание, правка и проверка текста."""
    st.title("📏 Инварианты проекта")
    st.caption(
        "Правила, которые агент не имеет права нарушать. Хранятся отдельно от "
        "диалога — в своей таблице `invariants`, подставляются блоком в "
        "системный промпт каждого запроса. Нарушение hard-инварианта — отказ, "
        "soft — предупреждение, но решение предлагается."
    )
    invariants = _load()
    if not invariants:
        st.info("Инвариантов пока нет — добавьте первый: он сразу попадёт в промпт агентов.")
    else:
        category = st.selectbox(
            "Категория", ["все"] + list(common.INVARIANT_CATEGORY_LABELS),
            format_func=lambda key: (
                "все" if key == "все" else common.INVARIANT_CATEGORY_LABELS[key]
            ),
            key="invariant_filter_category",
        )
        active_only = st.checkbox("только активные", key="invariant_filter_active")
        shown = [
            item for item in invariants
            if (category == "все" or item["category"] == category)
            and (item["is_active"] or not active_only)
        ]
        _render_table(shown)

    st.subheader("➕ Добавить инвариант")
    _render_create_form()
    _render_editor(invariants)
    _render_check(invariants)
