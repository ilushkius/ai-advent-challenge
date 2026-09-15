"""День 12: Streamlit-чат агентов DeepSeek с памятью и профилем пользователя.

Приложение общается с FastAPI-бэкендом (порт 8000) по HTTP через `requests`.
Ключ DEEPSEEK_API_KEY фронтенду НЕ нужен — его читает бэкенд (day12/.env или
переменная окружения). Все данные хранит бэкенд в SQLite (day12/agents.db),
поэтому они переживают рестарт.

Что нового по сравнению с днём 11: **персонализация**. У каждого пользователя
есть профиль (таблица `user_profiles`), который подключается к системному
промпту КАЖДОГО запроса агента:

- `preferences` — стиль (tone), длина (verbosity), язык (language), формат
  (format) ответов;
- `constraints` — предел длины ответа, запрещённые темы, обязательные
  дисклеймеры;
- `custom_instructions` — произвольные инструкции («Обращайся ко мне по
  имени», «При запросе "напиши фичу" спавни агентов в порядке: аналитик →
  разработчик → тестировщик»).

Интерфейс — два раздела основной области (переключатель вверху страницы):

- «💬 Чат и память» — диалог вручную, панели трёх слоёв памяти (краткосрочная,
  рабочая, долговременная), индикатор того, что ушло в последний запрос,
  сравнение режимов сжатия. Переключатель стратегии контекста, задача и сессия
  — в боковой панели;
- «👤 Профиль пользователя» — выбор профиля, форма редактирования с кнопкой
  «Сохранить профиль», готовые профили для демонстрации, быстрое переключение
  профиля активного агента и сравнение двух профилей на одном вопросе: видно,
  как один и тот же запрос получает разные ответы.

Тестовый сценарий дня 11 (кнопка прогона 12 реплик «собираем ТЗ») удалён: диалог
ведётся вручную, а доказательство персонализации даёт
`personalization_comparison.py` → `personalization_comparison.md`.

Запуск из папки day12/:  streamlit run app.py  (бэкенд запускается отдельно:
uvicorn backend.main:app --port 8000)
"""
import html
import os
from typing import List

import pandas as pd
import requests
import streamlit as st

from backend import config
from backend.demo_profiles import DEMO_PROFILES, DEMO_QUESTION
from backend.profiles import (
    CUSTOM_INSTRUCTION_EXAMPLE, PREFERENCE_OPTIONS, ProfileValueError,
    build_profile_prompt,
)

# Куда стучится фронтенд (можно переопределить переменной окружения).
BACKEND_URL = os.environ.get("DAY12_BACKEND_URL", "http://127.0.0.1:8000")
TIMEOUT = 90.0  # сек; compare с вызовами API делает два запроса к DeepSeek

# Подписи ролей для отрисовки сообщений чата.
ROLE_LABELS = {"user": "🧑 Вы", "assistant": "🤖 Ассистент"}

# Стратегии управления контекстом (день 10): значение → человекочитаемая подпись.
STRATEGY_LABELS = {
    "sliding_window": "🪟 Sliding Window (последние N)",
    "sticky_facts": "📌 Sticky Facts (факты + последние N)",
    "branching": "🌿 Branching (ветвление истории)",
    "summary": "🗜 Summary (сжатие конспектом)",
}

# Категории долговременной памяти (день 11): значение → подпись для UI.
MEMORY_CATEGORY_LABELS = {
    "profile": "👤 профиль",
    "preference": "⭐ предпочтение",
    "decision": "✅ решение",
    "knowledge": "📚 знание",
}

# Слои памяти в отчёте генерации: ключ слоя → человекочитаемая подпись.
LAYER_LABELS = {
    "short_term": "👤 Краткосрочная",
    "working": "🗂 Рабочая",
    "long_term": "🧠 Долговременная",
}

# Состояния стейт-машины сжатия (бэкенд отдаёт их строкой) — для человека.
STATE_LABELS = {
    "idle": "💤 накапливать нечего",
    "tracking": "📥 накопление реплик",
    "summary_pending": "⏳ пора сжимать",
    "summarizing": "🗜 сжатие выполняется",
    "error": "⚠️ ошибка сжатия (повтор на следующем ходу)",
}


