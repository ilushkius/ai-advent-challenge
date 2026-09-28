"""ORM-таблица инвариантов (день 14): ``invariants``.

Инвариант — правило проекта, которое агент не имеет права нарушать. Хранится
ОТДЕЛЬНО от диалога: своя таблица, на неё не ссылаются ни реплики, ни слои
памяти, поэтому список правил не зависит от истории сообщений и не «вымывается»
сжатием контекста. Таблица глобальная (без ``agent_id``): инварианты описывают
проект, а не конкретного агента.

Почему отдельный модуль, а не общая таблица дня: правило скилла
``fastapi-streamlit-day-structure`` — ORM раскладывается по доменам, поэтому
инварианты живут здесь. Реэкспорт — через ``backend/storage/database.py`` и
``backend/storage/__init__.py``, как и у остальных таблиц.

Колонки:

- ``name`` — имя правила (уникально: по нему человек отличает правило в UI и в
  тексте отказа);
- ``description`` — формулировка правила; детерминированные правила проверки
  привязываются именно к описанию (``backend/domain/invariant_rules.py``);
- ``category`` / ``severity`` — члены Enum из
  ``backend/domain/invariant_values.py`` (значения — строки, проверяются при
  записи через ``InvariantManager``);
- ``is_active`` — выключенный инвариант не попадает ни в промпт, ни в проверку,
  но остаётся в таблице (его можно вернуть, не набирая текст заново).
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from shared.db_base import Base

from ..core import config


class Invariant(Base):
    """Инвариант проекта (таблица invariants, день 14)."""

    __tablename__ = "invariants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(
        String(config.INVARIANT_NAME_MAX), nullable=False, unique=True, index=True
    )
    description = Column(Text, nullable=False)
    category = Column(
        String(config.INVARIANT_CATEGORY_MAX), nullable=False, index=True
    )
    severity = Column(String(config.INVARIANT_SEVERITY_MAX), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
