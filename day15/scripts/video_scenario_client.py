"""HTTP-клиент прогона кадров дня 15 и путь БД прогона.

Что это.
    Запросы к бэкенду прогона теми же вызовами, что делает фронтенд (день 15
    ходит в API через ``requests``), и путь ``video_scenario.db`` — база, на
    которой идут все режимы прогона. Общее место для режимов ``--all``,
    ``--auto`` и стенда ``--ui``.

Почему отдельный модуль, а не часть точки входа.
    Точка входа запускается как ``__main__``: её импорт по имени создал бы вторую
    копию модуля (см. ``video_scenario_checks``). Плюс клиент и путь БД — это
    граница «прогон ↔ бэкенд», и её читают все режимы, а не только CLI.
"""
from pathlib import Path
from typing import Any, Optional, Tuple

import requests

# Отдельная БД прогона: agents.db приложения не трогается ни одним режимом.
VIDEO_DB = Path(__file__).resolve().parents[1] / "video_scenario.db"

# Агент прогона. Стратегия скользящего окна: прогон гарантированно не зовёт
# сжатие конспекта, поэтому вызов модели в кадрах ровно один — реплика кадра 3
# и вопрос кадра 8 (оба обслуживает заглушка бэкенда).
AGENT_CONFIG = {"name": "Демо-агент", "strategy": "sliding_window",
                "summary_enabled": False}


class ApiClient:
    """HTTP-клиент прогона: те же запросы, что делает фронтенд."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def request(self, method: str, path: str,
                body: Optional[dict] = None) -> Tuple[int, Any]:
        """Запрос к бэкенду: ``(статус, разобранное тело)``."""
        response = requests.request(
            method, self.base_url + path, json=body, timeout=self.timeout
        )
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    def create_agent(self):
        """POST /agents — агент прогона."""
        return self.request("POST", "/agents", AGENT_CONFIG)

    def create_task(self, agent_id: str, task_id: str):
        """POST /agents/{id}/tasks — завести состояние задачи."""
        return self.request("POST", f"/agents/{agent_id}/tasks", {"task_id": task_id})

    def state(self, task_id: str):
        """GET /tasks/{id}/state — этап, шаг, допустимые переходы, промпт-блок."""
        return self.request("GET", f"/tasks/{task_id}/state")

    def history(self, task_id: str):
        """GET /tasks/{id}/history — журнал переходов и отклонённых попыток."""
        return self.request("GET", f"/tasks/{task_id}/history")

    def advance(self, task_id: str):
        """POST /tasks/{id}/advance — следующий шаг (или следующий этап)."""
        return self.request("POST", f"/tasks/{task_id}/advance")

    def transition(self, task_id: str, stage: str):
        """POST /tasks/{id}/transition — прямой переход в этап."""
        return self.request("POST", f"/tasks/{task_id}/transition", {"stage": stage})

    def set_flags(self, task_id: str, **flags):
        """PATCH /tasks/{id}/context — флаги согласования этапов."""
        return self.request("PATCH", f"/tasks/{task_id}/context", dict(flags))

    def generate(self, agent_id: str, prompt: str):
        """POST /agents/{id}/generate — ход агента (модель — заглушка бэкенда)."""
        return self.request("POST", f"/agents/{agent_id}/generate", {"prompt": prompt})

    def set_active_task(self, agent_id: str, task_id: str):
        """PUT /agents/{id}/memory/task — какую задачу показывает панель."""
        return self.request(
            "PUT", f"/agents/{agent_id}/memory/task", {"task_id": task_id}
        )
