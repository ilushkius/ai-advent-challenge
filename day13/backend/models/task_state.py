"""ORM-таблицы состояния задачи (день 13): task_states и task_transitions.

Почему отдельный модуль, а не ``backend/tables.py``: там уже 383 строки, и две
новые таблицы вывели бы файл за лимит 400 строк из скилла
``fastapi-streamlit-day-structure``. Правило скилла — делить ORM-слой по
доменам, поэтому состояние задачи живёт здесь, а таблицы агента, памяти и
профилей остаются в ``tables.py``. Реэкспорт — через ``backend/database.py``,
как и у остальных таблиц.

Таблицы:

- ``task_states`` (TaskState) — СОСТОЯНИЕ ЗАДАЧИ: одна строка на задачу
  (``task_id`` уникален). Хранит этап (``stage``), шаг внутри этапа
  (``current_step``), ожидаемое действие, снимок данных задачи (``context``
  — рабочая память плюс метка паузы) и журнал переходов внутри строки
  (``history``). Строка переживает рестарт процесса: именно поэтому агент
  после перезапуска знает, где остановился;
- ``task_transitions`` (TaskTransition) — ЖУРНАЛ ПЕРЕХОДОВ: по строке на
  переход (``from_stage``/``from_step`` → ``to_stage``/``to_step``, причина,
  время). У строки создания задачи ``from_stage``/``from_step`` пусты.

FK ``task_transitions.task_id`` ссылается на ``task_states.task_id`` (а не на
``id``), потому что журнал запрашивается по ``task_id`` и должен уходить
каскадом вместе с состоянием. Каскады включены и на уровне ORM
(``cascade="all, delete-orphan"``), и на уровне БД (``PRAGMA foreign_keys=ON``
в ``shared.db_base.make_engine``).
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from shared.db_base import Base

from ..core import config


class TaskState(Base):
    """Состояние задачи агента (таблица task_states, день 13).

    Строка на задачу: ``task_id`` уникален, потому что состояние запрашивается
    по нему одному (``GET /tasks/{task_id}/state``) и на него ссылается журнал
    переходов. ``context`` — снимок данных задачи (рабочая память дня 11 плюс
    метка паузы), ``history`` — журнал переходов внутри самой строки.
    """

    __tablename__ = "task_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        String(config.TASK_ID_MAX), nullable=False, unique=True, index=True
    )
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    stage = Column(String(config.TASK_STAGE_MAX), nullable=False, index=True)
    current_step = Column(String(config.TASK_STEP_MAX), nullable=False)
    expected_action = Column(
        String(config.EXPECTED_ACTION_MAX), nullable=False, default=""
    )
    context = Column(JSON, nullable=False, default=dict)
    history = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="task_states")
    transitions = relationship(
        "TaskTransition",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TaskTransition(Base):
    """Один переход состояния задачи (таблица task_transitions, день 13).

    ``from_stage``/``from_step`` пусты только у строки создания задачи. FK на
    ``task_states.task_id`` (а не на ``id``) — потому что журнал запрашивается
    по ``task_id`` и должен уходить каскадом вместе с состоянием.
    """

    __tablename__ = "task_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        String(config.TASK_ID_MAX),
        ForeignKey("task_states.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_stage = Column(String(config.TASK_STAGE_MAX), nullable=True)
    from_step = Column(String(config.TASK_STEP_MAX), nullable=True)
    to_stage = Column(String(config.TASK_STAGE_MAX), nullable=False)
    to_step = Column(String(config.TASK_STEP_MAX), nullable=False)
    reason = Column(String(config.TASK_REASON_MAX), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    task = relationship("TaskState", back_populates="transitions")
