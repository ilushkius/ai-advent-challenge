"""Раздел «🔎 AI-ревью кода (Day 32)»: локальный diff и реальный GitHub PR.

Что видно в разделе и зачем именно так.

- **Две вкладки по источнику diff-а.** «Локальный diff» берёт пару ref-ов, и diff с
  списком файлов приходит из MCP-сервера дня 31 (нужен живой бэкенд с этим сервером);
  «GitHub PR» берёт URL репозитория и номер PR, и то же самое читает GitHub REST API.
  Режимы различаются ровно этим, а ревью и его разметка у них общие.
- **Наружу — структура, а не текст модели.** Баги, архитектурные проблемы,
  рекомендации и риски P0–P3 выводятся таблицами и списками: свободный текст модели
  уезжает в раскрывашку «🧾 Полный ответ модели», иначе структура не читается глазами.
- **Публикация комментария — отдельный флаг** с подписью-предупреждением: без
  ``GITHUB_TOKEN`` с правом на запись комментарий не опубликуется, но ревью всё равно
  показывается, а причина отказа приходит в предупреждениях.
- **Справа — панель процесса:** готовность службы ревью и готовность GitHub (маска
  токена, остаток лимита). Обе — состояние процесса, не свойство агента; недоступный
  бэкенд показывается подписью причины, а не падением раздела.

Переключатель провайдера — ``llm_provider.PICKER_PROVIDERS`` (DeepSeek первым), как в
дне 31: ответ идёт в облако по умолчанию, локальная Ollama — второй провайдер.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import code_review, llm_provider

from . import api_client, code_review_api, common

#: Ключи состояния: результаты обоих режимов и панели живут между перезапусками скрипта.
LOCAL_RESULT_KEY = "review_local_result"
GITHUB_RESULT_KEY = "review_github_result"
PROVIDER_KEY = "code_review_provider"
BASE_KEY = "code_review_base"
HEAD_KEY = "code_review_head"
REPO_URL_KEY = "code_review_repo_url"
PR_NUMBER_KEY = "code_review_pr_number"
POST_KEY = "code_review_post_comment"
HEALTH_KEY = "review_health"
GITHUB_HEALTH_KEY = "review_github_health"


def render_code_review_section() -> None:
    """Раздел целиком: провайдер, две вкладки по источнику diff-а и панель служб."""
    st.session_state.setdefault(LOCAL_RESULT_KEY, {})
    st.session_state.setdefault(GITHUB_RESULT_KEY, {})
    st.title("🔎 AI-ревью кода (Day 32)")
    st.caption("Ревью приходит структурой: баги с файлом и строкой, архитектурные "
               "проблемы с рекомендацией, рекомендации и риски P0–P3. Контекст — "
               "фрагменты корпуса RAG (документация проекта и код изменённых файлов). "
               "Два режима: локальный diff двух ref и реальный PR из GitHub REST API.")
    provider = st.radio("Провайдер ответа", list(llm_provider.PICKER_PROVIDERS),
                        format_func=llm_provider.label, index=0, horizontal=True,
                        key=PROVIDER_KEY)
    left, right = st.columns([3, 1])
    with left:
        local_tab, github_tab = st.tabs(["🗂 Локальный diff", "🐙 GitHub PR"])
        with local_tab:
            _local_tab(provider)
        with github_tab:
            _github_tab(provider)
    with right:
        _panel()


def _local_tab(provider: str) -> None:
    """Локальный режим: пара ref-ов; diff и список файлов берёт MCP-сервер дня 31."""
    st.caption("Diff и список изменённых файлов в этом режиме берёт MCP-сервер "
               "``dev_server`` дня 31, поэтому нужен живой бэкенд с этим сервером. "
               "Готовый diff вводить не нужно — достаточно двух ref-ов.")
    base = st.text_input("Базовый ref", value="day30", key=BASE_KEY,
                         placeholder="day30")
    head = st.text_input("Ref изменения", value="day31", key=HEAD_KEY,
                         placeholder="day31")
    if st.button("Запустить ревью", type="primary", key="review_local_run"):
        _run_local(base, head, provider)
    if st.session_state.get(LOCAL_RESULT_KEY):
        _render(st.session_state[LOCAL_RESULT_KEY])


def _github_tab(provider: str) -> None:
    """Режим GitHub: URL репозитория и номер PR; публикация — по чекбоксу."""
    st.caption("Diff и список файлов приходят из GitHub REST API, локальная копия "
               "репозитория не нужна. Без ``GITHUB_TOKEN`` публичные репозитории "
               "читаются анонимно (60 запросов в час на IP).")
    url = st.text_input("URL репозитория", key=REPO_URL_KEY,
                        placeholder="https://github.com/user/repo")
    number = st.number_input("Номер PR", min_value=1, step=1, value=1,
                             key=PR_NUMBER_KEY)
    post = st.checkbox("Опубликовать комментарий", key=POST_KEY)
    if post:
        st.caption("Для публикации нужен ``GITHUB_TOKEN`` с правом "
                   "``pull requests: write``. Без него комментарий не опубликуется, "
                   "но ревью всё равно покажем, а причина попадёт в предупреждения.")
    if st.button("Запустить ревью", type="primary", key="review_github_run"):
        _run_github(url, int(number), provider, post)
    if st.session_state.get(GITHUB_RESULT_KEY):
        _render(st.session_state[GITHUB_RESULT_KEY], github=True)


def _run_local(base: str, head: str, provider: str) -> None:
    """Запускает локальное ревью: результат кладётся в состояние, страница обновляется."""
    payload = {"base": (base or "").strip(), "head": (head or "").strip(),
               "provider": provider}
    try:
        with st.spinner("Ревью идёт: поиск по корпусу и ответ модели…"):
            record = code_review_api.api_review_pr(payload)
    except api_client.BackendError as exc:
        st.error(exc.message)
        return
    st.session_state[LOCAL_RESULT_KEY] = record
    st.rerun()


def _run_github(url: str, pr_number: int, provider: str, post_comment: bool) -> None:
    """Запускает ревью PR из GitHub: с публикацией комментария при включённом флаге."""
    payload = {"repo_url": (url or "").strip(), "pr_number": int(pr_number),
               "provider": provider, "post_comment": bool(post_comment)}
    try:
        with st.spinner("Ревью идёт: GitHub, поиск по корпусу и ответ модели…"):
            record = code_review_api.api_review_github_pr(payload)
    except api_client.BackendError as exc:
        st.error(exc.message)
        return
    st.session_state[GITHUB_RESULT_KEY] = record
    st.rerun()


def _render(record: dict, github: bool = False) -> None:
    """Готовое ревью: ссылки на PR, подпись, таблицы находок, источники и полный текст."""
    for warning in record.get("warnings") or []:
        st.warning(warning)
    if github:
        _pr_links(record)
    st.caption(_caption(record, github))
    _findings(record.get("bugs") or [])
    _architecture(record.get("architecture_issues") or [])
    _recommendations(record.get("recommendations") or [])
    _risks(record.get("risks") or [])
    _sources(record.get("sources") or [])
    _tools(record.get("mcp_tools_used") or [])
    with st.expander("🧾 Полный ответ модели"):
        st.markdown(record.get("review_text") or "—")


def _pr_links(record: dict) -> None:
    """Ссылки GitHub-ревью: PR, опубликованный комментарий и признак отказа публикации."""
    pr_url = str(record.get("pr_url") or "")
    if pr_url:
        st.link_button("🐙 Открыть PR", pr_url)
    if record.get("posted") and record.get("comment_url"):
        st.success("Комментарий опубликован в PR")
        st.link_button("💬 Открыть комментарий", str(record["comment_url"]))
    elif st.session_state.get(POST_KEY):
        st.info("Ревью получено, комментарий не опубликован — причина в предупреждениях")


def _caption(record: dict, github: bool) -> str:
    """Подпись ревью: провайдер, время, число файлов и размер diff-а у режима GitHub."""
    files = len(record.get("changed_files") or [])
    meta = dict(record.get("github_meta") or {}) if github else {}
    if meta:
        files = int(meta.get("changed_files_count") or files)
    text = (f"Провайдер: {llm_provider.label(record.get('provider') or '')} · "
            f"{int(record.get('duration_ms') or 0) / 1000:.2f} с · "
            f"{common.plural(files, 'файл', 'файла', 'файлов')}: {files}")
    if meta:
        text += (f" · diff: {int(meta.get('diff_lines') or 0)} строк · "
                 f"PR `{meta.get('owner')}/{meta.get('repo')}#{meta.get('pr_number')}`")
    return text


def _findings(bugs: list) -> None:
    """Таблица багов: файл, строка, приоритет с подписью и сама проблема."""
    st.subheader("🐞 Потенциальные баги")
    if not bugs:
        st.caption("— не найдено")
        return
    st.dataframe([{"файл": item.get("file") or "—",
                   "строка": item.get("line") or "—",
                   "приоритет": _priority(item.get("priority")),
                   "проблема": item.get("issue") or "—"} for item in bugs],
                 hide_index=True, use_container_width=True)


def _architecture(issues: list) -> None:
    """Таблица архитектурных проблем: файл, приоритет, проблема и рекомендация."""
    st.subheader("🏛 Архитектурные проблемы")
    if not issues:
        st.caption("— не найдено")
        return
    st.dataframe([{"файл": item.get("file") or "—",
                   "приоритет": _priority(item.get("priority")),
                   "проблема": item.get("issue") or "—",
                   "рекомендация": item.get("recommendation") or "—"}
                  for item in issues], hide_index=True, use_container_width=True)


def _recommendations(items: list) -> None:
    """Список рекомендаций по улучшению."""
    st.subheader("💡 Рекомендации")
    if not items:
        st.caption("— не найдено")
        return
    st.markdown("\n".join(f"- {item}" for item in items))


def _risks(risks: list) -> None:
    """Таблица рисков: бэкенд уже отсортировал их от P0 к P3."""
    st.subheader("⚠️ Риски (P0 — P3)")
    if not risks:
        st.caption("— не найдено")
        return
    st.dataframe([{"приоритет": _priority(item.get("priority")),
                   "файл": item.get("file") or "—",
                   "риск": item.get("risk") or "—"} for item in risks],
                 hide_index=True, use_container_width=True)


def _sources(sources: list) -> None:
    """Раскрывашка «📚 Источники RAG»: файл корпуса, секция и балл каждого фрагмента."""
    with st.expander(f"📚 Источники RAG ({len(sources)})"):
        if not sources:
            st.caption("Источников нет: контекст корпуса не потребовался.")
            return
        st.dataframe([{"источник": item.get("source") or "—",
                       "секция": item.get("section") or "—",
                       "балл": item.get("score")} for item in sources],
                     hide_index=True, use_container_width=True)


def _tools(used: list) -> None:
    """Раскрывашка «🛠 MCP-инструменты»: локальный режим берёт ими diff и список файлов."""
    with st.expander(f"🛠 MCP-инструменты ({len(used)})"):
        if not used:
            st.caption("MCP-инструменты не вызывались: diff пришёл из запроса или из GitHub.")
            return
        st.dataframe([{"инструмент": item.get("tool") or "—",
                       "результат": "ок" if item.get("ok") else (item.get("error") or "ошибка"),
                       "время, мс": item.get("duration_ms")} for item in used],
                     hide_index=True, use_container_width=True)


def _priority(value: object) -> str:
    """Приоритет для человека: ``P0 (критично)``; незнакомое значение — как есть."""
    code = code_review.normalize_priority(value)
    return f"{code} ({code_review.PRIORITY_LABELS[code]})"


def _panel() -> None:
    """Панель служб: готовность ревью и готовность GitHub — с причиной вместо падения."""
    st.subheader("⚙️ Службы")
    with st.expander("⚙️ Готовность службы"):
        _health(HEALTH_KEY, code_review_api.api_review_health)
    with st.expander("🐙 GitHub"):
        _health(GITHUB_HEALTH_KEY, code_review_api.api_review_github_health)


def _health(key: str, fetch) -> None:
    """Данные одной панели: запрос один раз (или по кнопке), ошибка — подписью причины."""
    if st.button("🔄 Обновить", key=f"{key}_refresh") or key not in st.session_state:
        try:
            st.session_state[key] = fetch()
        except api_client.BackendError as exc:
            st.session_state[key] = {"error": exc.message}
    data = st.session_state.get(key) or {}
    if data.get("error"):
        st.caption(f"Недоступно: {data['error']}")
        return
    st.caption(f"Бэкенд: {api_client.BACKEND_URL} · служба: {data.get('service') or '—'}"
               f" · статус: {data.get('status') or '—'}")
    if "authenticated" not in data:
        st.caption(f"Провайдер по умолчанию: {data.get('default_provider') or '—'} · "
                   f"предел diff-а: {int(data.get('max_diff_lines') or 0)} строк · "
                   f"отчёт: `{data.get('report_path') or '—'}`")
        return
    st.caption(f"Токен: {'задан' if data.get('authenticated') else 'не задан'} "
               f"{data.get('token') or ''}")
    limits = dict(data.get("rate_limit") or {})
    st.caption(f"Лимит запросов: осталось {int(limits.get('remaining') or 0)} из "
               f"{int(limits.get('limit') or 0)}")
