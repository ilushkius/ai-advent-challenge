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
  (``current_step``), ожидаемое действие, этап паузы (``paused_from_stage``),
  снимок данных задачи (``context`` — рабочая память и флаги согласований) и
  журнал переходов внутри строки (``history``). Строка переживает рестарт
  процесса: именно поэтому агент после перезапуска знает, где остановился;
- ``task_transitions`` (TaskTransition) — ЖУРНАЛ ПОПЫТОК ПЕРЕХОДА: по строке на
  переход и на отклонённую попытку (``from_stage``/``from_step`` →
  ``to_stage``/``to_step``, причина, время, ``accepted``). У строки создания
  задачи ``from_stage``/``from_step`` пусты, у отклонённой попытки цель может
  быть не названа.

FK ``task_transitions.task_id`` ссылается на ``task_states.task_id`` (а не на
``id``), потому что журнал запрашивается по ``task_id`` и должен уходить
каскадом вместе с состоянием. Каскады включены и на уровне ORM
(``cascade="all, delete-orphan"``), и на уровне БД (``PRAGMA foreign_keys=ON``
в ``shared.db_base.make_engine``).
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from shared.db_base import Base

from ..core import config


class TaskState(Base):
    """Состояние задачи агента (таблица task_states, день 13).

    Строка на задачу: ``task_id`` уникален, потому что состояние запрашивается
    по нему одному (``GET /tasks/{task_id}/state``) и на него ссылается журнал
    переходов. ``context`` — снимок данных задачи (рабочая память плюс флаги
    согласований этапов), ``history`` — журнал переходов внутри самой строки,
    ``paused_from_stage`` — этап, с которого задача встала на паузу.
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
    # Этап, с которого задача встала на паузу (день 15). Отдельная колонка, а не
    # ключ в context: это факт состояния задачи, по нему guard-условие решает,
    # куда паузу разрешено продолжить, и он не должен зависеть от того, какие
    # ключи контекста перезаписал очередной переход.
    paused_from_stage = Column(String(config.TASK_STAGE_MAX), nullable=True)
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
    """Одна запись журнала попыток перехода (таблица task_transitions).

    ``from_stage``/``from_step`` пусты только у строки создания задачи. FK на
    ``task_states.task_id`` (а не на ``id``) — потому что журнал запрашивается
    по ``task_id`` и должен уходить каскадом вместе с состоянием.
    ``accepted=False`` — попытка перехода, отклонённая правилами допуска: строку
    ``task_states`` она не меняет, но остаётся в журнале с причиной отказа.
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
    # Целевые этап и шаг пусты не только у ничего не значащих строк: попытка
    # перехода в неизвестный этап тоже попадает в журнал, и назвать цель у неё
    # нечем (день 15).
    to_stage = Column(String(config.TASK_STAGE_MAX), nullable=True)
    to_step = Column(String(config.TASK_STEP_MAX), nullable=True)
    # accepted=False — попытка перехода, которую правила допуска отклонили.
    # Состояние задачи такая строка не меняет: это журнал отказов, по нему
    # видно, что пользователь (или модель) пытался сделать и почему нельзя.
    accepted = Column(Boolean, nullable=False, default=True)
    reason = Column(String(config.TASK_REASON_MAX), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    task = relationship("TaskState", back_populates="transitions")
