"""ORM-таблицы слоёв памяти дня 15: ``working_memory`` и ``long_term_memory``.

- ``WorkingMemory`` — РАБОЧАЯ память задачи: пары ``key → value``, привязанные к
  ``task_id`` (цель, ограничения, решения); пара (agent_id, task_id, key)
  уникальна; переживает смену сессии;
- ``LongTermMemory`` — ДОЛГОВРЕМЕННАЯ память: профиль, предпочтения, решения и
  знания, живущие между сессиями и задачами; пара (agent_id, category, key)
  уникальна.
"""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base


class WorkingMemory(Base):
    """Запись рабочей памяти агента (таблица working_memory).

    Рабочая память — данные текущей задачи (``task_id``): цель, ограничения,
    промежуточные решения, планы. Живёт дольше одной реплики, но привязана к
    задаче и НЕ очищается при старте новой сессии. Пара
    (agent_id, task_id, key) уникальна: повторная запись обновляет value.
    """

    __tablename__ = "working_memory"
    __table_args__ = (
        UniqueConstraint("agent_id", "task_id", "key", name="uq_working_agent_task_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    task_id = Column(String(64), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="working_entries")




class LongTermMemory(Base):
    """Запись долговременной памяти агента (таблица long_term_memory).

    Долговременная память — профиль пользователя, устойчивые предпочтения,
    важные решения и знания. Живёт между сессиями и задачами: не очищается ни
    ``new_session()``, ни сменой задачи. Пара (agent_id, category, key) уникальна:
    повторная запись обновляет value/confidence/updated_at.
    """

    __tablename__ = "long_term_memory"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "category", "key", name="uq_long_term_agent_category_key"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category = Column(String(32), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="long_term_entries")