class BackendError(Exception):
    """Ошибка общения с бэкендом (недоступен либо вернул HTTP-ошибку)."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------- HTTP-клиент к бэкенду ----------
def _extract_error(resp) -> str:
    """Достаёт человекочитаемый текст ошибки из тела бэкенда.

    Бэкенд отвечает ошибками в двух формах: {"detail": ...} (FastAPI для 404/422)
    и {status: "error", error: ...} (наша структурированная ошибка 502).
    """
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if isinstance(data, dict):
        if data.get("error"):
            return data["error"]
        if data.get("detail"):
            detail = data["detail"]
            return detail if isinstance(detail, str) else str(detail)
        if data.get("message"):
            return data["message"]
    return f"Бэкенд вернул HTTP {resp.status_code}"


def _request(method, path, **kwargs):
    """Делает запрос к бэкенду; HTTP-ошибки превращает в BackendError."""
    try:
        resp = requests.request(method, BACKEND_URL.rstrip("/") + path,
                                timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise BackendError(
            f"Бэкенд недоступен ({BACKEND_URL}). Запустите его из папки day12/: "
            f"uvicorn backend.main:app --port 8000 "
            f"({exc.__class__.__name__})"
        ) from exc
    if resp.status_code >= 400:
        raise BackendError(_extract_error(resp), resp.status_code)
    return resp.json()


def api_fetch_agents():
    """GET /agents -> список записей (id, имя, модель, сообщения, сжатие)."""
    return _request("GET", "/agents")


def api_create_agent(agent_config):
    """POST /agents -> полная информация о созданном агенте."""
    return _request("POST", "/agents", json=agent_config)


def api_patch_agent(agent_id, payload):
    """PATCH /agents/{agent_id} -> обновлённая конфигурация агента."""
    return _request("PATCH", f"/agents/{agent_id}", json=payload)


def api_delete_agent(agent_id):
    """DELETE /agents/{agent_id}."""
    return _request("DELETE", f"/agents/{agent_id}")


def api_generate(agent_id, prompt):
    """POST /agents/{agent_id}/generate -> ответ + метрики + обновлённая история.

    При сбое генерации бэкенд отвечает 502: _request поднимет BackendError с
    понятным текстом (например, «Ключ API не задан...»).
    """
    return _request("POST", f"/agents/{agent_id}/generate", json={"prompt": prompt})


def api_history(agent_id):
    """GET /agents/{agent_id}/history -> сообщения диалога (по возрастанию)."""
    return _request("GET", f"/agents/{agent_id}/history")


def api_clear_history(agent_id):
    """DELETE /agents/{agent_id}/history -> очистка диалога, конспектов и метрик."""
    return _request("DELETE", f"/agents/{agent_id}/history")


def api_usage(agent_id):
    """GET /agents/{agent_id}/usage -> сводка токенов и экономии."""
    return _request("GET", f"/agents/{agent_id}/usage")


def api_usage_graph(agent_id):
    """GET /agents/{agent_id}/usage/graph -> записи token_usage (по возрастанию)."""
    return _request("GET", f"/agents/{agent_id}/usage/graph")


def api_summary(agent_id):
    """GET /agents/{agent_id}/summary -> конспект, watermark, экономика."""
    return _request("GET", f"/agents/{agent_id}/summary")


def api_summarize(agent_id, force=False):
    """POST /agents/{agent_id}/summarize -> отчёт о попытке сжатия."""
    return _request("POST", f"/agents/{agent_id}/summarize", json={"force": force})


def api_compare(agent_id, prompt, call_api=False):
    """POST /agents/{agent_id}/compare -> сравнение режимов на одном промпте."""
    return _request("POST", f"/agents/{agent_id}/compare",
                    json={"prompt": prompt, "call_api": call_api})


def api_set_strategy(agent_id, strategy, window_size=None):
    """POST /agents/{agent_id}/strategy -> смена стратегии и окна."""
    payload = {"strategy": strategy}
    if window_size is not None:
        payload["window_size"] = int(window_size)
    return _request("POST", f"/agents/{agent_id}/strategy", json=payload)


def api_strategies(agent_id):
    """GET /agents/{agent_id}/strategies -> текущая стратегия + доступные."""
    return _request("GET", f"/agents/{agent_id}/strategies")


def api_branches(agent_id):
    """GET /agents/{agent_id}/branches -> дерево веток."""
    return _request("GET", f"/agents/{agent_id}/branches")


def api_create_branch(agent_id, checkpoint_id=None):
    """POST /agents/{agent_id}/branches -> создать ветку, вернуть дерево."""
    return _request("POST", f"/agents/{agent_id}/branches",
                    json={"checkpoint_id": checkpoint_id})


def api_switch_branch(agent_id, branch_id):
    """POST /agents/{agent_id}/branches/{branch_id}/switch -> переключить ветку."""
    return _request("POST", f"/agents/{agent_id}/branches/{branch_id}/switch",
                    json={})


def api_facts(agent_id):
    """GET /agents/{agent_id}/facts -> факты диалога (sticky_facts)."""
    return _request("GET", f"/agents/{agent_id}/facts")


# ---------- HTTP-клиент: слои памяти (день 11) ----------
def api_short_term(agent_id, session_id=None, limit=50):
    """GET /agents/{id}/memory/short-term -> реплики краткосрочного слоя."""
    params = {"limit": int(limit)}
    if session_id:
        params["session_id"] = session_id
    return _request("GET", f"/agents/{agent_id}/memory/short-term", params=params)


def api_add_short_term(agent_id, role, content, session_id=None):
    """POST /agents/{id}/memory/short-term -> добавить реплику в сессию."""
    payload = {"role": role, "content": content}
    if session_id:
        payload["session_id"] = session_id
    return _request("POST", f"/agents/{agent_id}/memory/short-term", json=payload)


def api_clear_short_term(agent_id, session_id=None):
    """DELETE /agents/{id}/memory/short-term -> очистить сессию (число удалённых)."""
    params = {"session_id": session_id} if session_id else None
    return _request("DELETE", f"/agents/{agent_id}/memory/short-term", params=params)


def api_working(agent_id, task_id=None):
    """GET /agents/{id}/memory/working -> записи задачи + список задач."""
    params = {"task_id": task_id} if task_id else None
    return _request("GET", f"/agents/{agent_id}/memory/working", params=params)


def api_add_working(agent_id, key, value, task_id=None):
    """POST /agents/{id}/memory/working -> upsert записи (task_id, key)."""
    payload = {"key": key, "value": value}
    if task_id:
        payload["task_id"] = task_id
    return _request("POST", f"/agents/{agent_id}/memory/working", json=payload)


def api_long_term(agent_id, category=None):
    """GET /agents/{id}/memory/long-term -> записи долговременной памяти."""
    params = {"category": category} if category else None
    return _request("GET", f"/agents/{agent_id}/memory/long-term", params=params)


def api_add_long_term(agent_id, category, key, value, confidence=1.0):
    """POST /agents/{id}/memory/long-term -> upsert записи (category, key)."""
    return _request("POST", f"/agents/{agent_id}/memory/long-term", json={
        "category": category, "key": key, "value": value,
        "confidence": float(confidence),
    })


def api_delete_long_term(agent_id, entry_id):
    """DELETE /agents/{id}/memory/long-term/{entry_id} -> удалить запись."""
    return _request("DELETE",
                    f"/agents/{agent_id}/memory/long-term/{int(entry_id)}")


def api_new_session(agent_id):
    """POST /agents/{id}/memory/session -> новая сессия (очистка короткого слоя)."""
    return _request("POST", f"/agents/{agent_id}/memory/session")


def api_set_task(agent_id, task_id):
    """PUT /agents/{id}/memory/task -> переключить активную задачу."""
    return _request("PUT", f"/agents/{agent_id}/memory/task",
                    json={"task_id": task_id})


# ---------- HTTP-клиент: профили пользователей (день 12) ----------
def api_list_users():
    """GET /users -> все профили пользователей (селектор в интерфейсе)."""
    return _request("GET", "/users")


def api_get_profile(user_id):
    """GET /users/{user_id}/profile -> профиль пользователя (404, если нет)."""
    return _request("GET", f"/users/{user_id}/profile")


def api_create_profile(user_id, payload):
    """POST /users/{user_id}/profile -> созданный профиль (409, если есть)."""
    return _request("POST", f"/users/{user_id}/profile", json=payload)


def api_update_profile(user_id, payload):
    """PUT /users/{user_id}/profile -> обновлённый профиль (404, если нет)."""
    return _request("PUT", f"/users/{user_id}/profile", json=payload)


def api_delete_profile(user_id):
    """DELETE /users/{user_id}/profile -> профиль удалён (404, если нет)."""
    return _request("DELETE", f"/users/{user_id}/profile")


def api_agent_profile(agent_id):
    """GET /agents/{id}/profile -> профиль агента и его вклад в промпт."""
    return _request("GET", f"/agents/{agent_id}/profile")


def api_set_agent_user(agent_id, user_id):
    """PATCH /agents/{id} с новым user_id -> быстрое переключение профиля."""
    return _request("PATCH", f"/agents/{agent_id}", json={"user_id": user_id})


# ---------- форматирование для UI ----------
def esc(text):
    """Безопасный вывод: экранирует HTML и сохраняет переносы строк."""
    if text is None:
        return ""
    return html.escape(str(text)).replace("\n", "<br>")


def fmt_time(ts):
    """'2026-09-09T12:00:00...' -> '09.09 12:00' (или '' при None)."""
    if not ts:
        return ""
    return str(ts)[:16].replace("T", " ")


def fmt_int(value) -> str:
    """1234567 -> '1 234 567' (удобное чтение больших чисел токенов)."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русская форма слова для числа: 1 сообщение / 2 сообщения / 5 сообщений."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def label_agent(agent) -> str:
    """Подпись агента: имя · модель · сообщения · стратегия · задача."""
    n = agent.get("message_count", 0)
    strategy = agent.get("strategy", "summary")
    mode = STRATEGY_LABELS.get(strategy, strategy)
    task = agent.get("task_id", "default")
    return (f"{agent['name']} · {agent['model']} · "
            f"{n} {plural(n, 'сообщение', 'сообщения', 'сообщений')} · {mode}"
            f" · задача {task}")


