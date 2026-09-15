"""Общая база SQLAlchemy/SQLite (папка shared/): Base, движок и сессии.

Модели таблиц объявляет приложение дня, наследуя их от ``Base``; схема создаётся
``init_db``. Движок — SQLite с ``check_same_thread=False`` (FastAPI обрабатывает
запросы в пуле потоков) и явным ``PRAGMA foreign_keys=ON`` (SQLite по умолчанию
внешние ключи не проверяет, а приложениям нужен каскад удаления).
"""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .logging_utils import get_logger

logger = get_logger(__name__)

#: Декларативная база: приложения дней наследуют от неё свои ORM-классы.
Base = declarative_base()


def make_engine(url: str) -> Engine:
    """Создаёт движок SQLAlchemy для SQLite с поддержкой потоков FastAPI.

    ``check_same_thread=False`` нужен, потому что FastAPI обрабатывает запросы в
    пуле потоков, а сессии открываются на время операции. Внешние ключи
    включаются явно (PRAGMA foreign_keys=ON): SQLite по умолчанию их не
    проверяет, а нам нужен каскад ``short_term_messages -> agents``.
    """
    logger.debug("SQLAlchemy: создаю движок %s", url)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_db(engine: Engine, base: type = Base) -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается при старте приложения."""
    base.metadata.create_all(engine)


def make_session_factory(engine: Engine):
    """Фабрика сессий для произвольного движка (офлайн-тесты, временные БД)."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
