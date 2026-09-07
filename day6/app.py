"""День 6: Streamlit-фронтенд для управления агентами DeepSeek.

Приложение общается с FastAPI-бэкендом (порт 8000) по HTTP через `requests`.
Ключ DEEPSEEK_API_KEY фронтенду НЕ нужен — его читает бэкенд (day6/.env или
переменная окружения). Агенты живут в памяти бэкенда; при его перезапуске они
исчезают (см. docs/usage.md).

Запуск из папки day6/:  .venv/Scripts/python -m streamlit run app.py
"""
import html
import os

import requests
import streamlit as st

# Куда стучится фронтенд (можно переопределить переменной окружения).
BACKEND_URL = os.environ.get("DAY6_BACKEND_URL", "http://127.0.0.1:8000")
TIMEOUT = 10.0  # сек; тут только общение с бэкендом (генерация идёт у него)

# Шаблоны ролей для массового создания (D10: ротация системных промптов).
SYSTEM_PROMPT_TEMPLATES = [
    "Ты — дружелюбный ассистент. Отвечай кратко и по делу.",
    "Ты — строгий критик: ищи слабые места и недочёты в тексте собеседника.",
    "Ты — конспектёр: излагай суть тезисами, без воды.",
    "Ты — переводчик с «сложного» на простой язык: объясняй понятия простыми словами.",
]


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
            f"Бэкенд недоступен ({BACKEND_URL}). Запустите его из папки day6/: "
            f".venv/Scripts/python -m uvicorn backend.main:app --port 8000 "
            f"({exc.__class__.__name__})"
        ) from exc
    if resp.status_code >= 400:
        raise BackendError(_extract_error(resp), resp.status_code)
    return resp.json()


def api_fetch_agents():
    """GET /agents -> список кратких записей об агентах."""
    return _request("GET", "/agents")


def api_create_agent(config):
    """POST /agents -> полная информация о созданном агенте."""
    return _request("POST", "/agents", json=config)


def api_delete_agent(agent_id):
    """DELETE /agents/{agent_id}."""
    return _request("DELETE", f"/agents/{agent_id}")


def api_generate(agent_id, prompt):
    """POST /agents/{agent_id}/generate -> запись-результат (status ok/error).

    При сбое генерации бэкенд отвечает 502: _request поднимет BackendError с
    понятным текстом (например, «Ключ API не задан...»).
    """
    return _request("POST", f"/agents/{agent_id}/generate", json={"prompt": prompt})


def api_history(agent_id):
    """GET /agents/{agent_id}/history -> список попыток (новые первыми)."""
    return _request("GET", f"/agents/{agent_id}/history")


# ---------- форматирование для UI ----------
def esc(text):
    """Безопасный вывод: экранирует HTML и сохраняет переносы строк."""
    if text is None:
        return ""
    return html.escape(str(text)).replace("\n", "<br>")


def format_usage(usage) -> str:
    if not usage:
        return "—"
    return (f"вход {usage.get('prompt_tokens', '?')} · "
            f"выход {usage.get('completion_tokens', '?')} · "
            f"всего {usage.get('total_tokens', '?')}")


def label_agent(agent) -> str:
    return f"{agent['name']} · {agent['model']} ({agent['agent_id']})"

# ================= UI: состояние и helpers =================
st.set_page_config(page_title="Менеджер агентов DeepSeek · День 6",
                   page_icon="🤖", layout="wide")

# Состояние, переживающее rerun'ы Streamlit.
if "agents" not in st.session_state:
    st.session_state["agents"] = []
if "active_agent_id" not in st.session_state:
    st.session_state["active_agent_id"] = None
if "backend_ok" not in st.session_state:
    st.session_state["backend_ok"] = False
if "backend_error" not in st.session_state:
    st.session_state["backend_error"] = None
if "last_record" not in st.session_state:
    st.session_state["last_record"] = None


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
        return None
    current = st.session_state.get("active_agent_id")
    if current is None or not any(a["agent_id"] == current for a in agents):
        current = agents[0]["agent_id"]
        st.session_state["active_agent_id"] = current
    return next(a for a in agents if a["agent_id"] == current)


def _bulk_config(index):
    """Детерминированно разные конфигурации для массового создания (D10)."""
    i = index
    return {
        "name": f"agent-{i:04d}",
        "model": "deepseek-reasoner" if i % 10 == 0 else "deepseek-chat",
        "temperature": round(0.2 + (i % 16) * 0.1, 1),  # 0.2 … 1.7 по кругу
        "system_prompt": SYSTEM_PROMPT_TEMPLATES[i % len(SYSTEM_PROMPT_TEMPLATES)],
        "max_tokens": (1024, 2048, 4096)[i % 3],
    }


# ================= UI: sidebar =================
_load_agents()
st.sidebar.title("🤖 Агенты DeepSeek")
if st.session_state["backend_ok"]:
    count = len(st.session_state["agents"])
    st.sidebar.caption(f"🟢 Бэкенд: {BACKEND_URL} · агентов: {count}")
else:
    st.sidebar.caption(f"🔴 Бэкенд недоступен: {BACKEND_URL}")
if st.sidebar.button("🔄 Обновить список"):
    _load_agents()