def render_message(role: str, content: str, ts: str = ""):
    """Отрисовывает одно сообщение диалога в виде «пузыря» чата."""
    who = ROLE_LABELS.get(role, role)
    time_suffix = f" · {fmt_time(ts)}" if ts else ""
    color = "#dbeafe" if role == "user" else "#dcfce7"
    st.markdown(
        f"<div style='background:{color};color:#111827;border-radius:10px;"
        f"padding:10px 14px;margin:6px 0;text-align:left'>"
        f"<b>{esc(who)}</b><span style='color:#6b7280;font-size:0.8em'>"
        f"{esc(time_suffix)}</span><br>{esc(content)}</div>",
        unsafe_allow_html=True,
    )


def render_summary_marker(count: int, tokens: int) -> None:
    """Маркер на границе сжатия: сколько реплик заменено конспектом."""
    st.markdown(
        f"<div style='background:#fef3c7;color:#78350f;border:1px dashed #d97706;"
        f"border-radius:8px;padding:6px 12px;margin:8px 0;text-align:center;"
        f"font-size:0.9em'>🗜 выше {count} "
        f"{plural(count, 'реплика', 'реплики', 'реплик')} заменены конспектом "
        f"(в запрос идёт ~{fmt_int(tokens)} токенов вместо полного текста)</div>",
        unsafe_allow_html=True,
    )


def format_usage(usage) -> str:
    if not usage:
        return "—"
    return (f"вход {usage.get('prompt_tokens', '?')} · "
            f"выход {usage.get('completion_tokens', '?')} · "
            f"всего {usage.get('total_tokens', '?')}")


def render_token_panel(active) -> None:
    """Панель «📊 Токены диалога»: счётчики, лимит, экономия, график, таблица."""
    agent_id = active.get("agent_id")
    try:
        summary = api_usage(agent_id)
        rows = api_usage_graph(agent_id)
    except BackendError:
        return  # бэкенд недоступен/ошибка — панель пропускается, чат живёт

    st.subheader("📊 Токены диалога")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Использовано за диалог",
                f"{fmt_int(summary.get('total_tokens'))} токенов")
    col2.metric("Запросов", fmt_int(summary.get("total_requests")))
    col3.metric("Стоимость", f"${summary.get('total_cost', 0.0):.6f}")
    col4.metric("Сэкономлено сжатием",
                f"{fmt_int(summary.get('total_saved_tokens'))} токенов",
                help="Разница между полной историей и отправленным контекстом; "
                     "чистая экономия (минус стоимость конспектов) — в панели "
                     "«🗜 Сжатие контекста».")

    limit = int(summary.get("context_limit_tokens") or 0)
    current = int(summary.get("current_history_tokens") or 0)
    remaining = int(summary.get("remaining_tokens") or 0)
    ratio = min(1.0, current / limit) if limit else 0.0
    st.progress(ratio)
    st.caption(f"Контекст диалога: занято **{fmt_int(current)}** из "
               f"**{fmt_int(limit)}** токенов · до лимита осталось "
               f"**{fmt_int(remaining)}**")
    if limit and remaining < limit * 0.1:
        st.warning("⚠️ Контекст почти заполнен. Со сжатием агент отправит конспект "
                   "старых реплик — включите сжатие или очистите историю.")

    if rows:
        df = pd.DataFrame([
            {
                "time": fmt_time(r.get("timestamp")),
                "prompt_tokens": r.get("prompt_tokens", 0),
                "completion_tokens": r.get("completion_tokens", 0),
                "total_tokens": r.get("total_tokens", 0),
                "full_context_tokens": r.get("full_context_tokens", 0),
                "sent_context_tokens": r.get("sent_context_tokens", 0),
                "saved_tokens": r.get("saved_tokens", 0),
                "mode": "🗜 сжатие" if r.get("summary_used") else "📜 полная",
                "cost": r.get("cost", 0.0),
            }
            for r in rows
        ])
        df["cumulative"] = df["total_tokens"].cumsum()
        df["saved_cumulative"] = df["saved_tokens"].cumsum()
        chart = df.set_index("time")[["cumulative", "saved_cumulative",
                                      "sent_context_tokens"]]
        st.markdown("**📈 Рост токенов и накопленная экономия** "
                    "(total за диалог · сэкономлено · отправлено в последнем запросе):")
        st.line_chart(chart)
        with st.expander("Таблица записей token_usage"):
            st.dataframe(df.rename(columns={
                "time": "время", "prompt_tokens": "запрос",
                "completion_tokens": "ответ", "total_tokens": "всего",
                "full_context_tokens": "без сжатия",
                "sent_context_tokens": "отправлено",
                "saved_tokens": "сэкономлено", "mode": "режим",
                "cost": "стоимость $", "cumulative": "накоплено",
                "saved_cumulative": "накопл. экономия",
            }))
    else:
        st.info("Записей токенов пока нет — отправьте первый запрос, и здесь "
                "появится график и таблица.")


