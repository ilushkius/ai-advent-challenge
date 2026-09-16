"""ORM-таблицы контекста дня 13: ``summaries``, ``token_usage``, ``facts``, ``checkpoints``.

- ``Summary`` — конспекты (append-only, текущий = последняя запись): content,
  границы покрытых реплик (watermark), экономика сжатия и стоимость вызова;
- ``TokenUsage`` — метрики одного успешного хода: базовые токены дня 8, эффект
  сжатия дня 9 (mode/full/sent/saved) и расход по слоям памяти дня 11;
- ``Fact`` — факты диалога «ключ → значение» (стратегия sticky_facts), пара
  (agent_id, key) уникальна;
- ``Checkpoint`` — снимки истории для стратегии branching (``messages`` — JSON).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base


class Summary(Base):
    """Конспект части диалога (таблица summaries).

    Append-only: каждая успешная суммаризация добавляет новую строку, поэтому
    история сжатий видна в интерфейсе, а текущий конспект агента — последняя
    запись. Поля ``covered_from_message_id``/``covered_to_message_id`` образуют
    watermark: всё, что старше ``covered_to_message_id``, уже описано в
    конспекте и в запрос не уходит.
    """

    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    content = Column(Text, nullable=False)
    covered_from_message_id = Column(Integer, nullable=False)
    covered_to_message_id = Column(Integer, nullable=False)
    covered_messages = Column(Integer, nullable=False, default=0)
    source_tokens = Column(Integer, nullable=False, default=0)
    summary_tokens = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False)

    agent = relationship("AgentRecord", back_populates="summaries")




class TokenUsage(Base):
    """Метрики токенов одного успешного хода диалога (таблица token_usage).

    Базовые поля — из дня 8 (prompt/completion/total/history/response/cost).
    Поля дня 9 описывают эффект сжатия:
    - ``mode`` — "full" (сжатие выключено) или "compressed";
    - ``full_context_tokens`` — оценка запроса, если бы ушла вся история;
    - ``sent_context_tokens`` — оценка фактически отправленного запроса;
    - ``saved_tokens`` — full_context_tokens - sent_context_tokens;
    - ``summary_tokens`` / ``summarized_messages`` — конспект хода;
    - ``summary_used`` — был ли конспект в payload.

    День 11 добавляет фактический расход по слоям памяти: ``short_term_tokens``,
    ``working_tokens``, ``long_term_tokens`` (оценки tiktoken для блоков,
    ушедших в запрос).
    """

    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    history_tokens = Column(Integer, nullable=False, default=0)
    response_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0.0)

    mode = Column(String(16), nullable=False, default="full")
    full_context_tokens = Column(Integer, nullable=False, default=0)
    sent_context_tokens = Column(Integer, nullable=False, default=0)
    saved_tokens = Column(Integer, nullable=False, default=0)
    summary_tokens = Column(Integer, nullable=False, default=0)
    summarized_messages = Column(Integer, nullable=False, default=0)
    summary_used = Column(Boolean, nullable=False, default=False)

    # Расход по слоям памяти (день 11): токены блоков, ушедших в запрос.
    short_term_tokens = Column(Integer, nullable=False, default=0)
    working_tokens = Column(Integer, nullable=False, default=0)
    long_term_tokens = Column(Integer, nullable=False, default=0)




class Fact(Base):
    """Один факт диалога «ключ → значение» (таблица facts, стратегия sticky_facts).

    Пара (agent_id, key) уникальна: повторное извлечение того же ключа обновляет
    ``value`` и ``updated_at``, а не плодит дубли. Экстракция — эвристическая
    (см. backend/fact_extractor.py), факты отправляются в LLM блоком в
    системном сообщении вместе с последними репликами.
    """

    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_facts_agent_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)




class Checkpoint(Base):
    """Снимок истории диалога в точке ветвления (таблица checkpoints, branching).

    ``messages`` — JSON-список ``[{"role": ..., "content": ...}, ...]`` — полный
    снимок истории на момент создания. ``parent_id`` указывает на чекпоинт,
    от которого создана ветка (None — корень). Активная ветка хранится в памяти
    агента (``Agent.active_branch_id``) и обновляется после каждого успешного
    хода в режиме branching; переключение заменяет краткосрочную память агента
    снимком выбранной ветки.
    """

    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parent_id = Column(Integer, nullable=True)
    messages = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
