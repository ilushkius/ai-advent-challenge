"""Миксин статистики токенов: строки и SQL-агрегаты token_usage.

Часть ``AgentManager`` (``backend/agent_manager.py``). Единственное место в
менеджере с SQL-агрегатами (``sqlalchemy.func`` / ``sqlalchemy.case``).
"""
from typing import List

from sqlalchemy import case, func

from ..models.context import TokenUsage


class UsageOpsMixin:
    """Строки и агрегаты таблицы token_usage (сводка + данные для графика)."""

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
