"""Слой SQLAlchemy/SQLite дня 8: движок, сессии и ORM-модели.

Хранилище агентов с контекстной памятью и метриками токенов. Три таблицы
(связь один-ко-многим от агента):

- ``agents`` (AgentRecord) — конфигурация агента;
- ``messages`` (Message) — реплики диалога: id (Integer, PK), agent_id
  (String, ForeignKey -> agents.agent_id, index), role, content (Text),
  timestamp (DateTime). Сохраняются только user/assistant; системный промпт
  живёт в конфигурации агента;
- ``token_usage`` (TokenUsage) — метрики токенов одного хода диалога: id
  (Integer, PK), agent_id (String, ForeignKey -> agents.agent_id,
  ondelete="CASCADE", index), timestamp, prompt_tokens, completion_tokens,
  total_tokens, history_tokens, response_tokens (Integer) и cost (Float).
  Одна успешная пара реплик = одна запись (заполняется той же транзакцией).

Движок и фабрика сессий создаются из ``config.DATABASE_URL``. Для офлайн-
проверок (временный файл/in-memory) используется ``make_engine(url)`` +
``init_db(engine)`` + своя sessionmaker — фабрика передаётся в Agent/AgentManager.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
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

    messages = relationship(
        "Message",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    """Одна реплика диалога агента (таблица messages).

    Поля строго по заданию: id (Integer, primary_key), agent_id (String,
    ForeignKey -> agents.agent_id, index), role (String), content (Text),
    timestamp (DateTime).
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


class TokenUsage(Base):
    """Метрики токенов одного успешного хода диалога (таблица token_usage).

    Заполняется той же транзакцией, что и пара сообщений user+assistant
    (см. design.md, D4). Поля строго по заданию дня 8: agent_id, timestamp,
    prompt_tokens, completion_tokens, total_tokens, history_tokens,
    response_tokens, cost; id добавлен как первичный ключ SQLAlchemy.
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


# Движок и фабрика сессий приложения (база day8/agents.db, см. config).
engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine_: Optional[Engine] = None) -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте бэкенда."""
    Base.metadata.create_all(engine_ or engine)