def render_compression_panel(active) -> None:
    """Панель «🗜 Сжатие контекста»: конспект, watermark, экономика, кнопка сжатия."""
    agent_id = active.get("agent_id")
    try:
        state = api_summary(agent_id)
    except BackendError:
        return

    st.subheader("🗜 Сжатие контекста")
    keep_last = int(state.get("keep_last_messages") or 0)
    every = int(state.get("summarize_every") or 0)
    st.caption(f"Состояние процесса: **{STATE_LABELS.get(state.get('state'), state.get('state'))}** "
               f"· режим: {'включено' if state.get('enabled') else 'выключено'} "
               f"· последние **{keep_last}** "
               f"{plural(keep_last, 'реплика', 'реплики', 'реплик')} — как есть "
               f"· сжатие каждые **{every}** "
               f"{plural(every, 'новая реплика', 'новые реплики', 'новых реплик')}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Конспектов", fmt_int(state.get("summary_count")))
    col2.metric("Реплик в конспекте", fmt_int(state.get("covered_messages")),
                help="Сколько реплик заменено конспектом в запросах.")
    col3.metric("Сэкономлено", f"{fmt_int(state.get('saved_tokens'))} токенов")
    col4.metric("Чистая экономия",
                f"{fmt_int(state.get('net_saved_tokens'))} токенов",
                help="Сэкономленные токены запросов минус токены вызовов "
                     "суммаризации (стоимость конспектов).")

    total = int(state.get("message_count") or 0)
    covered = int(state.get("covered_messages") or 0)
    ratio = min(1.0, covered / total) if total else 0.0
    st.progress(ratio)
    st.caption(f"Покрыто конспектом: **{fmt_int(covered)}** из "
               f"**{fmt_int(total)}** реплик · до следующего сжатия осталось "
               f"**{fmt_int(state.get('next_compression_in'))}** непокрытых "
               f"· стоимость конспектов ${state.get('summary_cost', 0.0):.6f}")

    current = state.get("current")
    if current:
        covered_n = int(current.get("covered_messages") or 0)
        with st.expander(f"📝 Текущий конспект ({covered_n} "
                         f"{plural(covered_n, 'реплика', 'реплики', 'реплик')}, "
                         f"{fmt_int(current.get('summary_tokens'))} токенов):"):
            st.markdown(esc(current.get("content")))
            st.caption(f"Создан: {fmt_time(current.get('created_at'))} · "
                       f"исходный текст: {fmt_int(current.get('source_tokens'))} "
                       f"токенов · сжатие ×"
                       f"{(current.get('source_tokens') or 0) / max(1, current.get('summary_tokens') or 1):.1f}")
    else:
        st.info("Конспекта пока нет: истории не хватает для порога сжатия. "
                "Кнопка ниже сжимает принудительно (демо).")

    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button("🗜 Сжать сейчас", help="Принудительное сжатие: всё, кроме "
                                             "последних N реплик, уходит в конспект"):
            try:
                report = api_summarize(agent_id, force=True)
            except BackendError as exc:
                _flash("error", f"Сжатие не выполнено: {exc.message}")
            else:
                if report.get("created"):
                    _flash("success",
                           f"Конспект обновлён: в него ушло "
                           f"{report.get('summarized_messages')} реплик. "
                           f"Состояние: {STATE_LABELS.get(report.get('state'), report.get('state'))}")
                else:
                    _flash("info", f"Сжимать пока нечего: {report.get('error') or 'нет данных'}")
            st.rerun()
    with col_left:
        if state.get("enabled"):
            if st.button("⏸ Отключить сжатие",
                         help="Агент снова начнёт отправлять всю историю (день 8)"):
                try:
                    api_patch_agent(agent_id, {"summary_enabled": False})
                except BackendError as exc:
                    _flash("error", f"Не удалось изменить режим: {exc.message}")
                else:
                    _flash("info", "Сжатие выключено: в запрос снова идёт вся история.")
                st.rerun()
        else:
            if st.button("▶️ Включить сжатие",
                         help="Агент будет отправлять конспект + последние N реплик"):
                try:
                    api_patch_agent(agent_id, {"summary_enabled": True})
                except BackendError as exc:
                    _flash("error", f"Не удалось изменить режим: {exc.message}")
                else:
                    _flash("success", "Сжатие включено.")
                st.rerun()


def render_compare(active) -> None:
    """Блок «⚖️ Сравнить режимы»: один промпт в двух вариантах контекста."""
    agent_id = active.get("agent_id")
    with st.expander("⚖️ Сравнить режимы: без сжатия и со сжатием",
                     expanded=False):
        st.caption("Один и тот же промпт считается (и, по желанию, отправляется) "
                   "дважды: со всей историей и с конспектом + последними "
                   "репликами. История диалога при этом не меняется.")
        compare_prompt = st.text_area(
            "Промпт для сравнения", key=f"compare_{agent_id}", height=80,
            placeholder="Например: что мы решили по лимитам контекста?",
        )
        call_api = st.checkbox(
            "Вызвать DeepSeek дважды (сравнить и ответы, и токены)",
            value=False, key=f"compare_api_{agent_id}",
            help="Без галочки считаются только токены — это работает без ключа API.",
        )
        if st.button("⚖️ Сравнить", disabled=not (compare_prompt or "").strip(),
                     key=f"compare_btn_{agent_id}"):
            try:
                result = api_compare(agent_id, compare_prompt.strip(),
                                     call_api=call_api)
            except BackendError as exc:
                st.error(f"Сравнение не выполнено: {exc.message}")
            else:
                st.session_state["compare_result"] = result

        result = st.session_state.get("compare_result")
        if result and result.get("agent_id") == agent_id:
            del st.session_state["compare_result"]  # показываем один раз
            col_full, col_comp = st.columns(2)
            full = result.get("full", {})
            comp = result.get("compressed", {})
            with col_full:
                st.markdown("**📜 Без сжатия** (вся история)")
                st.metric("Токенов контекста", fmt_int(full.get("sent_context_tokens")))
                if full.get("total_tokens") is not None:
                    st.caption(f"usage: вход {full.get('prompt_tokens')} · "
                               f"выход {full.get('completion_tokens')} · "
                               f"${full.get('cost', 0):.6f}")
                if full.get("error"):
                    st.error(full["error"])
                elif full.get("response"):
                    st.markdown(esc(full["response"]))
            with col_comp:
                st.markdown("**🗜 Со сжатием** (конспект + последние реплики)")
                st.metric("Токенов контекста", fmt_int(comp.get("sent_context_tokens")),
                          delta=f"-{fmt_int(result.get('saved_tokens'))}")
                if comp.get("total_tokens") is not None:
                    st.caption(f"usage: вход {comp.get('prompt_tokens')} · "
                               f"выход {comp.get('completion_tokens')} · "
                               f"${comp.get('cost', 0):.6f}")
                if comp.get("error"):
                    st.error(comp["error"])
                elif comp.get("response"):
                    st.markdown(esc(comp["response"]))
            st.success(
                f"Экономия контекста: **{fmt_int(result.get('saved_tokens'))}** токенов "
                f"(**{result.get('saved_percent')}%**) · "
                f"конспект: {'использован' if comp.get('summary_used') else 'не использован'}"
                f" · покрыто реплик: {fmt_int(comp.get('summarized_messages'))}"
            )
            if result.get("warning"):
                st.warning(result["warning"])


def render_branching_panel(active) -> None:
    """Панель «🌿 Ветвление»: дерево веток, создать ветку, переключиться."""
    agent_id = active.get("agent_id")
    try:
        tree = api_branches(agent_id)
    except BackendError:
        return

    st.subheader("🌿 Ветвление истории")
    branches = tree.get("branches") or []
    active_id = tree.get("active_branch_id")

    if not branches:
        st.info("Веток пока нет. Отправьте сообщение в режиме branching — "
                "создастся корневой чекпоинт, от которого можно ветвиться.")
        return

    # Дерево: чекпоинт → parent_id. Отрисовываем список с отступом по глубине.
    by_id = {b["id"]: b for b in branches}

    def _depth(branch, memo=None):
        memo = memo or {}
        if branch["id"] in memo:
            return 0
        memo[branch["id"]] = True
        parent = branch.get("parent_id")
        if parent is not None and parent in by_id:
            return 1 + _depth(by_id[parent], memo)
        return 0

    st.caption(f"Активная ветка: **{active_id}** · всего чекпоинтов: "
               f"{len(branches)}")
    for branch in branches:
        depth = _depth(branch)
        marker = "🟢" if branch["id"] == active_id else "  "
        label = (f"{marker} {'·  ' * depth}ветка {branch['id']} "
                 f"({branch['message_count']} "
                 f"{plural(branch['message_count'], 'реплика', 'реплики', 'реплик')})"
                 f" · {fmt_time(branch.get('created_at'))}")
        col_label, col_switch = st.columns([5, 1])
        with col_label:
            st.markdown(label)
        with col_switch:
            if branch["id"] != active_id:
                if st.button("↩", key=f"switch_{branch['id']}",
                             help=f"Переключиться на ветку {branch['id']}"):
                    try:
                        api_switch_branch(agent_id, branch["id"])
                    except BackendError as exc:
                        _flash("error", f"Не удалось переключить ветку: {exc.message}")
                    else:
                        _flash("info", f"Переключено на ветку {branch['id']}.")
                    st.rerun()

    col_new, _ = st.columns([3, 1])
    with col_new:
        if st.button("🌱 Новая ветка от текущего сообщения",
                     help="Снимок текущей истории становится новой веткой; "
                          "старая ветка замораживается, новая — активна."):
            try:
                api_create_branch(agent_id, None)
            except BackendError as exc:
                _flash("error", f"Не удалось создать ветку: {exc.message}")
            else:
                _flash("success", "Создана новая ветка от текущего сообщения.")
            st.rerun()


