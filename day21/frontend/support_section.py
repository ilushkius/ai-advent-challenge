"""Раздел «🎧 Поддержка пользователей (Day 33)»: вопрос по FAQ, профилю и тикету.

Что видно в разделе и зачем именно так.

- **Слева — выбор клиента и диалог.** Селекторы клиента и тикета наполняются из
  MCP-сервера поддержки (``support_server``), а не из константного списка id:
  каталог клиентов и их тикеты — данные сервиса, и раздел показывает именно то, что
  видит служба. Пары «вопрос — ответ» лежат в состоянии сессии, а источники,
  контекст клиента и вызовы инструментов раскрываются ПОД ответом — иначе «на чём
  основан ответ» не проверить глазами.
- **Карточка контекста над полем вопроса.** Выбранный тикет показывается целиком в
  одной строке (тема, статус, приоритет, последнее сообщение): видно, какой именно
  контекст уйдёт в промпт, ДО отправки вопроса. Это отличает раздел от чата: вопрос
  клиента без его тикета поддержке бесполезен.
- **Кнопки-подсказки** ставят вопрос в поле ввода И сразу отправляют его: пять
  сценариев демо покрывают все ветки службы (тикет, профиль, оба вместе и общий
  вопрос), и щёлкать «Отправить» после подсказки — лишний шаг.
- **Справа — панель процесса.** Каталог клиентов, кнопка обновления и очистка
  диалога: сервер поддержки поднимается лениво, поэтому его состояние показывается
  подписью причины, а не падением раздела.

Переключатель провайдера — ``llm_provider.PICKER_PROVIDERS`` (DeepSeek первым):
ответ идёт в облако по умолчанию, локальная Ollama — второй провайдер.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import llm_provider, support

from . import api_client, support_api

#: Ключи состояния: диалог, кэши каталога и тикетов, черновик вопроса и панели.
#: Живут между перезапусками скрипта Streamlit, сбрасываются кнопками раздела.
CHAT_KEY = "support_chat"
USERS_KEY = "support_users"
TICKETS_KEY = "support_tickets"
TICKETS_USER_KEY = "support_tickets_user"
USER_ID_KEY = "support_user_id"
TICKET_ID_KEY = "support_ticket_id"
PROVIDER_KEY = "support_provider"
DRAFT_KEY = "support_draft"
SEND_KEY = "support_send"
CLEAR_KEY = "support_clear"
USERS_REFRESH_KEY = "support_users_refresh"
#: Кэш полного тикета для карточки контекста: список тикетов отдаёт только темы,
#: а карточке нужно последнее сообщение — его приносит отдельный запрос.
CARD_KEY = "support_ticket_card"

#: Значение «без выбора» в обоих селекторах.
NONE_OPTION = "—"
#: Пределы подписей: вопрос в кнопке-подсказке и сообщение в карточке тикета.
QUESTION_LIMIT = 200
MESSAGE_LIMIT = 160


def render_support_section() -> None:
    """Раздел целиком: подсказки, провайдер, селекторы и диалог слева, панель справа."""
    st.session_state.setdefault(CHAT_KEY, [])
    st.title("🎧 Поддержка пользователей (Day 33)")
    st.caption("Ответ по документации поддержки (FAQ, разборы симптомов, справочник API "
               "из RAG-корпуса) и по контексту клиента: профиль и тикет приходят из "
               f"MCP-сервера ``{support.SUPPORT_SERVER_NAME}``. В ответе видны источники, "
               "контекст клиента и вызванные инструменты.")
    _hints()
    provider = st.radio("Провайдер ответа", list(llm_provider.PICKER_PROVIDERS),
                        format_func=llm_provider.label, index=0, horizontal=True,
                        key=PROVIDER_KEY)
    left, right = st.columns([2, 1])
    with right:
        # Панель рисуется первой: её кнопки меняют состояние кэшей, которое читает
        # левая колонка на том же проходе («Обновить» и «Очистить диалог»).
        refresh, clear = _panel(_user_cache())
    if refresh:
        st.session_state.pop(USERS_KEY, None)
        st.rerun()
    if clear:
        st.session_state[CHAT_KEY] = []
        st.rerun()
    with left:
        users = list(_user_cache().get("users") or [])
        user_id = _user_picker(users)
        tickets = _tickets(user_id)
        ticket_id = _ticket_picker(tickets)
        _context(users, user_id, ticket_id)
        _chat(provider, user_id, ticket_id)


def _hints() -> None:
    """Пять сценариев демо: кнопка ставит вопрос в поле ввода и отправляет его."""
    questions = [item["question"] for item in support.DEMO_SCENARIOS]
    st.caption("Примеры: " + " · ".join(questions))
    columns = st.columns(len(support.DEMO_SCENARIOS))
    for position, (column, item) in enumerate(zip(columns, support.DEMO_SCENARIOS)):
        with column:
            if st.button(_short(item["label"], QUESTION_LIMIT), key=f"support_q_{position}",
                         type="primary" if position == 0 else "secondary",
                         help=item["question"]):
                st.session_state[DRAFT_KEY] = item["question"]
                _ask(item["question"],
                     st.session_state.get(PROVIDER_KEY) or llm_provider.PROVIDER_DEEPSEEK,
                     _selected(USER_ID_KEY), _selected(TICKET_ID_KEY))


def _user_cache() -> dict:
    """Кэш каталога клиентов: запрос при первом проходе и после сброса кэша.

    Сбой бэкенда тоже кладётся в состояние: панель показывает причину подписью и не
    дёргает запрос на каждой перерисовке. Кнопка «🔄 Обновить» сбрасывает ключ и
    вызывает `st.rerun`, поэтому следующий проход делает запрос заново.
    """
    if USERS_KEY not in st.session_state:
        try:
            st.session_state[USERS_KEY] = support_api.api_support_users()
        except api_client.BackendError as exc:
            st.session_state[USERS_KEY] = {"count": 0, "users": [], "error": exc.message}
    return st.session_state.get(USERS_KEY) or {}


def _tickets(user_id: str) -> list:
    """Тикеты выбранного клиента: кэш перезапрашивается при смене клиента."""
    if not user_id:
        st.session_state[TICKETS_KEY] = {"tickets": [], "count": 0, "error": ""}
        st.session_state[TICKETS_USER_KEY] = ""
        return []
    if st.session_state.get(TICKETS_USER_KEY) != user_id or TICKETS_KEY not in st.session_state:
        try:
            data = support_api.api_support_tickets(user_id)
        except api_client.BackendError as exc:
            data = {"tickets": [], "count": 0, "error": exc.message}
        st.session_state[TICKETS_KEY] = data
        st.session_state[TICKETS_USER_KEY] = user_id
    data = st.session_state.get(TICKETS_KEY) or {}
    if data.get("error"):
        st.caption(f"Тикеты клиента не загружены: {data['error']}")
    return list(data.get("tickets") or [])


def _user_picker(users: list) -> str:
    """Селектор клиента: подпись «id — имя (тариф)», плюс вариант «без пользователя»."""
    labels = {NONE_OPTION: "— без пользователя —"}
    options = [NONE_OPTION]
    for item in users:
        key = str(item.get("id") or "")
        if not key:
            continue
        options.append(key)
        labels[key] = (f"{key} — {item.get('name') or '—'} ({item.get('plan') or '—'})")
    value = st.selectbox("Пользователь", options,
                         format_func=lambda option: labels.get(option, option), key=USER_ID_KEY)
    return "" if value == NONE_OPTION else str(value)


def _ticket_picker(tickets: list) -> str:
    """Селектор тикета: подпись «id — тема (статус, приоритет)».

    Выбранный тикет сбрасывается ДО создания виджета, если его больше нет в списке
    (клиент сменился): иначе Streamlit оставил бы выбор, которого нет в опциях.
    """
    labels = {NONE_OPTION: "— без тикета —"}
    options = [NONE_OPTION]
    for item in tickets:
        key = str(item.get("id") or "")
        if not key:
            continue
        options.append(key)
        labels[key] = (f"{key} — {_short(item.get('subject'), QUESTION_LIMIT)} "
                       f"({item.get('status') or '—'}, {item.get('priority') or '—'})")
    if st.session_state.get(TICKET_ID_KEY) not in options:
        st.session_state.pop(TICKET_ID_KEY, None)
    value = st.selectbox("Тикет", options,
                         format_func=lambda option: labels.get(option, option), key=TICKET_ID_KEY)
    return "" if value == NONE_OPTION else str(value)


def _context(users: list, user_id: str, ticket_id: str) -> None:
    """Карточка контекста над полем вопроса: профиль подписью, тикет — плашкой.

    Показывается то, что уйдёт в промпт: клиент, его тариф и последнее сообщение
    выбранного тикета. Так вопрос задаётся с открытыми глазами, а не «на удачу».
    """
    if user_id:
        user = next((item for item in users if str(item.get("id")) == user_id), {})
        st.caption(f"👤 {user.get('name') or user_id} · тариф {user.get('plan') or '—'} · "
                   f"регистрация {user.get('registered_at') or '—'}")
    if not ticket_id:
        return
    card = _ticket_card(ticket_id)
    if card.get("error"):
        st.warning(f"Тикет {ticket_id} не загружен: {card['error']}")
        return
    ticket = card.get("ticket") or {}
    messages = ticket.get("messages") or [{}]
    st.info(f"**Контекст тикета:** {ticket.get('id') or ticket_id} · "
            f"{_short(ticket.get('subject'), QUESTION_LIMIT) or '—'} · "
            f"{ticket.get('status') or '—'} · {ticket.get('priority') or '—'} · "
            f"последнее сообщение: «{_short(messages[-1].get('text'), MESSAGE_LIMIT)}»")


def _ticket_card(ticket_id: str) -> dict:
    """Полный тикет выбранного клиента из кэша: карточка контекста над вопросом."""
    cached = st.session_state.get(CARD_KEY) or {}
    if cached.get("id") != ticket_id:
        try:
            cached = {"id": ticket_id, "ticket": support_api.api_support_ticket(ticket_id),
                      "error": ""}
        except api_client.BackendError as exc:
            cached = {"id": ticket_id, "ticket": {}, "error": exc.message}
        st.session_state[CARD_KEY] = cached
    return cached


def _chat(provider: str, user_id: str, ticket_id: str) -> None:
    """Диалог раздела: пары «вопрос — ответ» и поле ввода с кнопкой отправки."""
    st.subheader("💬 Вопросы и ответы")
    history = st.session_state[CHAT_KEY]
    if not history:
        st.info("Задайте вопрос клиента — например, нажмите подсказку выше или выберите "
                "клиента и тикет, чтобы ответ опирался на его обращение.")
    for record in history:
        _turn(record)
    question = st.text_input("Вопрос", key=DRAFT_KEY,
                             placeholder="Почему не работает авторизация?")
    if st.button("Отправить", type="primary", key=SEND_KEY):
        _ask(question, provider, user_id, ticket_id)


def _turn(record: dict) -> None:
    """Одна пара «вопрос — ответ»: текст, предупреждения, источники и контекст.

    Текст ответа выводится как markdown БЕЗ экранирования: Streamlit сам экранирует
    HTML (``unsafe_allow_html`` по умолчанию выключен), а ручное экранирование
    превратило бы переносы строк в ``<br>`` — и markdown перестал бы быть markdown.
    """
    with st.chat_message("user"):
        st.markdown(record.get("question") or "")
    with st.chat_message("assistant"):
        st.markdown(record.get("answer") or "")
        for warning in record.get("warnings") or []:
            st.warning(warning)
        st.caption(f"провайдер: {llm_provider.label(record.get('provider') or '')}"
                   f" · время: {int(record.get('duration_ms') or 0) / 1000:.2f} с")
        _sources(record.get("sources") or [])
        _user_context(record.get("user_context"))
        _ticket_context(record.get("ticket_context"))
        _tools_used(record.get("mcp_tools_used") or [])


def _sources(sources: list) -> None:
    """Раскрывашка «📚 Источники»: файл, секция и балл каждого фрагмента."""
    with st.expander(f"📚 Источники ({len(sources)})"):
        if not sources:
            st.caption("Источников нет: поиск по документации поддержки ничего не нашёл.")
            return
        st.dataframe(
            [{"источник": item.get("source") or "—", "секция": item.get("section") or "—",
              "балл": item.get("score")} for item in sources],
            hide_index=True, use_container_width=True,
        )


def _user_context(user: dict | None) -> None:
    """Раскрывашка «👤 Контекст пользователя»: таблица «поле — значение»."""
    with st.expander("👤 Контекст пользователя"):
        if not user:
            st.caption(support.CONTEXT_UNAVAILABLE)
            return
        st.dataframe(
            [{"поле": label, "значение": user.get(field) or "—"}
             for label, field in (("id", "id"), ("имя", "name"), ("email", "email"),
                                  ("тариф", "plan"), ("регистрация", "registered_at"),
                                  ("последняя активность", "last_seen"))],
            hide_index=True, use_container_width=True,
        )


def _ticket_context(ticket: dict | None) -> None:
    """Раскрывашка «🎫 Контекст тикета»: тема, статус, приоритет и история сообщений."""
    with st.expander("🎫 Контекст тикета"):
        if not ticket:
            st.caption(support.CONTEXT_UNAVAILABLE)
            return
        st.markdown(f"**{ticket.get('subject') or '—'}**")
        st.caption(f"`{ticket.get('id') or '—'}` · {ticket.get('status') or '—'} · "
                   f"{ticket.get('priority') or '—'} · {ticket.get('created_at') or '—'}")
        messages = ticket.get("messages") or []
        if messages:
            st.dataframe(
                [{"автор": item.get("author") or "—",
                  "время": item.get("timestamp") or "—",
                  "текст": _short(item.get("text"), MESSAGE_LIMIT)} for item in messages],
                hide_index=True, use_container_width=True,
            )


def _tools_used(used: list) -> None:
    """Раскрывашка «🛠 MCP-инструменты»: что вызвали, чем кончилось и сколько заняло."""
    with st.expander(f"🛠 MCP-инструменты ({len(used)})"):
        if not used:
            st.caption("MCP-инструменты не вызывались: вопрос не потребовал контекста "
                       "клиента и раздела продукта.")
            return
        st.dataframe(
            [{"инструмент": item.get("tool") or "—",
              "результат": "ок" if item.get("ok") else (item.get("error") or "ошибка"),
              "время, мс": item.get("duration_ms")} for item in used],
            hide_index=True, use_container_width=True,
        )


def _ask(question: str, provider: str, user_id: str, ticket_id: str) -> None:
    """Отправляет вопрос: ответ добавляется в диалог, состояние перерисовывается.

    Неудачный запрос в диалог не попадает — иначе в истории осталась бы пара без
    ответа, и непонятно, был вопрос отправлен или только набран.
    """
    text = (question or "").strip()
    if not text:
        st.warning("Пустой вопрос: напишите вопрос о продукте.")
        return
    try:
        with st.spinner("Ассистент поддержки собирает контекст и ждёт модель…"):
            record = support_api.api_support_ask(text, user_id, ticket_id, provider)
    except api_client.BackendError as exc:
        st.error(f"Ответ не получен: {exc.message}")
        return
    st.session_state[CHAT_KEY] = [*st.session_state[CHAT_KEY], {"question": text, **record}]
    st.rerun()


def _panel(data: dict) -> tuple:
    """Панель раздела: клиенты MCP-сервера, обновление каталога и очистка диалога."""
    st.subheader("🧩 MCP-сервер поддержки")
    users = list(data.get("users") or [])
    if data.get("error"):
        st.caption(f"Сервер недоступен: {data['error']}")
    else:
        st.caption(f"Сервер {support.SUPPORT_SERVER_NAME}: клиентов "
                   f"{int(data.get('count') or len(users))}")
    for user in users:
        st.markdown(f"**`{user.get('id')}`** — {user.get('name') or '—'}")
        st.caption(f"{user.get('plan') or '—'} · {user.get('email') or '—'}")
    return (st.button("🔄 Обновить", key=USERS_REFRESH_KEY),
            st.button("🧹 Очистить диалог", key=CLEAR_KEY))


def _selected(key: str) -> str:
    """Выбранное значение селектора: пустая строка для «без выбора» и до первого прохода."""
    value = st.session_state.get(key)
    return "" if value in (None, NONE_OPTION) else str(value)


def _short(text: object, limit: int = QUESTION_LIMIT) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"
