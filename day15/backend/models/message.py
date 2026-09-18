"""ORM-таблица краткосрочной памяти дня 15: ``short_term_messages``.

``ShortTermMessage`` — одна реплика текущего диалога (``session_id``). История
не удаляется при сжатии: конспект лишь заменяет старые реплики в ЗАПРОСЕ, но не
в хранилище. Слой очищается при старте новой сессии (``Agent.new_session``) или
по команде (``DELETE /agents/{id}/memory/short-term``).
"""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base


class ShortTermMessage(Base):
    """Одна реплика краткосрочной памяти агента (таблица short_term_messages).

    Краткосрочная память — текущий диалог в рамках одной сессии (``session_id``):
    последние N реплик уходят в запрос, остальные доступны в БД до конца сессии.
    Очищается при старте новой сессии (``Agent.new_session``) или по команде
    (``DELETE /agents/{id}/memory/short-term``).
    """

    __tablename__ = "short_term_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    session_id = Column(String(32), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="short_term_messages")