def render_facts_panel(active) -> None:
    """Панель «📌 Факты» для sticky_facts: ключ-значение в реальном времени."""
    agent_id = active.get("agent_id")
    try:
        facts = api_facts(agent_id).get("facts", [])
    except BackendError:
        return

    st.subheader("📌 Факты диалога (sticky_facts)")
    if not facts:
        st.info("Фактов пока нет. Пишите реплики вида «ключ: значение» — "
                "эвристика извлечёт их и отправит в LLM вместе с последними "
                "сообщениями.")
        return
    rows = [{"ключ": f.get("key"), "значение": f.get("value"),
             "обновлено": fmt_time(f.get("updated_at"))} for f in facts]
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ---------- панели слоёв памяти (день 11) ----------
def render_short_term_panel(active) -> None:
    """Панель «👤 Краткосрочная память»: реплики текущей сессии и её очистка."""
    agent_id = active.get("agent_id")
    try:
        data = api_short_term(agent_id)
    except BackendError:
        return  # бэкенд недоступен/ошибка — панель пропускается, чат живёт

    messages = data.get("messages") or []
    st.subheader("👤 Краткосрочная память (текущая сессия)")
    st.caption(f"Сессия **{data.get('session_id')}** · реплик: "
               f"**{len(messages)}** · слой очищается кнопкой «🆕 Новая сессия» "
               "и командой ниже.")
    if not messages:
        st.info("Краткосрочная память пуста. Реплики появятся здесь после "
                "первого сообщения (или добавьте их кнопкой «Отправить»).")
    else:
        rows = [{
            "роль": ROLE_LABELS.get(m.get("role"), m.get("role")),
            "текст": (m.get("content") or "")[:200],
            "создано": fmt_time(m.get("created_at")),
        } for m in messages]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if st.button("🧹 Очистить краткосрочную память",
                 key=f"short_term_clear_{agent_id}",
                 help="Удаляет реплики текущей сессии. Рабочая и долговременная "
                      "память не затрагиваются."):
        try:
            result = api_clear_short_term(agent_id)
        except BackendError as exc:
            _flash("error", f"Не удалось очистить сессию: {exc.message}")
        else:
            _flash("success",
                   f"Краткосрочная память очищена: удалено реплик "
                   f"{result.get('deleted', 0)}.")
            st.session_state["chat_agent_id"] = None
        _load_agents()
        st.rerun()


def render_working_panel(active) -> None:
    """Панель «🗂 Рабочая память»: записи активной задачи и их сохранение."""
    agent_id = active.get("agent_id")
    try:
        data = api_working(agent_id)
    except BackendError:
        return

    entries = data.get("entries") or []
    task_id = data.get("task_id", "default")
    st.subheader("🗂 Рабочая память (текущая задача)")
    st.caption(f"Задача **{task_id}** · записей: **{len(entries)}** · слой "
               "переживает смену сессии и очищается только вручную "
               "(или сменой задачи).")

    with st.form(f"working_add_{agent_id}"):
        st.markdown("**Добавить/обновить запись** (ввод существующего ключа "
                    "перезапишет значение — upsert)")
        col_key, col_value = st.columns([2, 3])
        w_key = col_key.text_input("Ключ", placeholder="например: цель")
        w_value = col_value.text_area("Значение", height=80,
                                      placeholder="например: портал для ТЗ")
        if st.form_submit_button("💾 Сохранить"):
            if not w_key.strip() or not w_value.strip():
                st.warning("Нужны и ключ, и значение.")
            else:
                try:
                    api_add_working(agent_id, w_key.strip(), w_value.strip())
                except BackendError as exc:
                    st.error(f"Не удалось сохранить: {exc.message}")
                else:
                    _flash("success",
                           f"Рабочая память задачи {task_id}: записан ключ "
                           f"«{w_key.strip()}».")
                    st.rerun()

    if not entries:
        st.info("Записей нет. Сохраните цель, ограничения или решения задачи — "
                "они будут подставляться в каждый запрос этой задачи.")
    else:
        rows = [{"ключ": e.get("key"), "значение": e.get("value"),
                 "обновлено": fmt_time(e.get("updated_at"))} for e in entries]
        st.dataframe(rows, use_container_width=True, hide_index=True)


def render_long_term_panel(active) -> None:
    """Панель «🧠 Долговременная память»: записи между сессиями, CRUD."""
    agent_id = active.get("agent_id")
    st.subheader("🧠 Долговременная память (между сессиями)")
    categories = list(MEMORY_CATEGORY_LABELS.keys())
    all_label = "все категории"
    chosen = st.selectbox(
        "Фильтр по категории", [all_label] + categories,
        format_func=lambda c: all_label if c == all_label
        else MEMORY_CATEGORY_LABELS[c],
        key=f"long_term_filter_{agent_id}",
    )
    try:
        data = api_long_term(agent_id, None if chosen == all_label else chosen)
    except BackendError:
        return

    entries = data.get("entries") or []
    st.caption("Устойчивые данные о пользователе: профиль, предпочтения, "
               "решения, знания. Не очищаются ни «Новой сессией», ни сменой "
               "задачи — удаляются только вручную.")

    with st.form(f"long_term_add_{agent_id}"):
        st.markdown("**Добавить/обновить запись** (upsert по категории и ключу)")
        lt_category = st.selectbox(
            "Категория", categories,
            format_func=lambda c: MEMORY_CATEGORY_LABELS[c],
        )
        lt_key = st.text_input("Ключ", placeholder="например: язык_интерфейса")
        lt_value = st.text_area("Значение", height=80,
                                placeholder="например: русский")
        lt_confidence = st.slider("Уверенность", 0.0, 1.0, 1.0, 0.05)
        if st.form_submit_button("💾 Сохранить"):
            if not lt_key.strip() or not lt_value.strip():
                st.warning("Нужны и ключ, и значение.")
            else:
                try:
                    api_add_long_term(agent_id, lt_category, lt_key.strip(),
                                      lt_value.strip(), lt_confidence)
                except BackendError as exc:
                    st.error(f"Не удалось сохранить: {exc.message}")
                else:
                    _flash("success",
                           f"Долговременная память: записан ключ "
                           f"«{lt_key.strip()}» ({lt_category}).")
                    st.rerun()

    if not entries:
        st.info("Записей нет. Добавьте профиль пользователя или устойчивое "
                "предпочтение — такие записи учитываются в каждом запросе.")
        return

    rows = [{
        "id": e.get("id"),
        "категория": MEMORY_CATEGORY_LABELS.get(e.get("category"),
                                                e.get("category")),
        "ключ": e.get("key"),
        "значение": e.get("value"),
        "уверенность": e.get("confidence"),
    } for e in entries]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    col_id, col_del = st.columns([2, 1])
    entry_ids = [e.get("id") for e in entries]
    entry_id = col_id.selectbox("Удалить запись по id", entry_ids,
                                key=f"long_term_del_{agent_id}")
    if col_del.button("🗑 Удалить", key=f"long_term_del_btn_{agent_id}",
                      help="Удаляет запись долговременной памяти безвозвратно."):
        try:
            api_delete_long_term(agent_id, entry_id)
        except BackendError as exc:
            _flash("error", f"Не удалось удалить запись {entry_id}: {exc.message}")
        else:
            _flash("success", f"Запись {entry_id} удалена из долговременной памяти.")
        st.rerun()


