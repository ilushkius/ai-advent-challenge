"""ORM-таблица персонализации дня 16: ``user_profiles`` (``UserProfile``).

Профиль пользователя (``user_id`` уникален) подключается к системному промпту
каждого запроса: ``preferences`` (JSON: tone/verbosity/language/format),
``constraints`` (JSON: max_response_length/forbidden_topics/required_disclaimers),
``custom_instructions`` (Text) и метки времени. Агент ссылается на профиль через
``agents.user_id``: один профиль применяется ко всем агентам пользователя и
меняется через ``/users/{user_id}/profile`` на лету.
"""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Integer, JSON, String, Text,
)

from shared.db_base import Base

from ..core import config


# Персонализация (день 12): профиль пользователя, подключаемый к системному
# промпту каждого запроса. Таблица не связана FK с agents намеренно: профиль —
# самостоятельная сущность (есть CRUD /users/{user_id}/profile), а агент лишь
# ссылается на user_id. Удаление профиля оставляет агентов работоспособными.
class UserProfile(Base):
    """Профиль пользователя (таблица user_profiles).

    Поля:

    - ``id`` — первичный ключ строки (Integer, autoincrement);
    - ``user_id`` — уникальный идентификатор пользователя (String, index):
      по нему профиль и подключается к запросам агента;
    - ``name`` — имя для обращения («Обращайся ко мне по имени»);
    - ``preferences`` — JSON: tone / verbosity / language / format (значения —
      варианты из backend/profiles.py, незаполненное поле = None);
    - ``constraints`` — JSON: max_response_length / forbidden_topics /
      required_disclaimers;
    - ``custom_instructions`` — Text: произвольные инструкции пользователя,
      одна инструкция на строку (см. profiles.normalize_instructions);
    - ``created_at`` / ``updated_at`` — метки времени (UTC).

    JSON-поля хранятся в SQLite как TEXT: SQLAlchemy сериализует словарь сам,
    поэтому чтение всегда даёт dict, а не строку.
    """

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(config.USER_ID_MAX), nullable=False, unique=True, index=True,
    )
    name = Column(String(config.PROFILE_NAME_MAX), nullable=False, default="")
    preferences = Column(JSON, nullable=False, default=dict)
    constraints = Column(JSON, nullable=False, default=dict)
    custom_instructions = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
