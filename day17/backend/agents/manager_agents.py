"""Миксин пула агентов: создание, поиск, список, удаление, восстановление.

Часть ``AgentManager`` (``backend/agent_manager.py``): методы работают с теми же
полями инстанса (``self._agents``, ``self._lock``, ``self._session_factory``),
которые заводит ``AgentManager.__init__``. Здесь же объявлен
``AgentNotFoundError`` — его кидает ``require_agent``.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from ..core import config
from .agent import Agent
from ..models.agent import AgentRecord
from ..models.context import Checkpoint, Fact, Summary, TokenUsage
from ..models.memory import LongTermMemory, WorkingMemory
from ..models.message import ShortTermMessage
from ..models.task_state import TaskState, TaskTransition
from ..schemas import AgentConfig, AgentPatch
from .memory import new_session_id


class AgentNotFoundError(Exception):
    """Запрошенный agent_id отсутствует в менеджере (API отвечает 404)."""


class AgentPoolMixin:
    """Пул агентов: создание, поиск, список, удаление, восстановление."""

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

        История и конспекты нового агента пусты.
        """
        agent_id = self._unique_id()
        now = datetime.now(timezone.utc)
        session_id = new_session_id()
        task_id = config.DEFAULT_TASK_ID
        with self._session() as session:
            session.add(AgentRecord(
                agent_id=agent_id,
                name=cfg.name,
                model=cfg.model,
                temperature=cfg.temperature,
                system_prompt=cfg.system_prompt,
                max_tokens=cfg.max_tokens,
                summary_enabled=cfg.summary_enabled,
                keep_last_messages=cfg.keep_last_messages,
                summarize_every=cfg.summarize_every,
                strategy=cfg.strategy,
                window_size=cfg.window_size,
                current_session_id=session_id,
                current_task_id=task_id,
                user_id=cfg.user_id,
                created_at=now,
            ))
            session.commit()
        agent = Agent(cfg, agent_id=agent_id, created_at=now,
                      session_factory=self._session_factory,
                      session_id=session_id, task_id=task_id,
                      mcp_registry=self._mcp_registry)
        agent.refresh_context_state()
        with self._lock:
            self._agents[agent_id] = agent
        return agent_id

    def remove_agent(self, agent_id: str) -> bool:
        """Удаляет агента вместе с историей, конспектами и метриками."""
        with self._lock:
            existed = self._agents.pop(agent_id, None) is not None
        if existed:
            with self._session() as session:
                # Дочерние строки удаляются первыми: даже без FK-каскада не
                # остаётся осиротевших записей (агент — источник правды).
                # Журнал переходов ссылается на задачу по task_id, поэтому
                # удаляется до состояния задачи.
                task_ids = [
                    row.task_id
                    for row in session.query(TaskState.task_id)
                    .filter(TaskState.agent_id == agent_id)
                    .all()
                ]
                if task_ids:
                    session.query(TaskTransition).filter(
                        TaskTransition.task_id.in_(task_ids)
                    ).delete(synchronize_session=False)
                session.query(TaskState).filter(
                    TaskState.agent_id == agent_id
                ).delete(synchronize_session=False)
                session.query(TokenUsage).filter(
                    TokenUsage.agent_id == agent_id
                ).delete()
                session.query(Summary).filter(
                    Summary.agent_id == agent_id
                ).delete()
                session.query(Fact).filter(
                    Fact.agent_id == agent_id
                ).delete()
                session.query(Checkpoint).filter(
                    Checkpoint.agent_id == agent_id
                ).delete()
                session.query(LongTermMemory).filter(
                    LongTermMemory.agent_id == agent_id
                ).delete()
                session.query(WorkingMemory).filter(
                    WorkingMemory.agent_id == agent_id
                ).delete()
                session.query(ShortTermMessage).filter(
                    ShortTermMessage.agent_id == agent_id
                ).delete()
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

        Конспекты и watermark читаются из таблицы summaries лениво (при
        сборке payload), состояние FSM выводится из БД. Повторный вызов
        безопасен: список агентов пересобирается с нуля.
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
                summary_enabled=row.summary_enabled,
                keep_last_messages=row.keep_last_messages,
                summarize_every=row.summarize_every,
                strategy=row.strategy,
                window_size=row.window_size,
                # Профиль (день 12): у строк из старой БД колонки может не быть
                # значения — тогда пользователь по умолчанию.
                user_id=row.user_id or config.DEFAULT_USER_ID,
            )
            # Пустой current_session_id возможен только у строки из чужого файла
            # БД: генерируем и записываем, чтобы краткосрочный слой был валиден.
            session_id = row.current_session_id or new_session_id()
            if session_id != row.current_session_id:
                with self._session() as session:
                    stored = (
                        session.query(AgentRecord)
                        .filter(AgentRecord.agent_id == row.agent_id)
                        .one()
                    )
                    stored.current_session_id = session_id
                    session.commit()
            agent = Agent(
                cfg, agent_id=row.agent_id, created_at=row.created_at,
                session_factory=self._session_factory,
                session_id=session_id,
                task_id=row.current_task_id or config.DEFAULT_TASK_ID,
                mcp_registry=self._mcp_registry,
            )
            agent.refresh_context_state()
            with self._lock:
                self._agents[row.agent_id] = agent
        return len(rows)

    def patch_agent(self, agent_id: str, patch: AgentPatch) -> Agent:
        """Частично обновляет конфигурацию агента (БД + память).

        Поля, не указанные в теле запроса (None), не меняются: так можно
        переключить сжатие, не передавая заново остальную конфигурацию.
        """
        agent = self.require_agent(agent_id)
        current = agent.config
        data = current.model_dump()
        for key, value in patch.model_dump(exclude_none=True).items():
            data[key] = value
        cfg = AgentConfig(**data)

        with self._session() as session:
            row = (
                session.query(AgentRecord)
                .filter(AgentRecord.agent_id == agent_id)
                .one()
            )
            row.name = cfg.name
            row.model = cfg.model
            row.temperature = cfg.temperature
            row.system_prompt = cfg.system_prompt
            row.max_tokens = cfg.max_tokens
            row.summary_enabled = cfg.summary_enabled
            row.keep_last_messages = cfg.keep_last_messages
            row.summarize_every = cfg.summarize_every
            row.strategy = cfg.strategy
            row.window_size = cfg.window_size
            row.user_id = cfg.user_id
            session.commit()

        agent.apply_config(cfg)
        agent.refresh_context_state()
        return agent

    # --- действия над агентом ---
    def generate_response(self, agent_id: str, prompt: str) -> dict:
        """Отправляет промпт агенту; возвращает запись-результат (ok/error)."""
        return self.require_agent(agent_id).generate(prompt)

    def get_agent_history(self, agent_id: str) -> List[dict]:
        """Сообщения диалога агента в хронологическом порядке (с метаданными)."""
        return self.require_agent(agent_id).history_rows()

    def clear_agent_history(self, agent_id: str) -> int:
        """Удаляет историю, конспекты и метрики агента; возвращает число реплик."""
        return self.require_agent(agent_id).clear_history()
