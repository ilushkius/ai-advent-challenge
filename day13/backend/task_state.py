"""Состояние задачи как конечный автомат в SQLite (день 13): ``TaskStateMachine``.

Что это.
    Публичная точка работы с состоянием задачи: ``create``, ``transition_to``,
    ``pause``, ``resume``, ``advance_step``, ``rollback`` и чтение. Автомат
    (``backend/task_fsm.py``) решает, КУДА идти; этот модуль проверяет запрос,
    зовёт событие автомата и поручает запись хранилищу (``backend/task_store.py``),
    которое пишет строку ``task_states`` и строку журнала ``task_transitions``.

Зачем состояние в БД, а не в памяти.
    Состояние задачи обязано переживать перезапуск процесса: после рестарта
    агент читает строку по ``task_id`` и продолжает с того же места, без
    повторных объяснений. Поэтому у машины нет состояния в памяти — только
    хранилище на фабрике сессий, и каждый вызов читает строку заново.

Границы.
    Модуль не знает ни про LLM, ни про FastAPI/Streamlit. Тексты для промпта
    собирает ``backend/task_prompt.py``, распознавание реплик —
    ``backend/task_intent.py``, снимок рабочей памяти дня 11 кладёт в
    ``context`` задачи хранилище.
"""
from __future__ import annotations

from typing import Any, List, Optional

from . import config
from .database import TaskState
from .task_fsm import (
    InvalidTaskTransition,
    TaskEvent,
    TaskStage,
    TaskStep,
    first_step,
    is_valid_transition as fsm_is_valid_transition,
    rollback_target,
    stage_from_value,
    stage_state_from_value,
    step_from_value,
    steps_of,
)
from .task_prompt import default_expected_action
from .task_store import TaskNotFoundError, TaskStateStore

__all__ = [
    "TaskNotFoundError",
    "TaskExistsError",
    "TaskStateMachine",
]

# Этапы, с которых задачу можно завести. paused и done — не стартовые: задача
# не может быть создана уже приостановленной или сданной.
START_STAGES = (TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION)

# Причины переходов, попадающие в журнал: одно место, чтобы тексты не расползались.
REASON_CREATED = "задача создана"
REASON_NEXT_STEP = "следующий шаг"
REASON_PAUSE = "пауза"
REASON_RESUME = "продолжение после паузы"
REASON_ROLLBACK = "откат на предыдущий этап"
REASON_DONE = "задача завершена"
REASON_DEFAULT = "переход по запросу"


class TaskExistsError(Exception):
    """Задача с таким task_id уже заведена (POST отвечает 409)."""


