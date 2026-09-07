"""AgentManager дня 6 — синглтон, хранящий пул агентов DeepSeek.

Класс реализует «менеджер агентов» из задачи: один инстанс на процесс бэкенда
(синглтон через модульный объект + get_manager()), внутри — словарь агентов и
методы create/get/list/remove/generate_response. Мутации словаря защищены
`threading.Lock` — FastAPI обрабатывает запросы в пуле потоков.
"""
import threading
import uuid
from typing import List, Optional

from .agent import Agent
from .models import AgentConfig


class AgentNotFoundError(Exception):
    """Запрошенный agent_id отсутствует в менеджере (API отвечает 404)."""


class AgentManager:
    """Пул агентов: создание, поиск, список, удаление, генерация."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._agents: dict = {}

    # --- создание / удаление ---
    def _unique_id(self) -> str:
        """Короткий уникальный id (uuid4 hex[:8]); при коллизии — повтор."""
        while True:
            candidate = uuid.uuid4().hex[:8]
            if candidate not in self._agents:
                return candidate

    def create_agent(self, cfg: AgentConfig) -> str:
        """Создаёт агента по конфигурации и возвращает его agent_id."""
        agent_id = self._unique_id()
        agent = Agent(cfg, agent_id=agent_id)
        with self._lock:
            self._agents[agent_id] = agent
        return agent_id

    def remove_agent(self, agent_id: str) -> bool:
        """Удаляет агента вместе с его историей. True, если агент был удалён."""
        with self._lock:
            return self._agents.pop(agent_id, None) is not None

    # --- чтение ---
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Возвращает агента или None, если такого id нет."""
        return self._agents.get(agent_id)

    def require_agent(self, agent_id: str) -> Agent:
        """Возвращает агента или кидает AgentNotFoundError (для API-слоя)."""
        agent = self._agents.get(agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        return agent

    def list_agents(self) -> List[Agent]:
        """Снимок списка агентов (в порядке создания)."""
        with self._lock:
            return list(self._agents.values())

    # --- действия над агентом ---
    def generate_response(self, agent_id: str, prompt: str) -> dict:
        """Отправляет промпт агенту; возвращает запись-результат (ok/error).

        Каждая попытка автоматически попадает в историю агента (см. Agent).
        """
        return self.require_agent(agent_id).generate(prompt)


# Единственный инстанс менеджера процесса (синглтон, см. описание модуля).
_manager = AgentManager()


def get_manager() -> AgentManager:
    """Возвращает единственный инстанс AgentManager (синглтон)."""
    return _manager
