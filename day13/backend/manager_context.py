"""Миксин сжатия, стратегий, веток и фактов (дни 9–11).

Часть ``AgentManager`` (``backend/agent_manager.py``): состояние сжатия,
принудительная суммаризация, сравнение режимов, смена стратегии, дерево веток и
факты диалога.
"""
from typing import List, Optional

from .agent import Agent
from .database import AgentRecord
from .models import AgentConfig
from .strategies import AVAILABLE_STRATEGIES


class ContextOpsMixin:
    """Состояние сжатия, стратегии управления контекстом, ветки и факты."""

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
