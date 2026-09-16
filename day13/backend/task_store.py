"""Хранилище состояния задачи в SQLite (день 13): ``TaskStateStore``.

Что это.
    Единственное место дня, которое открывает сессии и трогает таблицы
    ``task_states`` и ``task_transitions``: чтение состояния и журнала, запись
    одного перехода (``apply``) и проекция ORM-строки в словарь для API/UI.

Почему отдельный модуль от ``task_state.py``.
    Поведение («какие переходы допустимы, какой шаг за каким идёт, что делать
    с паузой») живёт в ``backend/task_state.py`` (``TaskStateMachine``) и
    ``backend/task_fsm.py``; здесь — только хранение. Разделение то же, что
    ``profile_store.py`` / ``agent.py`` в дне 12: стейт-машину читают, не
    отвлекаясь на SQLAlchemy, а хранилище тестируется без автомата.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from shared.logging_utils import get_logger

from . import database
from .database import TaskState, TaskTransition
from .memory import MemoryManager
from .task_fsm import TaskStage, TaskStep, rollback_target, stage_from_value
from .task_prompt import render_task_state_block

__all__ = ["TaskNotFoundError", "TaskStateStore"]

logger = get_logger(__name__)


class TaskNotFoundError(Exception):
    """Состояние задачи отсутствует в БД (API отвечает 404)."""


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Приводит метку времени к UTC-aware (как ``profile_store._as_utc``).

    Пишем в БД aware-значения, а SQLite возвращает naive: без нормализации одна
    и та же задача отдавалась бы в API то с ``+00:00``, то без него.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TaskStateStore:
    """Строки task_states/task_transitions: чтение состояния и запись переходов."""

    def __init__(self, session_factory=None,
                 memory: Optional[MemoryManager] = None) -> None:
        self._session_factory = session_factory or database.SessionLocal
        self._memory = memory

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в AgentManager)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def memory_manager(self) -> MemoryManager:
        """Хранилище рабочей памяти на той же фабрике сессий."""
        if self._memory is None:
            self._memory = MemoryManager(session_factory=self._session_factory)
        return self._memory

    def working_snapshot(self, agent_id: str, task_id: str) -> dict:
        """Снимок рабочей памяти задачи: ``{key: value}`` на момент перехода."""
        return {
            row["key"]: row["value"]
            for row in self.memory_manager().get_working(agent_id, task_id)
        }

    # --- чтение ---
    def state(self, task_id: str) -> Optional[dict]:
        """Состояние задачи или ``None``, если задачи с таким id нет."""
        with self.session() as session:
            row = (
                session.query(TaskState)
                .filter(TaskState.task_id == task_id)
                .first()
            )
            return self.state_dict(row) if row is not None else None

    def state_row(self, session, task_id: str) -> TaskState:
        """Строка задачи в уже открытой сессии или ``TaskNotFoundError``."""
        row = (
            session.query(TaskState)
            .filter(TaskState.task_id == task_id)
            .first()
        )
        if row is None:
            raise TaskNotFoundError(f"Задача {task_id} не найдена")
        return row

    def state_dict(self, row: TaskState) -> dict:
        """ORM-строка → словарь для API/UI (с производными полями)."""
        context = dict(row.context or {})
        paused_from = context.get("paused_from_stage")
        return {
            "id": row.id,
            "task_id": row.task_id,
            "agent_id": row.agent_id,
            "stage": row.stage,
            "current_step": row.current_step,
            "expected_action": row.expected_action,
            "context": context,
            "history": list(row.history or []),
            "created_at": _as_utc(row.created_at),
            "updated_at": _as_utc(row.updated_at),
            "rollback_stage": _rollback_value(row.stage),
            "paused_from_stage": paused_from,
            "is_active": row.stage != TaskStage.DONE.value,
            "prompt_block": render_task_state_block(
                row.stage, row.current_step, row.expected_action,
                resume_stage=paused_from,
            ),
        }

    def history(self, task_id: str) -> List[dict]:
        """Журнал переходов задачи по возрастанию id (включая создание)."""
        with self.session() as session:
            self.state_row(session, task_id)
            rows = (
                session.query(TaskTransition)
                .filter(TaskTransition.task_id == task_id)
                .order_by(TaskTransition.id.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "task_id": row.task_id,
                    "from_stage": row.from_stage,
                    "from_step": row.from_step,
                    "to_stage": row.to_stage,
                    "to_step": row.to_step,
                    "reason": row.reason,
                    "created_at": _as_utc(row.created_at),
                }
                for row in rows
            ]

    def states(self, agent_id: str) -> List[dict]:
        """Состояния всех задач агента по возрастанию id."""
        with self.session() as session:
            rows = (
                session.query(TaskState)
                .filter(TaskState.agent_id == agent_id)
                .order_by(TaskState.id.asc())
                .all()
            )
            return [self.state_dict(row) for row in rows]

    # --- запись ---
    def apply(self, session, row: TaskState, *, stage: TaskStage, step: TaskStep,
              expected_action: str, reason: str, from_stage: Optional[str],
              from_step: Optional[str],
              paused_from: Optional[tuple[TaskStage, TaskStep]]) -> dict:
        """Единственный путь записи перехода: history + журнал + поля строки.

        ``from_stage``/``from_step`` передаются явно (у создания задачи они
        пусты), ``paused_from`` — пара «этап, шаг», с которых встали на паузу;
        у любого перехода, кроме перехода в paused, метка снимается.
        """
        now = datetime.now(timezone.utc)
        row.history = list(row.history or []) + [{
            "at": now.isoformat(),
            "from_stage": from_stage,
            "from_step": from_step,
            "to_stage": stage.value,
            "to_step": step.value,
            "reason": reason,
            "expected_action": expected_action,
        }]
        row.stage = stage.value
        row.current_step = step.value
        row.expected_action = expected_action
        context = dict(row.context or {})
        context["task_id"] = row.task_id
        context["working_memory"] = self.working_snapshot(row.agent_id, row.task_id)
        context["paused_from_stage"] = paused_from[0].value if paused_from else None
        context["paused_from_step"] = paused_from[1].value if paused_from else None
        row.context = context
        row.updated_at = now
        session.add(TaskTransition(
            task_id=row.task_id, from_stage=from_stage, from_step=from_step,
            to_stage=stage.value, to_step=step.value, reason=reason,
            created_at=now,
        ))
        session.commit()
        logger.debug(
            "Переход задачи %s: %s/%s -> %s/%s (%s)", row.task_id, from_stage,
            from_step, stage.value, step.value, reason,
        )
        return self.state_dict(row)


def _rollback_value(stage_value: str) -> Optional[str]:
    """Этап отката для производного поля ``rollback_stage`` (или ``None``)."""
    target = rollback_target(stage_from_value(stage_value))
    return target.value if target is not None else None
