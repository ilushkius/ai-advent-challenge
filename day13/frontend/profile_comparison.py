"""Сравнение двух профилей дня 13 (наследовано из дня 12): один вопрос, два временных агента, два ответа.

Показывает, как один и тот же запрос отвечается при разных профилях, и убирает
временных агентов за собой.
"""
import streamlit as st

from backend.domain.demo_profiles import DEMO_PROFILES, DEMO_QUESTION

from . import api_client


def _run_profile_comparison(question: str, first: str, second: str) -> dict:
    """Задаёт ОДИН вопрос двум профилям на временных агентах.

    Каждый профиль получает своего агента: общий агент «помнил» бы ответ для
    первого профиля, и второй отвечал бы, видя его ответ, — сравнение было бы
    нечестным. Агенты удаляются после прогона, чтобы не мусорить в БД.
    """
    result = {"question": question, "profiles": {}}
    for user_id in (first, second):
        entry: dict = {"user_id": user_id}
        try:
            info = api_client.api_create_agent({
                "name": f"Сравнение профилей · {user_id}",
                "user_id": user_id,
            })
        except api_client.BackendError as exc:
            entry["error"] = f"Агент не создан: {exc.message}"
            result["profiles"][user_id] = entry
            continue
        agent_id = info["agent_id"]
        try:
            record = api_client.api_generate(agent_id, question)
        except api_client.BackendError as exc:
            entry["error"] = exc.message
        else:
            entry.update({
                "answer": record.get("response") or "",
                "system_prompt": record.get("system_prompt") or "",
                "applied": record.get("profile") or {},
                "usage": record.get("usage") or {},
                "duration_sec": record.get("duration_sec"),
            })
        finally:
            try:
                api_client.api_delete_agent(agent_id)
            except api_client.BackendError:
                pass  # временный агент остался — не повод терять результат
        result["profiles"][user_id] = entry
    return result


def render_profile_comparison(by_id: dict) -> None:
    """Сравнение двух профилей: один вопрос, два временных агента, два ответа."""
    st.markdown("**📊 Сравнение двух профилей на одном вопросе**")
    st.caption("Создаются два временных агента (по одному на профиль), им "
               "задаётся один и тот же вопрос, агенты удаляются. Так разница "
               "ответов объясняется только профилем, а не историей диалога.")
    user_ids = list(by_id)
    if len(user_ids) < 2:
        st.info("Нужно минимум два профиля: нажмите «Строгий технический» и "
                "«Дружелюбный наставник» выше.")
        return
    # По умолчанию сравниваем пару с противоположными настройками из
    # demo_profiles (если такие профили созданы): так демо-прогон сразу
    # показывает максимальную разницу.
    demo_ids = [item["user_id"] for item in DEMO_PROFILES
                if item["user_id"] in by_id]
    default_first, default_second = (
        (demo_ids[0], demo_ids[1]) if len(demo_ids) >= 2
        else (user_ids[0], user_ids[1])
    )
    col_a, col_b = st.columns(2)
    first = col_a.selectbox(
        "Профиль A", user_ids, index=user_ids.index(default_first),
        format_func=lambda uid: f"{uid} · {by_id[uid]['summary']}",
        key="cmp_first",
    )
    second = col_b.selectbox(
        "Профиль B", user_ids, index=user_ids.index(default_second),
        format_func=lambda uid: f"{uid} · {by_id[uid]['summary']}",
        key="cmp_second",
    )
    st.session_state.setdefault("cmp_question", DEMO_QUESTION)
    question = st.text_area("Вопрос обоим профилям", height=68,
                            key="cmp_question")
    if st.button("🚀 Спросить оба профиля", type="primary", key="cmp_run"):
        if not question.strip():
            st.warning("Введите вопрос.")
        elif first == second:
            st.warning("Выберите два разных профиля.")
        else:
            with st.spinner("🤖 Два запроса к DeepSeek… это занимает "
                            "несколько секунд"):
                st.session_state["profile_compare"] = _run_profile_comparison(
                    question.strip(), first, second
                )

    comparison = st.session_state.get("profile_compare")
    if not comparison:
        return
    st.caption(f"Вопрос: _{comparison['question']}_")
    columns = st.columns(len(comparison["profiles"]))
    for column, (user_id, entry) in zip(columns,
                                        comparison["profiles"].items()):
        profile = by_id.get(user_id) or {}
        with column:
            st.markdown(f"**{user_id}**")
            st.caption(profile.get("summary") or "")
            if entry.get("error"):
                st.error(entry["error"])
                continue
            usage = entry.get("usage") or {}
            st.caption(
                f"токены: {usage.get('total_tokens', '—')} · "
                f"{entry.get('duration_sec') or 0:.2f} с"
            )
            st.markdown(entry.get("answer") or "_(пустой ответ)_")
            applied = entry.get("applied") or {}
            if applied.get("elements"):
                st.caption("Что повлияло на ответ:")
                st.dataframe(
                    [{"элемент": el["label"], "значение": el["value"]}
                     for el in applied["elements"]],
                    hide_index=True, use_container_width=True,
                )
            with st.expander("Системный промпт запроса"):
                st.code(entry.get("system_prompt") or "", language="text")