# --- создание одного агента ---
st.sidebar.subheader("➕ Новый агент")
with st.sidebar.form("create_agent_form", clear_on_submit=True):
    form_name = st.text_input("Имя", placeholder="Например: Редактор")
    form_model = st.selectbox("Модель", ["deepseek-chat", "deepseek-reasoner"])
    form_temp = st.slider("Температура", 0.0, 2.0, 0.7, 0.1)
    form_system = st.text_area(
        "Системный промпт", height=100,
        help="Роль/инструкции агента. Пусто — системное сообщение не добавляется.",
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
            st.sidebar.success(f"Создан: {info['name']} ({info['agent_id']})")

# --- массовое создание ---
st.sidebar.subheader("⚡ Массовое создание")
bulk_count = st.sidebar.number_input("Сколько агентов", 10, 100, 10, step=10,
                                     help="Каждый агент получает разные параметры.")
if st.sidebar.button(
    f"Заспавнить {int(bulk_count)} агентов",
    help="Демонстрация масштабируемости: создание экземпляров не обращается "
         "к DeepSeek и занимает мгновения.",
):
    with st.spinner(f"Создаю {int(bulk_count)} агентов..."):
        created_ok, errors = 0, 0
        for i in range(1, int(bulk_count) + 1):
            try:
                api_create_agent(_bulk_config(i))
                created_ok += 1
            except BackendError:
                errors += 1
        _load_agents()
    if errors:
        st.sidebar.warning(f"Создано {created_ok}, ошибок: {errors}.")
    else:
        st.sidebar.success(f"Создано агентов: {created_ok} 🎉")


# ================= UI: основная область =================
st.title("🤖 Менеджер агентов DeepSeek")

if not st.session_state["backend_ok"]:
    st.warning("🔌 Бэкенд недоступен. Интерфейс работает, но операции станут "
               "доступны после запуска сервера:")
    st.code("cd day6\n.venv/Scripts/python -m uvicorn backend.main:app --port 8000",
            language="bash")
    if st.session_state.get("backend_error"):
        st.caption(f"Причина: {st.session_state['backend_error']}")
else:
    agents = st.session_state["agents"]
    if not agents:
        st.info("Агентов пока нет. Создайте первого в боковой панели или "
                "заспавньте сразу несколько для демонстрации масштабируемости.")
    else:
        # --- выбор активного агента ---
        labels = [label_agent(a) for a in agents]
        active = _active_agent()
        idx = next(i for i, a in enumerate(agents) if a["agent_id"] == active["agent_id"])
        chosen = st.selectbox("Активный агент", labels, index=idx)
        active = agents[labels.index(chosen)]
        st.session_state["active_agent_id"] = active["agent_id"]

        col_card, col_del = st.columns([5, 1])
        with col_card:
            st.subheader(f"Агент: {active['name']}")
            st.caption(
                f"id `{active['agent_id']}` · модель **{active['model']}** · "
                f"температура {active.get('temperature', '—')} · "
                f"max_tokens {active.get('max_tokens', '—')}"
            )
        with col_del:
            if st.button("🗑 Удалить", help="Удалить активного агента вместе с историей"):
                try:
                    api_delete_agent(active["agent_id"])
                except BackendError as exc:
                    st.error(f"Не удалось удалить: {exc.message}")
                else:
                    _load_agents()
                    st.session_state["last_record"] = None
                    st.success("Агент удалён.")

        st.divider()

        # --- запрос и генерация ---
        st.subheader("💬 Запрос")
        prompt_text = st.text_area("Введите запрос для агента", height=120)
        if st.button("🚀 Отправить запрос", type="primary",
                     disabled=not prompt_text.strip()):
            if not prompt_text.strip():
                st.error("Запрос не может быть пустым.")
            else:
                try:
                    record = api_generate(active["agent_id"], prompt_text)
                except BackendError as exc:
                    st.error(f"Запрос не выполнен: {exc.message}")
                    st.session_state["last_record"] = None
                else:
                    st.session_state["last_record"] = record

        last = st.session_state.get("last_record")
        if last and last.get("agent_id") == active["agent_id"]:
            if last["status"] == "ok":
                st.success(f"Ответ получен за {last.get('duration_sec', 0):.2f} с.")
                st.markdown(f"<div style='white-space:normal'>{esc(last.get('response'))}</div>",
                            unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Время", f"{last.get('duration_sec', 0):.2f} с")
                c2.metric("Токены", format_usage(last.get("usage")))
                c3.metric("finish_reason", last.get("finish_reason") or "—")
                c4.metric("Модель", last.get("model") or "—")
            else:
                st.error(f"Генерация завершилась ошибкой: {last.get('error')}")

        st.divider()

        # --- история агента ---
        st.subheader("🗂 История запросов")
        try:
            history = api_history(active["agent_id"])
        except BackendError:
            history = []
            st.caption("Историю не удалось загрузить (бэкенд недоступен).")
        if not history:
            st.caption("Пока нет ни одной попытки — отправьте первый запрос выше.")
        for entry in history[:20]:
            status_tag = ("✅" if entry["status"] == "ok" else "❌")
            with st.expander(
                f"{status_tag} {str(entry.get('timestamp', ''))[:19].replace('T', ' ')} · "
                f"{entry.get('duration_sec', 0):.2f} с · {entry.get('model', '')}"
            ):
                st.markdown(f"**Запрос:**<br>{esc(entry.get('prompt'))}",
                            unsafe_allow_html=True)
                if entry["status"] == "ok":
                    st.markdown(f"**Ответ:**<br>{esc(entry.get('response'))}",
                                unsafe_allow_html=True)
                    st.caption(
                        f"finish_reason: {entry.get('finish_reason') or '—'} · "
                        f"токены: {format_usage(entry.get('usage'))}"
                    )
                else:
                    st.error(f"Ошибка: {entry.get('error')}")
        if len(history) > 20:
            st.caption(f"Показаны последние 20 из {len(history)} записей.")

