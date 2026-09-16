"""HTTP-клиент фронтенда дня 13: запросы к бэкенду FastAPI.

Все обращения интерфейса к бэкенду идут через ``_request``: он собирает URL из
``BACKEND_URL`` (переопределяется переменной окружения ``DAY13_BACKEND_URL``),
превращает HTTP-ошибку в ``BackendError`` с человекочитаемым текстом и
возвращает разобранный JSON. Модуль не зависит от Streamlit и pandas — это
чистый транспорт.
"""
import os

import requests


# Куда стучится фронтенд (можно переопределить переменной окружения).
BACKEND_URL = os.environ.get("DAY13_BACKEND_URL", "http://127.0.0.1:8000")
TIMEOUT = 90.0  # сек; compare с вызовами API делает два запроса к DeepSeek


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
            f"Бэкенд недоступен ({BACKEND_URL}). Запустите его из папки day13/: "
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


# ---------- HTTP-клиент: состояние задачи (день 13) ----------
def api_create_task(agent_id, task_id, initial_stage="planning"):
    """POST /agents/{agent_id}/tasks -> созданное состояние задачи (409 — есть)."""
    return _request("POST", f"/agents/{agent_id}/tasks",
                    json={"task_id": task_id, "initial_stage": initial_stage})


def api_agent_tasks(agent_id):
    """GET /agents/{agent_id}/tasks -> незавершённые задачи агента."""
    return _request("GET", f"/agents/{agent_id}/tasks")


def api_task_state(task_id):
    """GET /tasks/{task_id}/state -> этап, шаг, ожидаемое действие."""
    return _request("GET", f"/tasks/{task_id}/state")


def api_task_history(task_id):
    """GET /tasks/{task_id}/history -> журнал переходов задачи."""
    return _request("GET", f"/tasks/{task_id}/history")


def api_pause_task(task_id):
    """POST /tasks/{task_id}/pause -> задача на паузе (шаг сохранён)."""
    return _request("POST", f"/tasks/{task_id}/pause")


def api_resume_task(task_id):
    """POST /tasks/{task_id}/resume -> продолжение с того же этапа и шага."""
    return _request("POST", f"/tasks/{task_id}/resume")


def api_advance_task(task_id):
    """POST /tasks/{task_id}/advance -> следующий шаг (или следующий этап)."""
    return _request("POST", f"/tasks/{task_id}/advance")


def api_rollback_task(task_id, to_stage):
    """POST /tasks/{task_id}/rollback -> откат на предыдущий этап."""
    return _request("POST", f"/tasks/{task_id}/rollback",
                    json={"to_stage": to_stage})


def api_transition_task(task_id, stage, step=None, expected_action=None,
                        reason=None):
    """POST /tasks/{task_id}/transition -> прямой переход в этап/шаг.

    В тело уходят только заполненные поля: пустые значения бэкенд разрешает
    сам (первый шаг этапа, ожидаемое действие этапа, «переход по запросу»).
    """
    payload = {"stage": stage}
    if step is not None:
        payload["step"] = step
    if expected_action is not None:
        payload["expected_action"] = expected_action
    if reason is not None:
        payload["reason"] = reason
    return _request("POST", f"/tasks/{task_id}/transition", json=payload)
