"""Схемы API дня 13: состояние задачи, его переходы и журнал.

Валидация этапов и шагов не дублируется: схемы вызывают
``stage_from_value``/``step_from_value`` из ``backend/task_fsm.py``, поэтому
значение вне Enum — это 422, а не «тихий» этап-призрак в БД. Тела переходов
(``TaskTransitionIn``, ``TaskRollbackIn``) проверяют только форму; допустимость
самого перехода решает стейт-машина (``backend/task_state.py``) и отвечает на
неё 400.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..core import config
from ..domain.task_fsm import TaskStage, stage_from_value, step_from_value

# Этапы, с которых разрешено заводить задачу: paused и done — не стартовые.
START_STAGES = (TaskStage.PLANNING.value, TaskStage.EXECUTION.value,
                TaskStage.VALIDATION.value)


class TaskTransitionOut(BaseModel):
    """Одна запись журнала переходов (таблица task_transitions)."""
    id: int
    task_id: str
    from_stage: Optional[str] = None
    from_step: Optional[str] = None
    to_stage: str
    to_step: str
    reason: str = ""
    created_at: datetime


class TaskStateOut(BaseModel):
    """Состояние задачи: этап, шаг, ожидаемое действие и производные поля.

    ``prompt_block`` — тот же текст, что уходит в системный промпт запроса;
    ``rollback_stage`` — куда приведёт откат (``None`` — откатываться некуда);
    ``is_active`` — задача не завершена (пауза считается активной).
    """
    id: int
    task_id: str
    agent_id: str
    stage: str
    current_step: str
    expected_action: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    rollback_stage: Optional[str] = None
    paused_from_stage: Optional[str] = None
    is_active: bool = True
    prompt_block: str = ""


class TaskCreateIn(BaseModel):
    """Тело POST /agents/{agent_id}/tasks — завести состояние задачи."""
    task_id: str = Field(
        ..., min_length=1, max_length=config.TASK_ID_MAX,
        description="Идентификатор задачи (уникален; по нему читается состояние)",
    )
    initial_stage: str = Field(
        TaskStage.PLANNING.value,
        description=f"Начальный этап: {' | '.join(START_STAGES)}",
    )

    @field_validator("initial_stage")
    @classmethod
    def _stage_startable(cls, value: str) -> str:
        stage_from_value(value)
        if value not in START_STAGES:
            raise ValueError(
                f"нельзя завести задачу сразу на этапе {value}; "
                f"допустимые: {', '.join(START_STAGES)}"
            )
        return value


class TaskRollbackIn(BaseModel):
    """Тело POST /tasks/{task_id}/rollback — откат на предыдущий этап."""
    to_stage: str

    @field_validator("to_stage")
    @classmethod
    def _stage_known(cls, value: str) -> str:
        stage_from_value(value)
        return value


class TaskTransitionIn(BaseModel):
    """Тело POST /tasks/{task_id}/transition — переход в указанный этап и шаг.

    ``step``, ``expected_action`` и ``reason`` необязательны: их умолчания
    разрешает ``TaskOpsMixin.transition_task`` (первый шаг целевого этапа,
    ожидаемое действие из ``task_prompt``, причина «переход по запросу»).
    """
    stage: str
    step: Optional[str] = None
    expected_action: Optional[str] = Field(None, max_length=config.EXPECTED_ACTION_MAX)
    reason: Optional[str] = Field(None, max_length=config.TASK_REASON_MAX)

    @field_validator("stage")
    @classmethod
    def _stage_known(cls, value: str) -> str:
        stage_from_value(value)
        return value

    @field_validator("step")
    @classmethod
    def _step_known(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        step_from_value(value)
        return value


class TaskHistoryOut(BaseModel):
    """Журнал переходов задачи (GET /tasks/{task_id}/history)."""
    task_id: str
    entries: List[TaskTransitionOut] = Field(default_factory=list)
