"""ORM-таблица агента дня 15: ``agents`` (``AgentRecord``).

Строка таблицы ``agents`` — сохраняемая конфигурация агента: модель и её
параметры, настройки сжатия истории (день 9), стратегия сборки контекста
(день 11), активные ``current_session_id`` / ``current_task_id`` и ``user_id``
профиля пользователя (день 12). Связи (``relationship``) с остальными таблицами
дня объявлены здесь же: строковые имена разрешаются по registry SQLAlchemy, а
все модули ``backend/models/`` импортируются из ``backend.storage.database``.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base

from ..core import config


class AgentRecord(Base):
    """Строка таблицы agents — сохраняемая конфигурация агента."""

    __tablename__ = "agents"

    agent_id = Column(String, primary_key=True)
    name = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    temperature = Column(Float, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    max_tokens = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    # Настройки сжатия истории (день 9). Дефолты — константы config, чтобы
    # существующие строки БД читались осмысленно и без миграции.
    summary_enabled = Column(
        Boolean, nullable=False, default=config.DEFAULT_SUMMARY_ENABLED
    )
    keep_last_messages = Column(
        Integer, nullable=False, default=config.DEFAULT_KEEP_LAST_MESSAGES
    )
    summarize_every = Column(
        Integer, nullable=False, default=config.DEFAULT_SUMMARIZE_EVERY
    )

    # Стратегия управления контекстом (день 11). Дефолты — константы config,
    # чтобы существующие строки БД читались осмысленно и без миграции.
    strategy = Column(String(32), nullable=False, default=config.DEFAULT_STRATEGY)
    window_size = Column(Integer, nullable=False, default=config.DEFAULT_WINDOW_SIZE)

    # Слои памяти (день 11): строка agents — источник правды о том, какая сессия
    # краткосрочной памяти и какая задача рабочей памяти сейчас активны.
    current_session_id = Column(String(32), nullable=False)
    current_task_id = Column(String(64), nullable=False, default=config.DEFAULT_TASK_ID)

    # Персонализация (день 12): пользователь, чей профиль подключается к
    # системному промпту каждого запроса агента. Не FK: профиль — отдельная
    # сущность, его удаление не должно уносить агентов (они просто теряют
    # персонализацию и отвечают как обычно).
    user_id = Column(
        String(config.USER_ID_MAX), nullable=False, index=True,
        default=config.DEFAULT_USER_ID,
    )

    short_term_messages = relationship(
        "ShortTermMessage",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    working_entries = relationship(
        "WorkingMemory",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    long_term_entries = relationship(
        "LongTermMemory",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    summaries = relationship(
        "Summary",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    task_states = relationship(
        "TaskState",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