def render_memory_panels(active) -> None:
    """Три вкладки панелей памяти: краткосрочная, рабочая, долговременная."""
    st.subheader("🧠 Слои памяти агента")
    tab_short, tab_working, tab_long = st.tabs(
        ["👤 Краткосрочная", "🗂 Рабочая", "🧠 Долговременная"]
    )
    with tab_short:
        render_short_term_panel(active)
    with tab_working:
        render_working_panel(active)
    with tab_long:
        render_long_term_panel(active)


def render_memory_indicator(active) -> None:
    """Индикатор слоёв: что именно ушло в контекст последнего запроса.

    Данные берутся из ответа генерации (``record["memory"]``), который
    сохраняется в ``st.session_state["last_memory"]``: до первого сообщения
    показывать нечего.
    """
    agent_id = active.get("agent_id")
    memory = (st.session_state.get("last_memory") or {}).get(agent_id)
    st.subheader("🧭 Что ушло в последний запрос")
    if not memory:
        st.caption("Слои памяти: индикация появится после первого сообщения.")
        return

    layers = {layer.get("layer"): layer for layer in memory.get("layers") or []}
    col1, col2, col3 = st.columns(3)
    for column, key in ((col1, "short_term"), (col2, "working"),
                        (col3, "long_term")):
        layer = layers.get(key) or {}
        entries = int(layer.get("entries") or 0)
        tokens = int(layer.get("tokens") or 0)
        column.metric(
            LAYER_LABELS[key],
            f"{entries} записей · {fmt_int(tokens)} токенов",
            help=layer.get("details") or "",
        )
    st.caption(
        f"Сессия **{memory.get('session_id')}** · задача "
        f"**{memory.get('task_id')}** · всего по слоям: "
        f"**{fmt_int(memory.get('total_tokens'))}** токенов "
        f"(короткая {fmt_int(memory.get('short_term_tokens'))} + рабочая "
        f"{fmt_int(memory.get('working_tokens'))} + долговременная "
        f"{fmt_int(memory.get('long_term_tokens'))})"
    )
    used = [LAYER_LABELS[key] for key in ("short_term", "working", "long_term")
            if (layers.get(key) or {}).get("used")]
    if used:
        st.caption("Использованы в запросе: " + " · ".join(used))
    keywords = memory.get("keywords") or []
    if keywords:
        st.caption("Ключевые слова запроса (отбор долговременных записей): "
                   + ", ".join(keywords))


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
            result = api_update_profile(user_id, payload)
            _flash(
                "success",
                f"Профиль **{user_id}** обновлён · {result.get('summary')} · "
                f"применён к агентам: {result.get('applied_to_agents', 0)}",
            )
        else:
            result = api_create_profile(user_id, payload)
            _flash(
                "success",
                f"Профиль **{user_id}** создан · {result.get('summary')}",
            )
    except BackendError as exc:
        _flash("error", f"Профиль не сохранён: {exc.message}")
    _load_agents()
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
        api_get_profile(user_id)
    except BackendError as exc:
        if exc.status_code != 404:
            _flash("error", f"Профиль {user_id} недоступен: {exc.message}")
            st.rerun()
        _save_profile(user_id, payload, exists=False)
    else:
        _save_profile(user_id, payload, exists=True)


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
            info = api_create_agent({
                "name": f"Сравнение профилей · {user_id}",
                "user_id": user_id,
            })
        except BackendError as exc:
            entry["error"] = f"Агент не создан: {exc.message}"
            result["profiles"][user_id] = entry
            continue
        agent_id = info["agent_id"]
        try:
            record = api_generate(agent_id, question)
        except BackendError as exc:
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
                api_delete_agent(agent_id)
            except BackendError:
                pass  # временный агент остался — не повод терять результат
        result["profiles"][user_id] = entry
    return result


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
        users = api_list_users()
    except BackendError as exc:
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
                f"Обновлён: {fmt_time(by_id[selected].get('updated_at'))} · "
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
                    api_delete_profile(selected)
                except BackendError as exc:
                    _flash("error", f"Профиль не удалён: {exc.message}")
                else:
                    _flash("success",
                           f"Профиль **{selected}** удалён: агенты этого "
                           "пользователя снова работают без персонализации.")
                _load_agents()
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
            api_set_agent_user(agent_id, target)
        except BackendError as exc:
            _flash("error", f"Профиль не переключён: {exc.message}")
        else:
            _flash("success",
                   f"Агент **{active['name']}** теперь использует профиль "
                   f"`{target}`.")
        _load_agents()
        st.session_state["chat_agent_id"] = None
        st.rerun()

    try:
        applied = api_agent_profile(agent_id)
    except BackendError as exc:
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
    render_profile_comparison(by_id)


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


# ================= UI: состояние и helpers =================
st.set_page_config(page_title="Память и профиль · День 12",
                   page_icon="🧠", layout="wide")

# Состояние, переживающее rerun'ы Streamlit.
if "agents" not in st.session_state:
    st.session_state["agents"] = []
if "active_agent_id" not in st.session_state:
    st.session_state["active_agent_id"] = None
if "backend_ok" not in st.session_state:
    st.session_state["backend_ok"] = False
if "backend_error" not in st.session_state:
    st.session_state["backend_error"] = None
# Кэш показанного диалога: chat_agent_id — какому агенту принадлежит список.
if "chat_agent_id" not in st.session_state:
    st.session_state["chat_agent_id"] = None
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []
# Одноразовое сообщение-флеш (kind, text) для следующего прохода скрипта.
if "flash" not in st.session_state:
    st.session_state["flash"] = None
# Отчёт по слоям памяти из последней генерации: agent_id -> record["memory"].
if "last_memory" not in st.session_state:
    st.session_state["last_memory"] = {}


def _flash(kind: str, message: str) -> None:
    """Показывает сообщение на СЛЕДУЮЩЕМ проходе (после st.rerun)."""
    st.session_state["flash"] = (kind, message)


def _load_agents():
    """Свежий список агентов; ошибка соединения — в состояние, без падения."""
    try:
        st.session_state["agents"] = api_fetch_agents()
        st.session_state["backend_ok"] = True
        st.session_state["backend_error"] = None
    except BackendError as exc:
        st.session_state["agents"] = []
        st.session_state["backend_ok"] = False
        st.session_state["backend_error"] = str(exc)


