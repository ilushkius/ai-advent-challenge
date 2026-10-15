"""HTTP-часть раздела «🗂 Ассистент файлов» (день 34).

Транспорт общий — ``frontend/api_client.py``; здесь три запроса дня 34: прогон цели,
история запусков и diff одного запуска.

Предел ожидания — ``LONG_TIMEOUT`` у прогона (и у истории с diff-ом тоже): прогон
делает 2–4 вызова модели и десятки вызовов MCP-сервера, а первый зов поднимает
stdio-процесс сервера, поэтому общего предела в 90 секунд ему мало.
"""
from .api_client import LONG_TIMEOUT, request_json

#: Сколько запусков запрашивает история раздела, если предел не задан явно.
HISTORY_LIMIT = 20


def api_file_assistant_execute(goal: str, provider: str = "",
                               dry_run: bool = False) -> dict:
    """POST /file-assistant/execute -> план, журнал шагов, файлы, diff и сводка.

    Пустой ``provider`` в тело не попадает: «поле не задано» и «поле пустое» для
    службы одно и то же, но лишние поля в запросе мешают читать журнал вызовов.
    """
    payload = {"goal": goal, "dry_run": bool(dry_run)}
    if provider:
        payload["provider"] = provider
    return request_json("POST", "/file-assistant/execute", timeout=LONG_TIMEOUT,
                        json=payload)


def api_file_assistant_history(limit: int = HISTORY_LIMIT) -> dict:
    """GET /file-assistant/history -> запуски от свежих к старым (всегда 200)."""
    return request_json("GET", "/file-assistant/history", params={"limit": int(limit)})


def api_file_assistant_diff(run_id: int) -> dict:
    """GET /file-assistant/diff/{run_id} -> diff и файлы одного запуска (404 — нет)."""
    return request_json("GET", f"/file-assistant/diff/{int(run_id)}")
