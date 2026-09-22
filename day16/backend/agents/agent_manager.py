"""AgentManager дня 16 — синглтон, пул агентов с тремя слоями памяти и профилями.

Развивает менеджер дня 11: агенты по-прежнему создаются/восстанавливаются
вместе с историей и конспектами, история живёт в краткосрочном слое, а к нему
добавлены рабочая и долговременная память. День 12 добавляет персонализацию:
агент создаётся с ``user_id``, а менеджер ведёт CRUD профилей пользователей.

Класс собран из миксинов по доменам (файлы ``manager_*.py``), каждый метод
описан ровно в одном из них:

- ``manager_agents.py`` (``AgentPoolMixin``) — создание, поиск, список,
  удаление, восстановление из БД, patch и действия над агентом
  (``create_agent``, ``remove_agent``, ``restore_from_db``, ``patch_agent``,
  ``generate_response``, ``get_agent_history``, ``clear_agent_history``), а
  также ``AgentNotFoundError``;
- ``manager_context.py`` (``ContextOpsMixin``) — состояние сжатия, стратегии
  управления контекстом, ветки и факты;
- ``manager_usage.py`` (``UsageOpsMixin``) — строки и SQL-агрегаты token_usage;
- ``manager_memory.py`` (``MemoryOpsMixin``) — сессия, активная задача и CRUD
  трёх слоёв памяти;
- ``manager_profiles.py`` (``ProfileOpsMixin``) — CRUD профилей пользователей и
  раздача профиля живым агентам;
- ``manager_tasks.py`` (``TaskOpsMixin``) — состояние задачи дня 13: создание,
  переходы, пауза, откат и список активных задач;
- ``manager_invariants.py`` (``InvariantOpsMixin``) — инварианты дня 14: CRUD
  правил проекта и проверка текста через ``InvariantChecker``;
- здесь остаются общие части: ``__init__`` с пулом/блокировкой/фабрикой сессий,
  низкоуровневый ``_session`` и синглтон ``get_manager()``.

Фабрика сессий передаётся через конструктор (``session_factory``) — в
офлайн-проверках это фабрика на временный файл/временную БД. Второй необязательный
параметр — ``client_factory``: фабрика клиента DeepSeek для проверки инвариантов
вне агента (``POST /invariants/check``); в приложении она не задана, и клиент
создаёт сервис проверки.
"""
import threading
from contextlib import contextmanager

from ..storage import database
from .manager_agents import AgentNotFoundError, AgentPoolMixin
from .manager_context import ContextOpsMixin
from .manager_invariants import InvariantOpsMixin
from .manager_memory import MemoryOpsMixin
from .manager_profiles import ProfileOpsMixin
from .manager_tasks import TaskOpsMixin
from .manager_usage import UsageOpsMixin


class AgentManager(AgentPoolMixin, ContextOpsMixin, UsageOpsMixin,
                   MemoryOpsMixin, ProfileOpsMixin, TaskOpsMixin,
                   InvariantOpsMixin):
    """Пул агентов с тремя слоями памяти, стратегиями и профилями пользователей.

    Здесь только общее состояние инстанса: пул живых агентов (``self._agents``),
    блокировка (``self._lock``) и фабрика сессий (``self._session_factory``).
    Остальные методы приходят из миксинов (см. описание модуля); порядок
    наследования задаёт только состав класса — имена методов уникальны.
    """

    def __init__(self, session_factory=None, client_factory=None) -> None:
        self._lock = threading.Lock()
        self._agents: dict = {}
        self._session_factory = session_factory or database.SessionLocal
        # Фабрика клиента DeepSeek для проверки инвариантов вне агента
        # (POST /invariants/check): в офлайн-проверках подменяется фейком,
        # в приложении остаётся None — тогда клиент создаёт сервис проверки.
        self._client_factory = client_factory

    # --- низкоуровневый доступ к БД ---
    @contextmanager
    def _session(self):
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()


# Единственный инстанс менеджера процесса (синглтон, см. описание модуля).
_manager = AgentManager()


def get_manager() -> AgentManager:
    """Возвращает единственный инстанс AgentManager (синглтон)."""
    return _manager
