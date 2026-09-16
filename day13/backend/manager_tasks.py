"""Миксин состояния задачи (день 13): создание, переходы, пауза, откат, список.

Часть ``AgentManager`` (``backend/agent_manager.py``): тонкие обёртки над
``TaskStateMachine`` для API-слоя. Миксин ничего не кэширует: стейт-машина
создаётся на вызов и читает строку задачи из БД, поэтому состояние переживает
рестарт процесса.
"""
from typing import List, Optional

from .task_fsm import TaskStage, first_step, stage_from_value
from .task_prompt import default_expected_action
from .task_state import (
    REASON_DEFAULT,
    TaskNotFoundError,
    TaskStateMachine,
)


class TaskOpsMixin:
    """Состояние задачи: создание, переходы, пауза, откат, список."""

    @property
    def _tasks(self) -> TaskStateMachine:
        """Стейт-машина задач на фабрике сессий менеджера (без состояния в памяти)."""
        return TaskStateMachine(session_factory=self._session_factory)

    # --- чтение ---
    def get_task_state(self, task_id: str) -> Optional[dict]:
        """Текущее состояние задачи (``None`` — задачи нет)."""
        return self._tasks.get_state(task_id)

    def get_task_history(self, task_id: str) -> List[dict]:
        """Журнал переходов задачи (включая создание)."""
        return self._tasks.get_full_history(task_id)

    def list_active_tasks(self, agent_id: str) -> List[dict]:
        """Незавершённые задачи агента (пауза считается активной)."""
        return [
            state for state in self._tasks.list_states(agent_id)
            if state["is_active"]
        ]

    # --- запись ---
    def create_task(self, agent_id: str, task_id: str,
                    initial_stage: str = TaskStage.PLANNING.value) -> dict:
        """Заводит состояние задачи у существующего агента.

        Заодно делает задачу АКТИВНОЙ: блок состояния подключается к системному
        промпту только у активной задачи агента (``Agent.task_state``), поэтому
        иначе заведённое состояние молча не попало бы в запросы.
        """
        agent = self.require_agent(agent_id)  # AgentNotFoundError → 404
        state = self._tasks.create(agent_id, task_id, initial_stage)
        if agent.task_id != state["task_id"]:
            agent.set_task(state["task_id"])
        return state

    def pause_task(self, task_id: str) -> dict:
        """Ставит задачу на паузу (этап и шаг запоминаются)."""
        return self._tasks.pause(task_id)

    def resume_task(self, task_id: str) -> dict:
        """Продолжает задачу с того же этапа и шага."""
        return self._tasks.resume(task_id)

    def advance_task_step(self, task_id: str) -> dict:
        """Следующий шаг задачи (на последнем шаге этапа — следующий этап)."""
        return self._tasks.advance_step(task_id)

    def rollback_task(self, task_id: str, to_stage: str) -> dict:
        """Откат на предыдущий этап; ``to_stage`` обязан быть целью отката."""
        return self._tasks.rollback(task_id, to_stage)

    def transition_task(self, task_id: str, stage: str, step: Optional[str] = None,
                        expected_action: Optional[str] = None,
                        reason: Optional[str] = None) -> dict:
        """Переход в указанный этап с разрешением умолчаний шага и действия.

        Без ``step`` берётся первый шаг целевого этапа (``finalize`` для ``done``,
        текущий шаг для ``paused``); без ``expected_action`` — текст из
        ``backend/task_prompt.py``. Так кнопка «Завершить задачу» описывается
        одним вызовом: ``transition_task(task_id, "done", reason=...)``.
        """
        target = stage_from_value(stage)
        if step is None:
            step = self._default_step(task_id, target)
        action = (
            expected_action if expected_action is not None
            else default_expected_action(target, step)
        )
        return self._tasks.transition_to(
            task_id, target.value, step, action,
            reason=reason if reason is not None else REASON_DEFAULT,
        )

    # --- внутреннее ---
    def _default_step(self, task_id: str, target: TaskStage) -> str:
        """Шаг перехода по умолчанию: пауза не меняет шаг, остальные — первый."""
        if target is not TaskStage.PAUSED:
            return first_step(target).value
        state = self.get_task_state(task_id)
        if state is None:
            raise TaskNotFoundError(f"Задача {task_id} не найдена")
        return state["current_step"]
