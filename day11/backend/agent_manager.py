"""AgentManager дня 11 — синглтон, пул агентов с тремя слоями памяти.

Развивает менеджер дня 10: агенты по-прежнему создаются/восстанавливаются
вместе с историей и конспектами, но история теперь живёт в краткосрочном слое,
а к нему добавляются рабочая и долговременная память.

- ``create_agent`` пишет конфигурацию (включая настройки сжатия и текущие
  ``current_session_id``/``current_task_id``) в таблицу ``agents`` — при
  рестарте бэкенда агент восстанавливается вместе с диалогом своей сессии;
- ``patch_agent`` меняет конфигурацию на живом агенте (PATCH /agents/{id});
- ``get_summary`` / ``force_summarize`` / ``compare_modes`` — состояние сжатия,
  принудительное сжатие и сравнение режимов;
- ``get_usage_rows`` / ``get_usage_summary`` — строки и SQL-агрегаты таблицы
  ``token_usage`` (включая расход по слоям памяти);
- ``new_session`` / ``set_task`` / ``add_working`` / ``add_long_term`` и
  ``get_*`` — обёртки над слоями памяти для API (``Agent.memory``).

Фабрика сессий передаётся через конструктор (``session_factory``) — в
офлайн-проверках это фабрика на временный файл/временную БД.
"""
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import case, func

from . import config, database
from .agent import Agent
from .database import (
    AgentRecord, Checkpoint, Fact, LongTermMemory, ShortTermMessage, Summary,
    TokenUsage, WorkingMemory,
)
from .memory import AVAILABLE_CATEGORIES, new_session_id
from .models import AgentConfig, AgentPatch
from .strategies import AVAILABLE_STRATEGIES


class AgentNotFoundError(Exception):
    """Запрошенный agent_id отсутствует в менеджере (API отвечает 404)."""