class TaskStateMachine:
    """Переходы состояния задачи с журналом в task_transitions и history."""

    def __init__(self, session_factory=None,
                 memory: Optional[Any] = None) -> None:
        self._store = TaskStateStore(session_factory=session_factory, memory=memory)

    # --- чтение ---
    def get_state(self, task_id: str) -> Optional[dict]:
        """Текущее состояние задачи (``None`` — задачи с таким id нет)."""
        return self._store.state(task_id)

    def get_full_history(self, task_id: str) -> List[dict]:
        """Журнал переходов задачи по возрастанию id (включая создание)."""
        return self._store.history(task_id)

    def list_states(self, agent_id: str) -> List[dict]:
        """Состояния всех задач агента по возрастанию id."""
        return self._store.states(agent_id)

    @staticmethod
    def is_valid_transition(from_stage: Any, to_stage: Any) -> bool:
        """Допустим ли переход между этапами (строки или члены ``TaskStage``)."""
        return fsm_is_valid_transition(from_stage, to_stage)

    # --- запись ---
    def create(self, agent_id: str, task_id: str,
               initial_stage: str = TaskStage.PLANNING.value,
               initial_step: Optional[str] = None,
               expected_action: Optional[str] = None) -> dict:
        """Заводит состояние задачи и пишет первый переход журнала."""
        clean_agent = (agent_id or "").strip()
        clean_task = (task_id or "").strip()
        if not clean_agent:
            raise ValueError("agent_id не может быть пустым")
        if not clean_task:
            raise ValueError("task_id не может быть пустым")

        stage = stage_from_value(initial_stage)
        if stage not in START_STAGES:
            raise InvalidTaskTransition(
                f"нельзя завести задачу сразу на этапе {stage.value}"
            )
        step = (
            step_from_value(initial_step)
            if initial_step is not None
            else first_step(stage)
        )
        if step not in steps_of(stage):
            raise InvalidTaskTransition(
                f"шаг {step.value} не принадлежит этапу {stage.value}"
            )
        action = (
            expected_action if expected_action is not None
            else default_expected_action(stage, step)
        )

        with self._store.session() as session:
            already = (
                session.query(TaskState)
                .filter(TaskState.task_id == clean_task)
                .first()
            )
            if already is not None:
                raise TaskExistsError(f"Задача {clean_task} уже существует")
            row = TaskState(
                task_id=clean_task, agent_id=clean_agent, stage=stage.value,
                current_step=step.value, expected_action=action, context={},
                history=[],
            )
            session.add(row)
            session.flush()
            return self._store.apply(
                session, row, stage=stage, step=step, expected_action=action,
                reason=REASON_CREATED, from_stage=None, from_step=None,
                paused_from=None,
            )

    def transition_to(self, task_id: str, new_stage: str, new_step: str,
                      expected_action: str,
                      reason: str = REASON_DEFAULT) -> dict:
        """Переход в явно указанные этап и шаг (единая точка валидации)."""
        target = stage_from_value(new_stage)
        step = step_from_value(new_step)
        action = (expected_action or "").strip()
        if not action:
            raise ValueError("expected_action не может быть пустым")
        if len(action) > config.EXPECTED_ACTION_MAX:
            raise ValueError(
                f"expected_action длиннее {config.EXPECTED_ACTION_MAX} символов"
            )

        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            current = stage_from_value(row.stage)
            if not fsm_is_valid_transition(current, target):
                raise InvalidTaskTransition(
                    f"переход {current.value} -> {target.value} недопустим"
                )
            if target is TaskStage.PAUSED:
                # Пауза не двигает задачу: шаг остаётся тем, на котором встали.
                if step.value != row.current_step:
                    raise InvalidTaskTransition(
                        f"пауза сохраняет шаг {row.current_step}, а не {step.value}"
                    )
            elif target is TaskStage.DONE:
                # У done собственных шагов нет, но current_step остаётся finalize.
                if step is not TaskStep.FINALIZE:
                    raise InvalidTaskTransition(
                        f"шаг {step.value} не принадлежит этапу done"
                    )
            elif step not in steps_of(target):
                raise InvalidTaskTransition(
                    f"шаг {step.value} не принадлежит этапу {target.value}"
                )
            paused_from = (
                (current, step_from_value(row.current_step))
                if target is TaskStage.PAUSED else None
            )
            return self._store.apply(
                session, row, stage=target, step=step, expected_action=action,
                reason=(reason or "").strip() or REASON_DEFAULT,
                from_stage=row.stage, from_step=row.current_step,
                paused_from=paused_from,
            )

    def pause(self, task_id: str) -> dict:
        """Ставит задачу на паузу, сохраняя этап и шаг для продолжения."""
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            current = stage_from_value(row.stage)
            if current is TaskStage.PAUSED:
                raise InvalidTaskTransition("задача уже на паузе")
            step = step_from_value(row.current_step)
            return self._dispatch(session, row, TaskEvent.PAUSE, REASON_PAUSE,
                                  paused_from=(current, step))

    def resume(self, task_id: str) -> dict:
        """Продолжает задачу с того этапа и шага, на которых она встала."""
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            if row.stage != TaskStage.PAUSED.value:
                raise InvalidTaskTransition("задача не на паузе")
            resume_value = (row.context or {}).get("paused_from_stage")
            if resume_value is None:
                raise InvalidTaskTransition("у паузы не сохранён этап возврата")
            step = step_from_value(row.current_step)
            target = stage_from_value(resume_value)
            return self._store.apply(
                session, row, stage=target, step=step,
                expected_action=default_expected_action(target, step),
                reason=REASON_RESUME, from_stage=row.stage,
                from_step=row.current_step, paused_from=None,
            )

    def advance_step(self, task_id: str) -> dict:
        """Следующий шаг задачи (с последнего шага этапа — следующий этап)."""
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            self._require_active(row)
            return self._dispatch(session, row, TaskEvent.ADVANCE, REASON_NEXT_STEP)

    def rollback(self, task_id: str, to_stage: Optional[str] = None,
                 reason: str = REASON_ROLLBACK) -> dict:
        """Откат на один этап назад (переданный этап обязан быть целью отката)."""
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            self._require_active(row)
            current = stage_from_value(row.stage)
            target = rollback_target(current)
            if target is None:
                raise InvalidTaskTransition(
                    f"у этапа {current.value} нет предыдущего этапа"
                )
            if to_stage is not None and stage_from_value(to_stage) is not target:
                raise InvalidTaskTransition(
                    f"откат с этапа {current.value} возможен только на этап "
                    f"{target.value}"
                )
            return self._dispatch(session, row, TaskEvent.ROLLBACK,
                                  (reason or "").strip() or REASON_ROLLBACK)

    # --- внутреннее ---
    def _require_active(self, row: TaskState) -> None:
        """Пауза — не место для шага вперёд и отката: сначала продолжение."""
        if row.stage == TaskStage.PAUSED.value:
            raise InvalidTaskTransition(
                "задача на паузе: сначала продолжите её (resume)"
            )

    def _dispatch(self, session, row: TaskState, event: TaskEvent, reason: str,
                  paused_from: Optional[tuple[TaskStage, TaskStep]] = None) -> dict:
        """Событие → пара «этап, шаг» по автомату → запись перехода."""
        step = step_from_value(row.current_step)
        target, new_step = stage_state_from_value(row.stage).handle(event, step)
        return self._store.apply(
            session, row, stage=target, step=new_step,
            expected_action=default_expected_action(target, new_step),
            reason=reason, from_stage=row.stage, from_step=row.current_step,
            paused_from=paused_from,
        )
