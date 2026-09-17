"""Слой конфигурации и зависимостей дня 14.

- ``config`` — настройки и дефолты дня (URL/модели DeepSeek, лимиты, цены,
  параметры сжатия/стратегий/памяти/профиля, путь к SQLite и к ``.env``);
- ``dependencies`` — зависимости роутов: ``get_manager`` (доступ к
  ``AgentManager`` через ``backend.api.main``) и помощники ``agent_or_404`` /
  ``task_or_404`` / ``invariant_or_404``.

Слой не импортирует другие слои дня, кроме ``agents`` (тип ``AgentManager`` в
аннотации) и лениво — ``api`` (внутри ``get_manager``), поэтому циклов нет.
"""

from . import config
from .dependencies import agent_or_404, get_manager, invariant_or_404, task_or_404

__all__ = [
    "config",
    "get_manager",
    "agent_or_404",
    "invariant_or_404",
    "task_or_404",
]
