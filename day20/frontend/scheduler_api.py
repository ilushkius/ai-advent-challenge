"""HTTP-часть фронтенда дня 18 для раздела «🗓 Планировщик».

Транспорт общий — ``frontend/api_client.py`` (``request_json``, ``BackendError``);
здесь лежат только запросы планировщика: задачи и управление ими, каталог
инструментов, напоминания, накопленные записи, сводки, уведомления и статус.

Отдельный модуль, а не дополнение ``api_client``, по той же причине, что у
``mcp_api.py`` дня 17: ``api_client`` уже держит семь доменов и подошёл к лимиту
400 строк, а планировщик стал восьмым.

Разделы интерфейса (``frontend/scheduler_section.py``, ``notifications.py``)
ходят в бэкенд только через эти функции: планировщик живёт в процессе бэкенда,
поэтому перерисовка страницы Streamlit его не трогает.
"""
from .api_client import request_json


def api_scheduler_status():
    """GET /scheduler/status -> работает ли планировщик и сколько задач поставлено."""
    return request_json("GET", "/scheduler/status")


def api_scheduler_tools():
    """GET /scheduler/tools -> каталог трёх инструментов с аргументами."""
    return request_json("GET", "/scheduler/tools")


def api_scheduler_tasks(status=None):
    """GET /scheduler/tasks -> задачи планировщика и состояние самого планировщика."""
    params = {"status": status} if status else None
    return request_json("GET", "/scheduler/tasks", params=params)


def api_scheduler_create(payload):
    """POST /scheduler/tasks -> созданная задача, результат подготовки и подтверждение.

    400 — негодные аргументы, незнакомый инструмент или расписание; 422 —
    невалидное тело. Текст причины приходит через ``BackendError``.
    """
    return request_json("POST", "/scheduler/tasks", json=payload)


def api_scheduler_delete(task_id):
    """DELETE /scheduler/tasks/{task_id} -> задача удалена (404 — её нет)."""
    return request_json("DELETE", f"/scheduler/tasks/{int(task_id)}")


def api_scheduler_pause(task_id):
    """POST /scheduler/tasks/{task_id}/pause -> задача на паузе (409 — не активна)."""
    return request_json("POST", f"/scheduler/tasks/{int(task_id)}/pause", json={})


def api_scheduler_resume(task_id):
    """POST /scheduler/tasks/{task_id}/resume -> задача снова активна (409 — не на паузе)."""
    return request_json("POST", f"/scheduler/tasks/{int(task_id)}/resume", json={})


def api_scheduler_run(task_id):
    """POST /scheduler/tasks/{task_id}/run -> запуск вне расписания (запись в журнал)."""
    return request_json("POST", f"/scheduler/tasks/{int(task_id)}/run", json={})


def api_scheduler_history(task_id, limit=None):
    """GET /scheduler/tasks/{task_id}/history -> задача и её запуски."""
    params = {"limit": int(limit)} if limit else None
    return request_json("GET", f"/scheduler/tasks/{int(task_id)}/history", params=params)


def api_scheduler_reminders(status=None):
    """GET /scheduler/reminders -> напоминания (ближайшие — первыми)."""
    params = {"status": status} if status else None
    return request_json("GET", "/scheduler/reminders", params=params)


def api_scheduler_collected(name=None):
    """GET /scheduler/collected -> накопленные записи сбора и их общее число."""
    params = {"name": name} if name else None
    return request_json("GET", "/scheduler/collected", params=params)


def api_scheduler_summaries(name=None):
    """GET /scheduler/summaries -> регулярные сводки (свежие — первыми)."""
    params = {"name": name} if name else None
    return request_json("GET", "/scheduler/summaries", params=params)


def api_scheduler_notifications(unread_only=False):
    """GET /scheduler/notifications -> очередь уведомлений и число непрочитанных."""
    return request_json("GET", "/scheduler/notifications",
                        params={"unread_only": bool(unread_only)})


def api_scheduler_mark_read(notification_id):
    """POST /scheduler/notifications/{id}/read -> уведомление прочитано (404 — нет такого)."""
    return request_json("POST",
                        f"/scheduler/notifications/{int(notification_id)}/read", json={})
