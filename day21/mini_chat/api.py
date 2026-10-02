"""HTTP-часть мини-чата дня 25: пять запросов к разделу ``/mini-chat``.

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь только вызовы мини-чата: сессия, реплика с ответом, память задачи, история
диалога и закрытие сессии. Правила поиска по корпусу, сборки промпта и обновления
памяти живут в ``MiniChatService`` бэкенда — интерфейс их не повторяет.

Границы поля ``top_k`` берутся из домена бэкенда (``backend.domain.rag_mode``), а не
пишутся числами: схема ``MiniChatMessageIn`` проверяет те же границы, и разойтись
им нельзя.
"""
from backend.domain.rag_mode import RAG_DEFAULT_TOP_K, RAG_MAX_TOP_K
from frontend.api_client import BackendError, request_json

#: Границы поля ``top_k`` в схеме ``MiniChatMessageIn`` (``ge=1``, ``le=RAG_MAX_TOP_K``).
TOP_K_MIN = 1
TOP_K_MAX = RAG_MAX_TOP_K
TOP_K_DEFAULT = RAG_DEFAULT_TOP_K

__all__ = ["BackendError", "TOP_K_DEFAULT", "TOP_K_MAX", "TOP_K_MIN", "close_session",
           "fetch_history", "fetch_memory", "send_message", "start_session"]


def start_session(user_id=None) -> dict:
    """POST /mini-chat/sessions -> сессия: ``session_id``, ``task_id``, пользователь.

    201 — сессия создана; служебная строка агента ``mini-chat`` и задача рабочей
    памяти ``mc-<session_id>`` появляются на бэкенде, поэтому перезапуск бэкенда
    память задачи не теряет.
    """
    return request_json("POST", "/mini-chat/sessions", json={"user_id": user_id})


def send_message(session_id, message, top_k=None) -> dict:
    """POST /mini-chat/sessions/{sid}/messages -> ответ с источниками и памятью.

    Ответ содержит ``mode`` (``rag`` / ``dont_know`` / ``error``), ``answer``,
    ``sources``, ``quotes``, ``task_memory`` и ``memory_updated``. 404 — сессии нет,
    400 — пустая реплика, 409 — корпус не проиндексирован, 502 — сбой отбора.
    """
    payload = {"message": message,
               "top_k": TOP_K_DEFAULT if top_k is None else int(top_k)}
    return request_json("POST", f"/mini-chat/sessions/{session_id}/messages",
                        json=payload)


def fetch_memory(session_id) -> dict:
    """GET /mini-chat/sessions/{sid}/memory -> четыре ключа памяти задачи."""
    return request_json("GET", f"/mini-chat/sessions/{session_id}/memory")


def fetch_history(session_id, limit=None) -> dict:
    """GET /mini-chat/sessions/{sid}/history -> реплики сессии (при ``limit`` — хвост)."""
    params = {"limit": int(limit)} if limit else None
    return request_json("GET", f"/mini-chat/sessions/{session_id}/history",
                        params=params)


def close_session(session_id) -> dict:
    """DELETE /mini-chat/sessions/{sid} -> удалённые реплики; идемпотентно.

    Память задачи остаётся в рабочей памяти: удаления записей рабочей памяти в API
    дня 11 нет, а новая сессия получает новый ``task_id``.
    """
    return request_json("DELETE", f"/mini-chat/sessions/{session_id}")
