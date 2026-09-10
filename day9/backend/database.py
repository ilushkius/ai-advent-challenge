"""Слой SQLAlchemy/SQLite дня 9: движок, сессии и ORM-модели.

Хранилище агентов со сжатием истории. Четыре таблицы (связь один-ко-многим
от агента):

- ``agents`` (AgentRecord) — конфигурация агента, включая настройки сжатия
  (``summary_enabled``, ``keep_last_messages``, ``summarize_every``);
- ``messages`` (Message) — ПОЛНЫЕ реплики диалога: id (Integer, PK), agent_id
  (String, ForeignKey -> agents.agent_id, index), role, content (Text),
  timestamp. История не удаляется при сжатии — конспект лишь заменяет старые
  реплики в ЗАПРОСЕ, но не в хранилище;
- ``summaries`` (Summary) — конспекты (append-only, текущий = последняя запись):
  content (Text), covered_from_message_id / covered_to_message_id (границы
  покрытых реплик, watermark), covered_messages (сколько реплик покрыто),
  source_tokens / summary_tokens (экономика), prompt_tokens / completion_tokens
  / cost (сколько стоил сам вызов суммаризации), created_at;
- ``token_usage`` (TokenUsage) — метрики одного успешного хода. День 8 хранил
  prompt/completion/total/history/response/cost; день 9 добавляет
  ``mode`` ("full" | "compressed"), ``full_context_tokens`` (сколько токенов
  ушло бы без сжатия), ``sent_context_tokens`` (сколько ушло фактически),
  ``saved_tokens`` (разница), ``summary_tokens`` / ``summarized_messages``
  (из чего собран конспект этого хода) и ``summary_used`` (применялся ли он).

Движок и фабрика сессий создаются из ``config.DATABASE_URL``. Для офлайн-
проверок (временный файл/in-memory) используется ``make_engine(url)`` +
``init_db(engine)`` + своя sessionmaker — фабрика передаётся в Agent/AgentManager.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from . import config

Base = declarative_base()


def make_engine(url: str) -> Engine:
    """Создаёт движок SQLAlchemy для SQLite с поддержкой потоков FastAPI.

    ``check_same_thread=False`` нужен, потому что FastAPI обрабатывает запросы в
    пуле потоков, а сессии открываются на время операции. Внешние ключи
    включаются явно (PRAGMA foreign_keys=ON): SQLite по умолчанию их не
    проверяет, а нам нужен каскад ``messages -> agents``.
    """
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


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

    messages = relationship(
        "Message",
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


class Message(Base):
    """Одна реплика диалога агента (таблица messages).

    Реплики не удаляются при сжатии: конспект заменяет старые сообщения только
    в запросе к модели (см. ``ContextCompressor``), полная история остаётся в
    БД для аудита и восстановления.
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="messages")


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


# Движок и фабрика сессий приложения (база day9/agents.db, см. config).
engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine_: Optional[Engine] = None) -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте бэкенда."""
    Base.metadata.create_all(engine_ or engine)


def make_session_factory(engine_: Engine):
    """Фабрика сессий для произвольного движка (офлайн-тесты, временные БД)."""
    return sessionmaker(bind=engine_, autoflush=False, expire_on_commit=False)
