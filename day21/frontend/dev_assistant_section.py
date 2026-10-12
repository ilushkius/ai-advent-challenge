"""Раздел «🧑‍💻 Ассистент разработчика (Day 31)»: вопросы ``/help`` по проекту.

Что видно в разделе и зачем именно так.

- **Слева — диалог.** Вопрос и ответ лежат парами в состоянии сессии: ответ
  приходит с источниками документации и списком вызванных MCP-инструментов, и оба
  блока раскрываются ПОД ответом, а не уезжают в отдельную вкладку — иначе
  «на чём основан ответ» не проверить глазами.
- **Кнопки-подсказки** ставят вопрос в поле ввода И сразу отправляют его: пять
  вопросов демо покрывают обе ветки службы (документация и git), и щёлкать «Send»
  после подсказки — лишний шаг.
- **Справа — панель процесса.** Каталог инструментов dev-сервера и текущая
  ветка: и то и другое — состояние процесса, а не свойство агента, и видно без
  вопроса модели. Недоступный бэкенд или MCP-сервер показываются подписью причины,
  а не падением раздела.

Переключатель провайдера — ``llm_provider.PICKER_PROVIDERS`` (DeepSeek первым):
ответ идёт в облако по умолчанию, локальная Ollama — второй провайдер.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import dev_assistant, llm_provider

from . import api_client, dev_assistant_api

#: Ключи состояния: диалог, панели и черновик вопроса живут между перезапусками
#: скрипта Streamlit; сбрасываются только кнопкой «Очистить диалог».
CHAT_KEY = "dev_assistant_chat"
TOOLS_KEY = "dev_assistant_tools"
GIT_KEY = "dev_assistant_git"
PROVIDER_KEY = "dev_assistant_provider"
DRAFT_KEY = "dev_assistant_draft"
SEND_KEY = "dev_assistant_send"
TOOLS_REFRESH_KEY = "dev_assistant_tools_refresh"
CLEAR_KEY = "dev_assistant_clear"

#: Сколько символов описания инструмента показывать в списке.
DESCRIPTION_LIMIT = 140


def render_dev_assistant_section() -> None:
    """Раздел целиком: подсказки, провайдер, диалог слева и панели справа."""
    st.session_state.setdefault(CHAT_KEY, [])
    st.title("🧑‍💻 /help — ассистент разработчика (Day 31)")
    st.caption("Ответ по документации проекта (фрагменты RAG-корпуса) и по состоянию "
               "репозитория (инструменты MCP-сервера ``dev_server``): в ответе видны "
               "источники, вызванные инструменты и текущая ветка.")
    _hints()
    provider = st.radio("Провайдер ответа", list(llm_provider.PICKER_PROVIDERS),
                        format_func=llm_provider.label, index=0, horizontal=True,
                        key=PROVIDER_KEY)
    left, right = st.columns([2, 1])
    with left:
        _chat(provider)
    with right:
        _panel()


def _hints() -> None:
    """Пять примеров вопросов: кнопка ставит вопрос в поле ввода и отправляет его."""
    st.caption("Примеры: " + " · ".join(dev_assistant.DEMO_QUESTIONS))
    columns = st.columns(len(dev_assistant.DEMO_QUESTIONS))
    for position, (column, question) in enumerate(zip(columns,
                                                      dev_assistant.DEMO_QUESTIONS)):
        label = question.replace("/help ", "")
        with column:
            if st.button(label, key=f"dev_q_{position}",
                         type="primary" if position == 0 else "secondary"):
                st.session_state[DRAFT_KEY] = question
                _ask(question, st.session_state.get(PROVIDER_KEY)
                     or llm_provider.PROVIDER_DEEPSEEK)


def _chat(provider: str) -> None:
    """Диалог раздела: пары «вопрос — ответ» с источниками и инструментами."""
    st.subheader("💬 Вопросы и ответы")
    history = st.session_state[CHAT_KEY]
    if not history:
        st.info("Задайте вопрос о проекте — например, нажмите подсказку выше или "
                "напишите `/help как запустить тесты?`.")
    for record in history:
        _turn(record)
    question = st.text_input("Вопрос (/help …)", key=DRAFT_KEY,
                             placeholder="/help что в текущей git-ветке?")
    if st.button("Отправить", type="primary", key=SEND_KEY):
        _ask(question, provider)


def _turn(record: dict) -> None:
    """Одна пара «вопрос — ответ»: текст, предупреждения, источники и инструменты.

    Текст ответа выводится как markdown БЕЗ ``common.esc``: Streamlit сам экранирует
    HTML (``unsafe_allow_html`` по умолчанию выключен), а ``esc`` превращает переносы
    строк в ``<br>`` — после первого такого переноса markdown перестаёт быть markdown,
    и модель, ответившая заголовками и списками, показывает их «как есть».
    """
    with st.chat_message("user"):
        st.markdown(record.get("question") or "")
    with st.chat_message("assistant"):
        st.markdown(record.get("answer") or "")
        for warning in record.get("warnings") or []:
            st.warning(warning)
        st.caption(f"Тип вопроса: {dev_assistant.KIND_LABELS.get(record.get('question_type'), '—')}"
                   f" · провайдер: {llm_provider.label(record.get('provider') or '')}"
                   f" · время: {int(record.get('duration_ms') or 0) / 1000:.2f} с")
        _sources(record.get("sources") or [])
        _tools_used(record.get("mcp_tools_used") or [])


def _sources(sources: list) -> None:
    """Раскрывашка «📚 Источники»: файл, секция и балл каждого фрагмента."""
    with st.expander(f"📚 Источники ({len(sources)})"):
        if not sources:
            st.caption("Источников нет: вопрос не потребовал документации.")
            return
        st.dataframe(
            [{"источник": item.get("source") or "—", "секция": item.get("section") or "—",
              "балл": item.get("score")} for item in sources],
            hide_index=True, use_container_width=True,
        )


def _tools_used(used: list) -> None:
    """Раскрывашка «🛠 MCP-инструменты»: что вызвали, чем кончилось и сколько заняло."""
    with st.expander(f"🛠 MCP-инструменты ({len(used)})"):
        if not used:
            st.caption("MCP-инструменты не вызывались: вопрос про документацию.")
            return
        st.dataframe(
            [{"инструмент": item.get("tool") or "—",
              "результат": "ок" if item.get("ok") else (item.get("error") or "ошибка"),
              "время, мс": item.get("duration_ms")} for item in used],
            hide_index=True, use_container_width=True,
        )


def _ask(question: str, provider: str) -> None:
    """Отправляет вопрос: ответ добавляется в диалог, состояние перерисовывается.

    Неудачный запрос в диалог не попадает — иначе в истории осталась бы пара без
    ответа, и непонятно, был вопрос отправлен или только набран.
    """
    text = (question or "").strip()
    if not text:
        st.warning("Пустой вопрос: напишите «/help <вопрос>».")
        return
    try:
        with st.spinner("Ассистент собирает контекст и ждёт модель…"):
            record = dev_assistant_api.api_dev_help(text, provider)
    except api_client.BackendError as exc:
        st.error(f"Ответ не получен: {exc.message}")
        return
    st.session_state[CHAT_KEY] = [*st.session_state[CHAT_KEY], record]
    st.rerun()


def _panel() -> None:
    """Панель раздела: инструменты dev-сервера, состояние git и очистка диалога."""
    st.subheader("🛠 MCP-инструменты")
    tools = _data(TOOLS_KEY, dev_assistant_api.api_dev_tools,
                  refresh=st.button("🔄 Обновить", key=TOOLS_REFRESH_KEY))
    _tools_catalog(tools)
    st.subheader("🌱 Git")
    git = _data(GIT_KEY, dev_assistant_api.api_dev_git_context)
    _git_state(git)
    if st.button("🧹 Очистить диалог", key=CLEAR_KEY):
        st.session_state[CHAT_KEY] = []
        st.rerun()


def _data(key: str, fetch, refresh: bool = False) -> dict:
    """Данные панели: из состояния сессии, а по кнопке или при первом проходе — запросом.

    Ошибка бэкенда тоже кладётся в состояние: раздел показывает причину подписью и
    не дёргает запрос на каждой перерисовке.
    """
    if refresh or key not in st.session_state:
        try:
            st.session_state[key] = fetch()
        except api_client.BackendError as exc:
            st.session_state[key] = {"error": exc.message}
    return st.session_state.get(key) or {}


def _tools_catalog(tools: dict) -> None:
    """Список инструментов сервера: имя, описание и причина отказа подключения."""
    if tools.get("error"):
        st.caption(f"Сервер недоступен: {tools['error']}")
        return
    st.caption(f"Сервер {tools.get('server') or 'dev_server'}: инструментов "
               f"{int(tools.get('count') or 0)}")
    for tool in tools.get("tools") or []:
        name = tool.get("name") or "—"
        st.markdown(f"**`{name}`**")
        st.caption(_short(tool.get("description")))


def _git_state(git: dict) -> None:
    """Состояние репозитория: ветка, коммит и число изменённых файлов."""
    if git.get("error"):
        st.caption(f"Git недоступен: {git['error']}")
        return
    st.markdown(f"**Ветка:** `{git.get('branch') or '—'}`")
    st.caption(f"Коммит: {_short(git.get('last_commit'), 80) or '—'}")
    st.caption(f"Изменённых файлов: {len(git.get('modified_files') or [])}"
               + ("" if git.get("clean") else " (дерево не чистое)"))


def _short(text: object, limit: int = DESCRIPTION_LIMIT) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"
