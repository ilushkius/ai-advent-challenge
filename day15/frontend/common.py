"""Общие помощники интерфейса дня 15 (наследовано из дня 12): подписи, форматтеры и состояние страницы.

Здесь живут словари человекочитаемых подписей (роли, стратегии, категории
долговременной памяти, слои памяти, состояния стейт-машины сжатия, состояния и
флаги задачи, инварианты дня 14), форматтеры значений и всё, что связано с
``st.session_state``: инициализация состояния, одноразовое флеш-сообщение,
загрузка списка агентов и выбор активного. Сюда же вынесен единый путь мутаций
панели задачи ``run_task_action`` (день 15): им пользуются и панель состояния, и
блок переходов, поэтому сообщение об отказе правил допуска выглядит одинаково.
"""
import html

import streamlit as st

from . import api_client


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


# Состояния задачи (день 13): этап FSM → человекочитаемая подпись для UI.
TASK_STAGE_LABELS = {
    "planning": "🧭 planning — планирование",
    "execution": "⚙️ execution — выполнение",
    "validation": "🔍 validation — валидация",
    "done": "✅ done — завершено",
    "paused": "⏸ paused — пауза",
}


# Согласования этапов (день 15): флаг context → подпись чекбокса. Переход вперёд
# закрыт, пока согласование не выставлено, поэтому подпись объясняет, что именно
# подтверждает пользователь.
TASK_FLAG_LABELS = {
    "plan_approved": "📝 План утверждён",
    "implementation_complete": "⚙️ Реализация завершена",
    "validation_passed": "✅ Валидация пройдена",
}

# Этапы, между которыми переключает пользователь: порядок кнопок в панели задачи.
TASK_TRANSITION_STAGES = ("planning", "execution", "validation", "done", "paused")

# Подписи кнопок-переходов: у паузы оно своё (это не «ещё один этап», а остановка).
PAUSE_BUTTON_LABEL = "⏸ Пауза"


def stage_button_label(stage: str) -> str:
    """Подпись кнопки перехода: пауза отдельной строкой, остальные — «➡️ этап»."""
    if stage == "paused":
        return PAUSE_BUTTON_LABEL
    return f"➡️ {TASK_STAGE_LABELS.get(stage, stage)}"


def blocked_reason(state: dict, stage: str) -> str:
    """Почему переход в этап недоступен (``""`` — этап доступен).

    Причина приходит с бэкенда (``state["blocked"]``) — фронт не повторяет
    правила допуска, а показывает то, что решил домен.
    """
    for item in state.get("blocked") or []:
        if item.get("stage") == stage:
            return item.get("reason") or ""
    return ""


def run_task_action(action, success: str, failure: str) -> None:
    """Единый путь мутаций панели задачи: вызвать, сообщить, перерисовать.

    Ошибка бэкенда не должна выглядеть как «ничего не произошло»: причина
    показывается красным сообщением (в ней — объяснение правил допуска), а
    успешная мутация сбрасывает кэш диалога, потому что состояние задачи
    попадает в системный промпт следующего запроса.
    """
    try:
        action()
    except api_client.BackendError as exc:
        flash("error", f"{failure}: {exc.message}")
    else:
        flash("success", success)
        st.session_state["chat_agent_id"] = None
    load_agents()
    st.rerun()


# Инварианты (день 14): значение → человекочитаемая подпись (таблицы и селекторы).
# Копии словарей домена: frontend не импортирует backend, только HTTP.
INVARIANT_CATEGORY_LABELS = {
    "architecture": "архитектура",
    "tech_decisions": "технические решения",
    "stack_constraints": "ограничения стека",
    "business_rules": "бизнес-правила",
}
INVARIANT_SEVERITY_LABELS = {
    "hard": "hard — отказ при нарушении",
    "soft": "soft — предупреждение",
}
INVARIANT_VERDICT_LABELS = {
    "allowed": "нарушений нет",
    "warning": "предупреждение",
    "refusal": "отказ",
}


def invariant_notice(invariants: dict) -> str:
    """Текст предупреждения/отказа по инвариантам для области чата.

    Пустая строка — нарушений нет. Строки: заголовок «📏 Инварианты: отказ» или
    «📏 Инварианты: предупреждение» и по строке на нарушение —
    «• [hard] Имя (архитектура) — причина». Подписи категорий — человекочитаемые:
    в отказе для пользователя важнее «архитектура», чем «architecture».
    """
    violations = (invariants or {}).get("violations") or []
    if not violations:
        return ""
    verdict = (invariants or {}).get("verdict", "")
    title = INVARIANT_VERDICT_LABELS.get(verdict, verdict)
    lines = [f"📏 Инварианты: {title}"]
    for item in violations:
        category = INVARIANT_CATEGORY_LABELS.get(
            item.get("category"), item.get("category", "")
        )
        lines.append(
            f"• [{item.get('severity')}] {item.get('name')} ({category}) — "
            f"{item.get('reason')}"
        )
    return "\n".join(lines)


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


def init_state() -> None:
    """Заводит ключи ``st.session_state`` при первом проходе скрипта."""
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
    # Предупреждение/отказ по инвариантам последнего хода: (verdict, текст).
    if "invariant_notice" not in st.session_state:
        st.session_state["invariant_notice"] = None


def flash(kind: str, message: str) -> None:
    """Показывает сообщение на СЛЕДУЮЩЕМ проходе (после st.rerun)."""
    st.session_state["flash"] = (kind, message)


def load_agents():
    """Свежий список агентов; ошибка соединения — в состояние, без падения."""
    try:
        st.session_state["agents"] = api_client.api_fetch_agents()
        st.session_state["backend_ok"] = True
        st.session_state["backend_error"] = None
    except api_client.BackendError as exc:
        st.session_state["agents"] = []
        st.session_state["backend_ok"] = False
        st.session_state["backend_error"] = str(exc)


def active_agent():
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