def _active_agent():
    """Возвращает выбранного агента (словарь) или None; чинит active_agent_id."""
    agents = st.session_state.get("agents") or []
    if not agents:
        st.session_state["active_agent_id"] = None
        st.session_state["chat_agent_id"] = None
        return None
    current = st.session_state.get("active_agent_id")
    if current is None or not any(a["agent_id"] == current for a in agents):
        current = agents[0]["agent_id"]
        st.session_state["active_agent_id"] = current
    return next(a for a in agents if a["agent_id"] == current)


def _ensure_chat(active):
    """Подгружает диалог активного агента, если он ещё не в состоянии."""
    if active is None:
        return
    if st.session_state.get("chat_agent_id") == active["agent_id"]:
        return
    try:
        st.session_state["chat_messages"] = api_history(active["agent_id"])
        st.session_state["chat_agent_id"] = active["agent_id"]
    except BackendError as exc:
        st.session_state["chat_messages"] = []
        st.session_state["chat_agent_id"] = active["agent_id"]
        st.warning(f"Диалог не загружен: {exc.message}")


# ================= UI: боковая панель =================
_load_agents()
st.sidebar.title("🧠 Память агента")
if st.session_state["backend_ok"]:
    st.sidebar.caption(f"🟢 Бэкенд: {BACKEND_URL} · агентов: "
                       f"{len(st.session_state['agents'])}")
else:
    st.sidebar.caption(f"🔴 Бэкенд недоступен: {BACKEND_URL}")
if st.sidebar.button("🔄 Обновить список"):
    _load_agents()

# --- создание нового агента ---
st.sidebar.subheader("➕ Новый агент")
try:
    profile_ids = [user["user_id"] for user in api_list_users()]
