"""Схемы API дня 15: состояние задачи, его переходы и журнал.

Валидация этапов и шагов не дублируется: схемы вызывают
``stage_from_value``/``step_from_value`` из ``backend/task_fsm.py``, поэтому
значение вне Enum — это 422, а не «тихий» этап-призрак в БД. Тела переходов
(``TaskTransitionIn``, ``TaskRollbackIn``) проверяют только форму; допустимость
самого перехода решает стейт-машина (``backend/task_state.py``) и отвечает на
неё 400.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core import config
from ..domain.task_fsm import TaskStage, stage_from_value, step_from_value

# Этапы, с которых разрешено заводить задачу: paused и done — не стартовые.
START_STAGES = (TaskStage.PLANNING.value, TaskStage.EXECUTION.value,
                TaskStage.VALIDATION.value)


class TaskTransitionOut(BaseModel):
    """Одна запись журнала попыток перехода (таблица task_transitions).

    ``accepted=False`` — попытка, отклонённая правилами допуска: состояние
    задачи она не меняет, а ``to_stage``/``to_step`` могут быть пустыми
    (например, попытка перехода в неизвестный этап).
    """
    id: int
    task_id: str
    from_stage: Optional[str] = None
    from_step: Optional[str] = None
    to_stage: Optional[str] = None
    to_step: Optional[str] = None
    accepted: bool = True
    reason: str = ""
    created_at: datetime


class TaskBlockedOut(BaseModel):
    """Недоступный из текущего этапа переход и короткая причина отказа."""
    stage: str
    reason: str


class TaskStateOut(BaseModel):
    """Состояние задачи: этап, шаг, ожидаемое действие и производные поля.

    ``prompt_block`` — тот же текст, что уходит в системный промпт запроса;
    ``rollback_stage`` — куда приведёт откат (``None`` — откатываться некуда);
    ``is_active`` — задача не завершена (пауза считается активной);
    ``allowed_next`` — этапы, доступные сейчас с учётом guard-условий, а
    ``blocked`` — остальные с причиной отказа: интерфейс рисует по ним
    кнопки-переходы и подсказки, не повторяя правила допуска у себя.
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
    allowed_next: List[str] = Field(default_factory=list)
    blocked: List[TaskBlockedOut] = Field(default_factory=list)
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


class TaskAllowedNextOut(BaseModel):
    """Куда задача может перейти прямо сейчас и что для этого мешает.

    Отдельный ответ для панели задачи и внешних клиентов: тот же расчёт, что
    внутри ``TaskStateOut``, но без полной строки состояния.
    """
    task_id: str
    stage: str
    allowed_next: List[str] = Field(default_factory=list)
    blocked: List[TaskBlockedOut] = Field(default_factory=list)


class TaskFlagsIn(BaseModel):
    """Тело PATCH /tasks/{task_id}/context — флаги-согласования этапов.

    Непереданный флаг не меняется (``None``), поэтому тело ``{}`` — ошибка:
    запрос, который ничего не меняет, почти всегда означает опечатку в имени
    поля, и молча вернуть 200 хуже, чем сказать об этом.
    """
    plan_approved: Optional[bool] = None
    implementation_complete: Optional[bool] = None
    validation_passed: Optional[bool] = None

    @model_validator(mode="after")
    def _at_least_one_flag(self) -> "TaskFlagsIn":
        if self.plan_approved is None and self.implementation_complete is None \
                and self.validation_passed is None:
            raise ValueError("нужен хотя бы один флаг задачи")
        return self
