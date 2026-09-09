"""AgentManager дня 8 — синглтон, пул агентов с контекстной памятью.

Наследует менеджер дня 6 и добавляет персистентность:

- ``create_agent`` пишет конфигурацию в таблицу ``agents`` (commit) — при
  рестарте бэкенда агент восстанавливается;
- ``remove_agent`` удаляет строку агента (сообщения и метрики токенов
  удаляются вместе с агентом);
- ``restore_from_db`` восстанавливает всех агентов из ``agents`` при старте
  приложения; каждый ``Agent`` в конструкторе загружает свой диалог
  (``load_history``) из таблицы ``messages``;
- ``get_agent_history`` / ``clear_agent_history`` — чтение и очистка диалога
  (очистка сбрасывает и записи ``token_usage``);
- ``get_usage_rows`` / ``get_usage_summary`` — строки и SQL-агрегаты таблицы
  ``token_usage`` для эндпоинтов ``/usage`` и ``/usage/graph``.

Фабрика сессий передаётся через конструктор (``session_factory``) — в
офлайн-проверках это фабрика на временный файл/временную БД.
"""
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func

from . import database
from .agent import Agent
from .database import AgentRecord, Message, TokenUsage
from .models import AgentConfig


class AgentNotFoundError(Exception):
    """Запрошенный agent_id отсутствует в менеджере (API отвечает 404)."""


class AgentManager:
    """Пул агентов: создание, поиск, список, удаление, генерация, история."""

    def __init__(self, session_factory=None) -> None:
        self._lock = threading.Lock()
        self._agents: dict = {}
        self._session_factory = session_factory or database.SessionLocal

    # --- низкоуровневый доступ к БД ---
    @contextmanager
    def _session(self):
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- создание / удаление ---
    def _unique_id(self) -> str:
        """Короткий уникальный id: отсутствует и в памяти, и в таблице agents."""
        while True:
            candidate = uuid.uuid4().hex[:8]
            with self._session() as session:
                in_db = (
                    session.query(AgentRecord)
                    .filter(AgentRecord.agent_id == candidate)
                    .first()
                ) is not None
            if candidate not in self._agents and not in_db:
                return candidate

    def create_agent(self, cfg: AgentConfig) -> str:
        """Создаёт агента: строка в agents (БД) + объект в памяти.

        История нового агента пустая (строк в messages ещё нет).
        """
        agent_id = self._unique_id()
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.add(AgentRecord(
                agent_id=agent_id,
                name=cfg.name,
                model=cfg.model,
                temperature=cfg.temperature,
                system_prompt=cfg.system_prompt,
                max_tokens=cfg.max_tokens,
                created_at=now,
            ))
            session.commit()
        agent = Agent(cfg, agent_id=agent_id, created_at=now,
                      session_factory=self._session_factory)
        with self._lock:
            self._agents[agent_id] = agent
        return agent_id

    def remove_agent(self, agent_id: str) -> bool:
        """Удаляет агента вместе с историей из БД и памяти."""
        with self._lock:
            existed = self._agents.pop(agent_id, None) is not None
        if existed:
            with self._session() as session:
                # Сообщения и метрики токенов удаляются первыми: даже без
                # FK-каскада не остаётся осиротевших строк (агент — источник
                # правды в agents).
                session.query(TokenUsage).filter(
                    TokenUsage.agent_id == agent_id
                ).delete()
                session.query(Message).filter(Message.agent_id == agent_id).delete()
                session.query(AgentRecord).filter(
                    AgentRecord.agent_id == agent_id
                ).delete()
                session.commit()
        return existed

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

    # --- старт приложения: восстановление из БД ---
    def restore_from_db(self) -> int:
        """Восстанавливает агентов из таблицы agents (историю грузит Agent).

        Возвращает число восстановленных агентов. Повторный вызов безопасен.
        """
        with self._lock:
            self._agents = {}
        with self._session() as session:
            rows = (
                session.query(AgentRecord)
                .order_by(AgentRecord.created_at.asc(), AgentRecord.agent_id.asc())
                .all()
            )
        for row in rows:
            cfg = AgentConfig(
                name=row.name,
                model=row.model,
                temperature=row.temperature,
                system_prompt=row.system_prompt,
                max_tokens=row.max_tokens,
            )
            agent = Agent(
                cfg, agent_id=row.agent_id, created_at=row.created_at,
                session_factory=self._session_factory,
            )
            with self._lock:
                self._agents[row.agent_id] = agent
        return len(rows)

    # --- действия над агентом ---
    def generate_response(self, agent_id: str, prompt: str) -> dict:
        """Отправляет промпт агенту; возвращает запись-результат (ok/error).

        Агент сам добавляет реплики в self.messages и сохраняет диалог в БД.
        """
        return self.require_agent(agent_id).generate(prompt)

    def get_agent_history(self, agent_id: str) -> List[dict]:
        """Сообщения диалога агента в хронологическом порядке (с метаданными)."""
        return self.require_agent(agent_id).history_rows()

    def clear_agent_history(self, agent_id: str) -> int:
        """Удаляет все сообщения агента; возвращает число удалённых."""
        return self.require_agent(agent_id).clear_history()

    # --- метрики токенов (день 8) ---
    def get_usage_rows(self, agent_id: str) -> List[dict]:
        """Записи token_usage агента по возрастанию времени (для графика)."""
        self.require_agent(agent_id)
        with self._session() as session:
            rows = (
                session.query(TokenUsage)
                .filter(TokenUsage.agent_id == agent_id)
                .order_by(TokenUsage.timestamp.asc(), TokenUsage.id.asc())
                .all()
            )
        return [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "timestamp": row.timestamp,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "total_tokens": row.total_tokens,
                "history_tokens": row.history_tokens,
                "response_tokens": row.response_tokens,
                "cost": row.cost,
            }
            for row in rows
        ]

    def get_usage_summary(self, agent_id: str) -> dict:
        """Сводка токенов агента: SQL-агрегаты + занятость контекста."""
        agent = self.require_agent(agent_id)
        with self._session() as session:
            stats = (
                session.query(
                    func.count(TokenUsage.id),
                    func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.cost), 0.0),
                    func.max(TokenUsage.timestamp),
                )
                .filter(TokenUsage.agent_id == agent_id)
                .one()
            )
        limit = agent.context_limit_tokens
        current = agent._context_tokens_for(agent.messages)
        return {
            "agent_id": agent_id,
            "model": agent.model,
            "total_requests": stats[0],
            "total_prompt_tokens": stats[1],
            "total_completion_tokens": stats[2],
            "total_tokens": stats[3],
            "total_cost": round(float(stats[4]), 6),
            "last_usage_at": stats[5],
            "context_limit_tokens": limit,
            "current_history_tokens": current,
            "remaining_tokens": max(0, limit - current),
        }


# Единственный инстанс менеджера процесса (синглтон, см. описание модуля).
_manager = AgentManager()


def get_manager() -> AgentManager:
    """Возвращает единственный инстанс AgentManager (синглтон)."""
    return _manager