except BackendError:
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
            info = api_create_agent({
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
        except BackendError as exc:
            st.sidebar.error(f"Не удалось создать: {exc.message}")
        else:
            _load_agents()
            st.session_state["active_agent_id"] = info["agent_id"]
            st.session_state["chat_agent_id"] = None  # перечитаем диалог
            st.sidebar.success(
                f"Создан: {info['name']} ({info['agent_id']}) · профиль "
                f"{info.get('user_id', 'default')}"
            )


# --- стратегия контекста активного агента (день 11) ---
if st.session_state["backend_ok"] and st.session_state["agents"]:
    active = _active_agent()
    if active is not None:
        st.sidebar.subheader("⚙️ Стратегия контекста")
        st.sidebar.caption(f"Агент: **{active['name']}**")
        current_strategy = active.get("strategy", "summary")
        current_window = int(active.get("window_size", 10))
        options = list(STRATEGY_LABELS.keys())
        if current_strategy not in options:
            current_strategy = "summary"
        with st.sidebar.form(f"strategy_form_{active['agent_id']}"):
            chosen = st.selectbox(
                "Стратегия", options, index=options.index(current_strategy),
                format_func=lambda s: STRATEGY_LABELS[s],
            )
            window = st.slider("window_size (последних реплик)", 2, 50,
                               current_window,
                               help="Для sliding_window и sticky_facts: сколько "
                                    "последних реплик уходит в запрос.")
            apply_strategy = st.form_submit_button("Применить стратегию")
        if apply_strategy:
            try:
                api_set_strategy(active["agent_id"], chosen, window)
            except BackendError as exc:
                st.sidebar.error(f"Не удалось сменить стратегию: {exc.message}")
            else:
                _load_agents()
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
            tasks = api_working(agent_id).get("tasks") or []
        except BackendError:
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
                api_set_task(agent_id, task_choice)
            except BackendError as exc:
                st.sidebar.error(f"Не удалось переключить задачу: {exc.message}")
            else:
                _flash("info", f"Активная задача: {task_choice}.")
                _load_agents()
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
                    result = api_set_task(agent_id, new_task.strip())
                except BackendError as exc:
                    st.sidebar.error(f"Не удалось создать задачу: {exc.message}")
                else:
                    _flash("success",
                           f"Активная задача: {result.get('task_id')} "
                           f"(записей: {result.get('entries', 0)}).")
                    _load_agents()
                    st.rerun()

        if st.sidebar.button("🆕 Новая сессия",
                             help="Краткосрочная память обнуляется (диалог, "
                                  "конспекты и факты), рабочая и долговременная "
                                  "память сохраняются."):
            try:
                session = api_new_session(agent_id)
            except BackendError as exc:
                st.sidebar.error(f"Не удалось начать сессию: {exc.message}")
            else:
                st.session_state["chat_agent_id"] = None
                st.session_state["last_memory"] = {}
                _flash("success",
                       f"Новая сессия {session.get('session_id')}: удалено "
                       f"реплик {session.get('deleted_messages', 0)}. Рабочая и "
                       "долговременная память сохранены.")
                _load_agents()
                st.rerun()


# ================= UI: основная область — чат =================
st.title("💬 Чат с агентами DeepSeek · три слоя памяти")
st.caption("Агент помнит диалог в SQLite и раскладывает память по трём слоям: "
           "краткосрочная (текущая сессия), рабочая (текущая задача) и "
           "долговременная (профиль и предпочтения). Слои памяти — в панелях "
           "ниже, переключатель задачи и кнопка новой сессии — в боковой панели.")

flash = st.session_state.pop("flash", None)
if flash:
    kind, message = flash
    if kind == "success":
        st.success(message)
    elif kind == "error":
        st.error(message)
    else:
        st.info(message)

if not st.session_state["backend_ok"]:
    st.warning("🔌 Бэкенд недоступен. Запустите его из папки day12/:")
    st.code("uvicorn backend.main:app --port 8000", language="bash")
    if st.session_state.get("backend_error"):
        st.caption(f"Причина: {st.session_state['backend_error']}")
else:
    agents = st.session_state["agents"]
    # Разделы переключаются st.radio, а не st.tabs: выбор вкладки Streamlit не
    # сохраняет между перезапусками скрипта, а после «Сохранить профиль» нужен
    # st.rerun — с radio пользователь остаётся в том же разделе.
    section = st.radio(
        "Раздел", ["💬 Чат и память", "👤 Профиль пользователя"],
        horizontal=True, key="main_section", label_visibility="collapsed",
    )
    if section.startswith("👤"):
        render_profile_section(_active_agent())
    else:
        if not agents:
            st.info("Агентов пока нет — создайте первого в боковой панели. "
                    "Его диалог, слои памяти и метрики сохранятся в "
                    "day12/agents.db.")
        else:
            # --- выбор агента (список с числом сообщений и режимом сжатия) ---
            labels = [label_agent(a) for a in agents]
            active = _active_agent()
            idx = next(i for i, a in enumerate(agents)
                       if a["agent_id"] == active["agent_id"])
            chosen = st.selectbox("Агент", labels, index=idx,
                                  help="Переключение загружает диалог агента.")
            active = agents[labels.index(chosen)]
            st.session_state["active_agent_id"] = active["agent_id"]

            col_card, col_del = st.columns([5, 1])
            with col_card:
                st.subheader(f"🤖 {active['name']}")
                strategy = active.get("strategy", "summary")
                strategy_label = STRATEGY_LABELS.get(strategy, strategy)
                st.caption(
                    f"id `{active['agent_id']}` · модель **{active['model']}** · "
                    f"температура {active.get('temperature', '—')} · "
                    f"max_tokens {active.get('max_tokens', '—')}"
                )
                st.markdown(
                    f"**Стратегия:** {strategy_label} · window_size "
                    f"{active.get('window_size', '—')}"
                )
                st.markdown(
                    f"**Профиль пользователя (день 12):** "
                    f"`{active.get('user_id', 'default')}` — настройки и "
                    "кастомные инструкции во вкладке «👤 Профиль пользователя»"
                )
                if strategy == "branching":
                    try:
                        tree = api_branches(active["agent_id"])
                        active_id = tree.get("active_branch_id")
                    except BackendError:
                        active_id = None
                    st.caption(f"🌿 Активная ветка: **{active_id}**")
                if active.get("system_prompt"):
                    st.caption(f"Роль: _{active['system_prompt']}_")
            with col_del:
                if st.button("🗑 Удалить агента",
                             help="Удалить вместе с диалогом, конспектами и метриками"):
                    try:
                        api_delete_agent(active["agent_id"])
                    except BackendError as exc:
                        st.error(f"Не удалось удалить: {exc.message}")
                    else:
                        _load_agents()
                        st.session_state["chat_agent_id"] = None
                        st.success("Агент удалён.")

            # --- панели по стратегии + панель токенов ---
            strategy = active.get("strategy", "summary")
            if strategy == "summary":
                render_compression_panel(active)
            elif strategy == "sticky_facts":
                render_facts_panel(active)
            elif strategy == "branching":
                render_branching_panel(active)
            render_token_panel(active)

            # --- слои памяти агента: три панели + индикация последнего запроса ---
            render_memory_panels(active)
            render_memory_indicator(active)

            st.divider()

            # --- диалог: роль + текст каждого сообщения + маркер сжатия ---
            _ensure_chat(active)
            st.subheader("💬 Диалог")
            chat_box = st.container(height=420, border=False)
            messages = st.session_state.get("chat_messages") or []
            with chat_box:
                if not messages:
                    st.info("Диалог пуст. Напишите первое сообщение — и агент "
                            "запомнит его после перезапуска.")
                # Маркер ставим на границе: где кончаются покрытые конспектом
                # реплики и начинается отправляемый «как есть» хвост.
                marker_done = False
                for msg in messages:
                    if (not marker_done and msg.get("summarized") is False
                            and any(m.get("summarized") for m in messages)):
                        covered = sum(1 for m in messages if m.get("summarized"))
                        try:
                            state = api_summary(active["agent_id"])
                            summary_tokens = (state.get("current") or {}).get(
                                "summary_tokens", 0)
                        except BackendError:
                            summary_tokens = 0
                        render_summary_marker(covered, summary_tokens)
                        marker_done = True
                    render_message(msg.get("role", ""),
                                   msg.get("content", ""),
                                   msg.get("created_at", ""))

            # --- сравнение режимов (день 9) ---
            render_compare(active)

            # --- поле ввода и кнопки внизу ---
            # Форма: значения виджетов уходят на сервер по нажатию «Отправить», а не
            # по потере фокуса, поэтому отправка работает сразу после набора текста.
            with st.form(key=f"chat_form_{active['agent_id']}", clear_on_submit=True):
                prompt = st.text_area(
                    "Сообщение агенту", key=f"prompt_{active['agent_id']}",
                    height=90, placeholder="Введите сообщение и нажмите «Отправить»…",
                )
                sent = st.form_submit_button(
                    "🚀 Отправить", type="primary",
                    help="Контекст собирается текущей стратегией "
                         "(окно / факты / ветка / конспект).",
                )
            if sent and not prompt.strip():
                st.info("Пустое сообщение не отправлено: введите текст.")
            elif sent:
                with st.spinner("🤖 Агент думает… это занимает несколько секунд"):
                    try:
                        record = api_generate(active["agent_id"], prompt)
                    except BackendError as exc:
                        _flash("error", f"Запрос не выполнен: {exc.message}")
                        st.rerun()
                    else:
                        if record.get("status") == "ok":
                            # Сервер вернул актуальную историю — рисуем из неё.
                            st.session_state["chat_messages"] = record.get("messages", [])
                            st.session_state["chat_agent_id"] = active["agent_id"]
                            _load_agents()  # обновить счётчики в боковой панели
                            tm = record.get("token_metrics") or {}
                            ctx = record.get("context") or {}
                            comp = ctx.get("compression") or {}
                            mem = record.get("memory") or {}
                            st.session_state["last_memory"][active["agent_id"]] = mem
                            notes = []
                            if comp.get("summary_used"):
                                notes.append(
                                    f"🗜 конспект: сэкономлено "
                                    f"{fmt_int(comp.get('saved_tokens'))} токенов "
                                    f"({comp.get('saved_percent')}%)")
                            if mem:
                                notes.append(
                                    f"слои: короткая "
                                    f"{fmt_int(mem.get('short_term_tokens'))} / рабочая "
                                    f"{fmt_int(mem.get('working_tokens'))} / "
                                    f"долговременная "
                                    f"{fmt_int(mem.get('long_term_tokens'))} токенов")
                            applied_profile = record.get("profile") or {}
                            if applied_profile.get("personalized"):
                                notes.append(
                                    f"👤 профиль {applied_profile.get('user_id')}: "
                                    f"{len(applied_profile.get('elements') or [])} "
                                    "элементов")
                            else:
                                notes.append("👤 профиль: без персонализации")
                            if ctx.get("trimmed_messages"):
                                notes.append(f"⚠️ пропущено реплик в запросе: "
                                             f"{ctx['trimmed_messages']}")
                            if ctx.get("warning"):
                                notes.append(ctx["warning"])
                            if comp.get("error"):
                                notes.append(f"⚠️ сжатие не выполнено: {comp['error']}")
                            note_text = (" · " + " · ".join(notes)) if notes else ""
                            # Одна плашка на ход: ошибка сжатия — красная, остальное —
                            # успешная сводка (иначе второе сообщение затирает первое).
                            kind = "error" if comp.get("error") else "success"
                            _flash(kind,
                                   f"Ответ получен за {record.get('duration_sec', 0):.2f} с · "
                                   f"токены {format_usage(record.get('usage'))} · "
                                   f"стоимость ~${tm.get('cost', 0):.6f} · "
                                   f"finish_reason {record.get('finish_reason') or '—'}"
                                   f"{note_text}")
                        else:
                            _flash("error", f"Генерация завершилась ошибкой: "
                                            f"{record.get('error')}")
                        st.rerun()
            if st.button("🧹 Очистить историю",
                         help="Удаляет диалог, конспекты и метрики. "
                              "Конфигурация агента не меняется."):
                try:
                    api_clear_history(active["agent_id"])
                except BackendError as exc:
                    _flash("error", f"Не удалось очистить: {exc.message}")
                    st.rerun()
                else:
                    st.session_state["chat_messages"] = []
                    st.session_state["chat_agent_id"] = active["agent_id"]
                    _load_agents()
                    _flash("success", "История, конспекты и метрики очищены. "
                                      "Новый диалог начнётся с нуля.")
                    st.rerun()
