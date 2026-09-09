"""Слой SQLAlchemy/SQLite дня 7: движок, сессии и ORM-модели.

Хранилище контекстной памяти агентов. Две таблицы (связь один-ко-многим):

- ``agents`` (AgentRecord) — конфигурация агента. Таблица добавлена сверх явно
  требуемой ``messages``: внешний ключ и восстановление диалога после рестарта
  бэкенда невозможны, если сам агент (модель, температура, системный промпт)
  не переживает перезапуск (см. design.md, D2).
- ``messages`` (Message) — реплики диалога: id (Integer, PK), agent_id
  (String, ForeignKey -> agents.agent_id, index), role, content (Text),
  timestamp (DateTime). Сохраняются только user/assistant; системный промпт
  живёт в конфигурации агента (D3).

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


# Движок и фабрика сессий приложения (база day7/agents.db, см. config).
engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine_: Optional[Engine] = None) -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте бэкенда."""
    Base.metadata.create_all(engine_ or engine)
