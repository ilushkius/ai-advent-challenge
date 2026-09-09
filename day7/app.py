"""День 7: Streamlit-чат агентов DeepSeek с контекстной памятью.

Приложение общается с FastAPI-бэкендом (порт 8000) по HTTP через `requests`.
Ключ DEEPSEEK_API_KEY фронтенду НЕ нужен — его читает бэкенд (day7/.env или
переменная окружения). Диалоги агентов хранит бэкенд в SQLite (day7/agents.db)
и восстанавливает их после рестарта — поэтому чат продолжается с того же места.

Интерфейс — полноценный чат: основная область показывает все сообщения
выбранного агента (роль + текст), внизу — поле ввода и кнопки «Отправить» и
«Очистить историю»; в боковой панели — список агентов с числом сообщений.

Запуск из папки day7/:  streamlit run app.py  (бэкенд запускается отдельно:
uvicorn backend.main:app --port 8000)
"""
import html
import os

import requests
import streamlit as st

# Куда стучится фронтенд (можно переопределить переменной окружения).
BACKEND_URL = os.environ.get("DAY7_BACKEND_URL", "http://127.0.0.1:8000")
TIMEOUT = 30.0  # сек; генерация идёт на бэкенде (вызов DeepSeek до 60 с)

# Подписи ролей для отрисовки сообщений чата.
ROLE_LABELS = {"user": "🧑 Вы", "assistant": "🤖 Ассистент"}


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
            f"Бэкенд недоступен ({BACKEND_URL}). Запустите его из папки day7/: "
            f"uvicorn backend.main:app --port 8000 "
            f"({exc.__class__.__name__})"
        ) from exc
    if resp.status_code >= 400:
        raise BackendError(_extract_error(resp), resp.status_code)
    return resp.json()


def api_fetch_agents():
    """GET /agents -> список записей (id, имя, модель, message_count)."""
    return _request("GET", "/agents")


def api_create_agent(config):
    """POST /agents -> полная информация о созданном агенте."""
    return _request("POST", "/agents", json=config)


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
    """DELETE /agents/{agent_id}/history -> очистка диалога."""
    return _request("DELETE", f"/agents/{agent_id}/history")


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


def label_agent(agent) -> str:
    """Подпись агента в списке: имя · модель · число сообщений."""
    n = agent.get("message_count", 0)
    if n % 10 == 1 and n % 100 != 11:
        word = "сообщение"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = "сообщения"
    else:
        word = "сообщений"
    return f"{agent['name']} · {agent['model']} · {n} {word}"


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


def format_usage(usage) -> str:
    if not usage:
        return "—"
    return (f"вход {usage.get('prompt_tokens', '?')} · "
            f"выход {usage.get('completion_tokens', '?')} · "
            f"всего {usage.get('total_tokens', '?')}")


# ================= UI: состояние и helpers =================
st.set_page_config(page_title="Агенты с памятью · День 7",
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
st.sidebar.title("🧠 Агенты с памятью")
if st.session_state["backend_ok"]:
    st.sidebar.caption(f"🟢 Бэкенд: {BACKEND_URL} · агентов: "
                       f"{len(st.session_state['agents'])}")
else:
    st.sidebar.caption(f"🔴 Бэкенд недоступен: {BACKEND_URL}")
if st.sidebar.button("🔄 Обновить список"):
    _load_agents()

# --- создание нового агента ---
st.sidebar.subheader("➕ Новый агент")
with st.sidebar.form("create_agent_form", clear_on_submit=True):
    form_name = st.text_input("Имя агента", placeholder="Например: Конспектёр")
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
            })
        except BackendError as exc:
            st.sidebar.error(f"Не удалось создать: {exc.message}")
        else:
            _load_agents()
            st.session_state["active_agent_id"] = info["agent_id"]
            st.session_state["chat_agent_id"] = None  # перечитаем диалог
            st.sidebar.success(f"Создан: {info['name']} ({info['agent_id']})")


# ================= UI: основная область — чат =================
st.title("💬 Чат с агентами DeepSeek")
st.caption("Каждый агент помнит диалог: история хранится в SQLite на бэкенде "
           "и переживает его перезапуск.")

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
    st.warning("🔌 Бэкенд недоступен. Запустите его из папки day7/:")
    st.code("uvicorn backend.main:app --port 8000", language="bash")
    if st.session_state.get("backend_error"):
        st.caption(f"Причина: {st.session_state['backend_error']}")
else:
    agents = st.session_state["agents"]
    if not agents:
        st.info("Агентов пока нет — создайте первого в боковой панели. "
                "Его диалог сохранится в базе day7/agents.db и переживёт "
                "перезапуск приложения.")
    else:
        # --- выбор агента (список с числом сообщений у каждого) ---
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
            st.caption(
                f"id `{active['agent_id']}` · модель **{active['model']}** · "
                f"температура {active.get('temperature', '—')} · "
                f"max_tokens {active.get('max_tokens', '—')}"
            )
            if active.get("system_prompt"):
                st.caption(f"Роль: _{active['system_prompt']}_")
        with col_del:
            if st.button("🗑 Удалить агента",
                         help="Удалить вместе с диалогом из БД"):
                try:
                    api_delete_agent(active["agent_id"])
                except BackendError as exc:
                    st.error(f"Не удалось удалить: {exc.message}")
                else:
                    _load_agents()
                    st.session_state["chat_agent_id"] = None
                    st.success("Агент удалён.")


        st.divider()

        # --- диалог: роль + текст каждого сообщения ---
        _ensure_chat(active)
        st.subheader("💬 Диалог")
        chat_box = st.container(height=420, border=False)
        messages = st.session_state.get("chat_messages") or []
        with chat_box:
            if not messages:
                st.info("Диалог пуст. Напишите первое сообщение — и агент "
                        "запомнит его после перезапуска.")
            for msg in messages:
                render_message(msg.get("role", ""),
                               msg.get("content", ""),
                               msg.get("timestamp", ""))

        # --- поле ввода и кнопки внизу ---
        prompt = st.text_area(
            "Сообщение агенту", key=f"prompt_{active['agent_id']}",
            height=90, placeholder="Введите сообщение и нажмите «Отправить»…",
        )
        col_send, col_clear = st.columns(2)
        can_send = bool(prompt and prompt.strip())
        if col_send.button("🚀 Отправить", type="primary", disabled=not can_send,
                           help="Вся история + запрос уходят в DeepSeek"):
            # Генерация синхронная: бэкенд ждёт ответ DeepSeek (обычно 1–5 с,
            # дольше на длинной истории/больших max_tokens). Показываем спиннер,
            # чтобы процесс был виден, а не выглядел «зависанием».
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
                        _flash("success",
                               f"Ответ получен за {record.get('duration_sec', 0):.2f} с · "
                               f"токены {format_usage(record.get('usage'))} · "
                               f"finish_reason {record.get('finish_reason') or '—'}")
                    else:
                        _flash("error", f"Генерация завершилась ошибкой: "
                                        f"{record.get('error')}")
                    st.rerun()
        if col_clear.button("🧹 Очистить историю",
                            help="Удаляет диалог агента из SQLite. Конфигурация "
                                 "агента не меняется."):
            try:
                api_clear_history(active["agent_id"])
            except BackendError as exc:
                _flash("error", f"Не удалось очистить: {exc.message}")
                st.rerun()
            else:
                st.session_state["chat_messages"] = []
                st.session_state["chat_agent_id"] = active["agent_id"]
                _load_agents()
                _flash("success", "История очищена. Новый диалог начнётся с нуля.")
                st.rerun()

