"""HTTP-часть MCP-сервера дня 18: постановка фоновых задач через API дня.

Инструменты планировщика ничего не сохраняют сами: их тело — один вызов
``POST /scheduler/tasks`` бэкенда дня (``backend/api/scheduler.py``). Причина
простая и важная: единственный писатель в SQLite — процесс бэкенда, а фон живёт
там же (APScheduler). Если бы MCP-сервер (отдельный процесс по stdio) писал в БД
сам, появились бы два писателя и задачи, которых не видит планировщик. Так у
ручного создания задачи и у вызова инструмента один код-путь.

Ошибка бэкенда — это ``BackendAPIError`` с текстом для человека: сервер переводит
её в ``ToolError``, и модель получает причину («интервал должен быть от 1 до
86400 секунд»), а не «Error executing tool collect_data».

Клиент настраивается через ``configure()`` (аргумент ``--backend-url``) и живёт в
модуле один на процесс: ``get_client()`` создаёт его лениво, поэтому инструменты
не заводят соединение на каждый вызов.
"""

from __future__ import annotations

from typing import Any

import httpx

from mcp_server.config import BACKEND_TIMEOUT, BACKEND_URL

__all__ = ["BackendAPIError", "ScheduleBackendClient", "configure", "get_client"]


class BackendAPIError(RuntimeError):
    """Ошибка бэкенда дня с текстом, пригодным для показа модели и человеку."""


class ScheduleBackendClient:
    """Постановка задач планировщика: один вызов ``POST /scheduler/tasks``."""

    def __init__(self, base_url: str = BACKEND_URL,
                 timeout: float = BACKEND_TIMEOUT) -> None:
        self._base_url = (base_url or BACKEND_URL).rstrip("/")
        self._timeout = float(timeout)

    @property
    def base_url(self) -> str:
        """Адрес бэкенда дня (нужен скриптам и отчёту)."""
        return self._base_url

    def schedule_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Ставит задачу инструмента и возвращает ответ бэкенда.

        Успех — разобранный JSON (``task``, ``result``, ``message``). Ошибка
        запроса (400/404/409) приходит текстом причины из ``detail``; недоступный
        бэкенд — понятным текстом с адресом, по которому его ждали (иначе модель
        видела бы трассировку ``httpx`` и не поняла, что чинить).
        """
        url = f"{self._base_url}/scheduler/tasks"
        body = {"tool": tool, "arguments": dict(arguments or {})}
        try:
            response = httpx.post(url, json=body, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise BackendAPIError(
                f"Бэкенд дня недоступен по адресу {self._base_url}: {exc}. "
                "Запустите его из папки day18/: uvicorn backend.api.main:app --port 8000"
            ) from exc
        if response.status_code >= 400:
            raise BackendAPIError(_error_text(response))
        try:
            return response.json()
        except ValueError as exc:
            raise BackendAPIError(
                f"Бэкенд дня вернул не JSON на {url}"
            ) from exc


def _error_text(response: httpx.Response) -> str:
    """Текст отказа бэкенда: ``detail`` из тела или код ответа."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message")
        if isinstance(detail, str) and detail:
            return detail
    return f"Бэкенд дня ответил ошибкой HTTP {response.status_code}"


_client: ScheduleBackendClient | None = None


def configure(base_url: str | None = None,
              timeout: float | None = None) -> ScheduleBackendClient:
    """Настраивает клиент процесса (аргумент командной строки ``--backend-url``)."""
    global _client
    _client = ScheduleBackendClient(
        base_url or BACKEND_URL,
        BACKEND_TIMEOUT if timeout is None else timeout,
    )
    return _client


def get_client() -> ScheduleBackendClient:
    """Клиент процесса; создаётся при первом обращении с настройками по умолчанию."""
    global _client
    if _client is None:
        _client = ScheduleBackendClient()
    return _client
