"""Миксин состояния задачи (день 15): создание, контролируемые переходы, флаги.

Часть ``AgentManager`` (``backend/agent_manager.py``): тонкие обёртки над
``TaskStateMachine`` для API-слоя. Миксин ничего не кэширует и не решает сам,
какой шаг или какое действие подставить: умолчания разрешает сервис
(``backend/services/task_state.py``), иначе появился бы второй источник правды
о переходах. Состояние переживает рестарт процесса, потому что читается из БД.
"""
from typing import List, Optional

from ..domain.task_fsm import TaskStage
from ..services.task_state import (
    REASON_DEFAULT,
    TaskNotFoundError,
    TaskStateMachine,
)


class TaskOpsMixin:
    """Состояние задачи: создание, переходы, пауза, откат, флаги, список."""

    @property
    def _tasks(self) -> TaskStateMachine:
        """Стейт-машина задач на фабрике сессий менеджера (без состояния в памяти)."""
        return TaskStateMachine(session_factory=self._session_factory)

    # --- чтение ---
    def get_task_state(self, task_id: str) -> Optional[dict]:
        """Текущее состояние задачи (``None`` — задачи нет)."""
        return self._tasks.get_state(task_id)

    def get_task_history(self, task_id: str) -> List[dict]:
        """Журнал попыток перехода задачи (включая создание и отказы)."""
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
        """Следующий шаг задачи (на последнем шаге этапа — следующий этап).

        Выход из этапа на последнем шаге подчиняется guard-условию этапа:
        без согласования отказ объясняет, какой флаг нужно выставить.
        """
        return self._tasks.advance_step(task_id)

    def rollback_task(self, task_id: str, to_stage: str) -> dict:
        """Откат на предыдущий этап; ``to_stage`` обязан быть целью отката."""
        return self._tasks.rollback(task_id, to_stage)

    def transition_task(self, task_id: str, stage: str, step: Optional[str] = None,
                        expected_action: Optional[str] = None,
                        reason: Optional[str] = None) -> dict:
        """Переход в указанный этап; умолчания шага и действия разрешает сервис.

        Без ``step`` берётся первый шаг целевого этапа (``finalize`` для ``done``,
        текущий шаг для ``paused``); без ``expected_action`` — текст из
        ``backend/domain/task_prompt.py``; без причины — «переход по запросу».
        Так кнопка этапа описывается одним вызовом:
        ``transition_task(task_id, "done", reason=...)``.
        """
        return self._tasks.transition_to(
            task_id, stage, step, expected_action,
            reason=reason if reason is not None else REASON_DEFAULT,
        )

    def set_task_flags(self, task_id: str, flags: dict) -> dict:
        """Выставляет флаги-согласования этапов (guard-условия переходов вперёд)."""
        return self._tasks.set_flags(task_id, flags)