class AgentManager:
    """Пул агентов: создание, поиск, список, удаление, генерация, сжатие."""

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
                created_at=now,
            ))
            session.commit()
        agent = Agent(cfg, agent_id=agent_id, created_at=now,
                      session_factory=self._session_factory,
                      session_id=session_id, task_id=task_id)
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

    # --- сжатие истории (день 9) ---
    def get_summary(self, agent_id: str) -> dict:
        """Состояние сжатия агента (конспект, watermark, экономика)."""
        return self.require_agent(agent_id).summary_state()

    def force_summarize(self, agent_id: str, force: bool = False) -> dict:
        """Запускает сжатие и возвращает его результат.

        Если сжимать нечего (порог не набран, а ``force`` не задан) — это не
        ошибка сервера: отчёт содержит ``created: False`` и текст причины.
        """
        agent = self.require_agent(agent_id)
        report = agent.compress_now(force=force)
        report["summary"] = agent.summary_state()
        return report

    def compare_modes(self, agent_id: str, prompt: str,
                      call_api: bool = False) -> dict:
        """Сравнивает режимы «полная история» и «со сжатием» на одном промпте."""
        return self.require_agent(agent_id).compare_modes(prompt, call_api=call_api)

    # --- стратегии управления контекстом (день 11) ---
    def set_strategy(self, agent_id: str, strategy: str,
                     window_size: Optional[int] = None) -> Agent:
        """Меняет стратегию агента (и, опц., размер окна) на живом агенте.

        Смена стратегии не теряет диалог: меняются только ``strategy`` и
        ``window_size`` в конфигурации (БД + память). Валидация значения
        стратегии — на уровне Pydantic (``StrategySetRequest``).
        """
        agent = self.require_agent(agent_id)
        data = agent.config.model_dump()
        data["strategy"] = strategy
        if window_size is not None:
            data["window_size"] = window_size
        cfg = AgentConfig(**data)

        with self._session() as session:
            row = (
                session.query(AgentRecord)
                .filter(AgentRecord.agent_id == agent_id)
                .one()
            )
            row.strategy = cfg.strategy
            row.window_size = cfg.window_size
            session.commit()

        agent.apply_config(cfg)
        agent.refresh_context_state()
        return agent

    def get_available_strategies(self) -> List[str]:
        """Список доступных стратегий (значения Enum Strategy)."""
        return list(AVAILABLE_STRATEGIES)

    def get_strategy_state(self, agent_id: str) -> dict:
        """Текущая стратегия агента + список доступных."""
        agent = self.require_agent(agent_id)
        return {
            "agent_id": agent_id,
            "strategy": agent.strategy,
            "window_size": agent.window_size,
            "available": list(AVAILABLE_STRATEGIES),
        }

    # --- ветвление (стратегия branching) ---
    def create_branch(self, agent_id: str, checkpoint_id: Optional[int] = None) -> dict:
        """Создаёт ветку (чекпоинт) и делает её активной."""
        return self.require_agent(agent_id).create_branch(checkpoint_id)

    def switch_branch(self, agent_id: str, branch_id: int) -> dict:
        """Переключает активную ветку агента."""
        return self.require_agent(agent_id).switch_branch(branch_id)

    def list_branches(self, agent_id: str) -> dict:
        """Дерево веток агента (чекпоинты с parent_id и флагом is_active)."""
        agent = self.require_agent(agent_id)
        return {
            "agent_id": agent_id,
            "active_branch_id": agent.active_branch_id,
            "branches": agent.list_branches(),
        }

    # --- факты (стратегия sticky_facts) ---
    def get_facts(self, agent_id: str) -> dict:
        """Текущие факты агента (ключ-значение, для панели фактов в UI)."""
        return {
            "agent_id": agent_id,
            "facts": self.require_agent(agent_id).list_facts(),
        }

    # --- метрики токенов ---
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
                "mode": row.mode,
                "full_context_tokens": row.full_context_tokens,
                "sent_context_tokens": row.sent_context_tokens,
                "saved_tokens": row.saved_tokens,
                "summary_tokens": row.summary_tokens,
                "summarized_messages": row.summarized_messages,
                "summary_used": row.summary_used,
                "short_term_tokens": row.short_term_tokens,
                "working_tokens": row.working_tokens,
                "long_term_tokens": row.long_term_tokens,
            }
            for row in rows
        ]

    def get_usage_summary(self, agent_id: str) -> dict:
        """Сводка токенов агента: SQL-агрегаты + занятость контекста + экономия."""
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
                    func.coalesce(func.sum(TokenUsage.full_context_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.sent_context_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.saved_tokens), 0),
                    func.coalesce(
                        func.sum(
                            case((TokenUsage.summary_used.is_(True), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(TokenUsage.short_term_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.working_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.long_term_tokens), 0),
                )
                .filter(TokenUsage.agent_id == agent_id)
                .one()
            )
        summaries = agent.compressor.economics()
        limit = agent.context_limit_tokens
        current = agent._context_tokens_for(agent.short_term_messages)
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
            "total_full_context_tokens": int(stats[6]),
            "total_sent_context_tokens": int(stats[7]),
            "total_saved_tokens": int(stats[8]),
            "total_summary_cost": summaries["summary_cost"],
            # Честная экономия: сэкономленные токены запросов минус собственные
            # токены вызовов суммаризации (та же метрика, что в /summary).
            "total_net_saved_tokens": summaries["net_saved_tokens"],
            "compressed_requests": int(stats[9]),
            # Расход по слоям памяти (день 11) — суммы новых колонок token_usage.
            "total_short_term_tokens": int(stats[10]),
            "total_working_tokens": int(stats[11]),
            "total_long_term_tokens": int(stats[12]),
        }

    # --- слои памяти (день 11) ---
    def new_session(self, agent_id: str) -> dict:
        """Начинает новую сессию агента (краткосрочный слой старой очищается)."""
        return self.require_agent(agent_id).new_session()

    def set_task(self, agent_id: str, task_id: str) -> dict:
        """Переключает активную задачу агента (рабочая память фильтруется)."""
        return self.require_agent(agent_id).set_task(task_id)

    def get_memory_state(self, agent_id: str) -> dict:
        """Сводка трёх слоёв: сессия, задача, счётчики и токены по слоям."""
        return self.require_agent(agent_id).memory_state()

    def add_short_term(self, agent_id: str, role: str, content: str) -> dict:
        """Добавляет реплику в краткосрочный слой текущей сессии."""
        return self.require_agent(agent_id).add_short_term(role, content)

    def get_short_term(self, agent_id: str, session_id: Optional[str] = None,
                       limit: Optional[int] = None) -> dict:
        """Реплики краткосрочного слоя сессии (по умолчанию — текущей)."""
        agent = self.require_agent(agent_id)
        target = session_id or agent.session_id
        return {
            "agent_id": agent_id,
            "session_id": target,
            "messages": agent.short_term_rows(target, limit=limit),
        }

    def clear_short_term(self, agent_id: str,
                         session_id: Optional[str] = None) -> dict:
        """Очищает краткосрочный слой сессии; возвращает число удалённых реплик."""
        agent = self.require_agent(agent_id)
        target = session_id or agent.session_id
        return {
            "agent_id": agent_id,
            "session_id": target,
            "deleted": agent.clear_short_term(target),
        }

    def add_working(self, agent_id: str, key: str, value: str,
                    task_id: Optional[str] = None) -> dict:
        """Upsert записи рабочей памяти (по умолчанию — активной задачи)."""
        return self.require_agent(agent_id).add_working(key, value, task_id=task_id)

    def get_working(self, agent_id: str, task_id: Optional[str] = None) -> dict:
        """Записи рабочей памяти задачи + список задач агента (для UI)."""
        agent = self.require_agent(agent_id)
        target = task_id or agent.task_id
        return {
            "agent_id": agent_id,
            "task_id": target,
            "entries": agent.working_rows(target),
            "tasks": agent.memory.list_tasks(agent_id),
        }

    def add_long_term(self, agent_id: str, category: str, key: str, value: str,
                      confidence: float = 1.0) -> dict:
        """Upsert записи долговременной памяти."""
        return self.require_agent(agent_id).add_long_term(
            category, key, value, confidence=confidence
        )

    def get_long_term(self, agent_id: str, category: Optional[str] = None) -> dict:
        """Записи долговременной памяти + список категорий (для UI)."""
        agent = self.require_agent(agent_id)
        return {
            "agent_id": agent_id,
            "category": category,
            "entries": agent.long_term_rows(category),
            "categories": list(AVAILABLE_CATEGORIES),
        }

    def delete_long_term(self, agent_id: str, entry_id: int) -> bool:
        """Удаляет запись долговременной памяти (False — записи не было)."""
        return self.require_agent(agent_id).delete_long_term(entry_id)


# Единственный инстанс менеджера процесса (синглтон, см. описание модуля).
_manager = AgentManager()


def get_manager() -> AgentManager:
    """Возвращает единственный инстанс AgentManager (синглтон)."""
    return _manager
