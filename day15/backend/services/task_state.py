"""Состояние задачи как конечный автомат в SQLite (день 15).

Что это.
    Публичная точка работы с состоянием задачи: ``create``, ``transition_to``,
    ``pause``, ``resume``, ``advance_step``, ``rollback``, ``set_flags`` и
    чтение. Автомат шагов (``backend/domain/task_fsm.py``) решает, КУДА идти;
    граф допуска и guard-условия (``backend/domain/task_state_machine.py``)
    решают, МОЖНО ли туда сейчас; этот модуль проверяет запрос, зовёт событие
    автомата и поручает запись хранилищу (``backend/storage/task_store.py``),
    которое пишет строку ``task_states`` и строку журнала ``task_transitions``.

Отказ — это данные, а не только исключение.
    Любая недопустимая попытка перехода проходит через ``_reject``: она
    попадает в журнал (``task_transitions.accepted = False``) и только потом
    превращается в ``InvalidTransitionError`` с короткой причиной. Благодаря
    этому в интерфейсе видно, что пользователь пытался сделать и почему
    нельзя, а состояние задачи после отказа остаётся прежним.

Зачем состояние в БД, а не в памяти.
    Состояние задачи обязано переживать перезапуск процесса: после рестарта
    агент читает строку по ``task_id`` и продолжает с того же места, без
    повторных объяснений. Поэтому у машины нет состояния в памяти — только
    хранилище на фабрике сессий, и каждый вызов читает строку заново.

Границы.
    Модуль не знает ни про LLM, ни про FastAPI/Streamlit. Тексты для промпта
    собирает ``backend/domain/task_prompt.py``, распознавание реплик —
    ``backend/domain/task_intent.py``, снимок рабочей памяти дня 11 кладёт в
    ``context`` задачи хранилище.
"""
from __future__ import annotations

from typing import Any, List, NoReturn, Optional

from ..core import config
from ..models.task_state import TaskState
from ..domain.task_fsm import (
    InvalidTransitionError,
    TaskEvent,
    TaskStage,
    TaskStep,
    first_step,
    rollback_target,
    stage_from_value,
    stage_state_from_value,
    step_from_value,
    steps_of,
)
from ..domain.task_state_machine import (
    TASK_FLAGS,
    cleared_flags,
    guard_context,
    is_transition_allowed,
    transition_error_message,
)
from ..domain.task_prompt import default_expected_action
from ..storage.task_store import TaskNotFoundError, TaskStateStore

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


def _context(row: TaskState) -> dict:
    """Guard-контекст строки задачи: флаги плюс этап, шаг и метка паузы."""
    return guard_context({
        "context": dict(row.context or {}),
        "stage": row.stage,
        "current_step": row.current_step,
        "paused_from_stage": row.paused_from_stage,
    })


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

    # --- запись ---
    def create(self, agent_id: str, task_id: str,
               initial_stage: str = TaskStage.PLANNING.value,
               initial_step: Optional[str] = None,
               expected_action: Optional[str] = None) -> dict:
        """Заводит состояние задачи и пишет первый переход журнала.

        Ошибки здесь в журнал не пишутся: строки задачи ещё нет, а журнал
        ссылается на неё по ``task_id``. Это ошибки запроса, а не отклонённый
        переход — журнал попыток описывает переходы существующей задачи.
        """
        clean_agent = (agent_id or "").strip()
        clean_task = (task_id or "").strip()
        if not clean_agent:
            raise ValueError("agent_id не может быть пустым")
        if not clean_task:
            raise ValueError("task_id не может быть пустым")

        stage = stage_from_value(initial_stage)
        if stage not in START_STAGES:
            raise InvalidTransitionError(
                f"нельзя завести задачу сразу на этапе {stage.value}"
            )
        step = (
            step_from_value(initial_step)
            if initial_step is not None
            else first_step(stage)
        )
        if step not in steps_of(stage):
            raise InvalidTransitionError(
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

    def transition_to(self, task_id: str, new_stage: str,
                      new_step: Optional[str] = None,
                      expected_action: Optional[str] = None,
                      reason: str = REASON_DEFAULT) -> dict:
        """Переход в указанный этап: единая точка проверки допуска.

        Проверки идут в порядке «этап понятен → переход разрешён графом и
        guard-условиями → шаг принадлежит целевому этапу → действие задано»:
        так отказ называет первую настоящую причину, а не следствие.
        """
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            try:
                target = stage_from_value(new_stage)
            except ValueError as exc:
                self._reject(session, row, str(exc), to_stage=None)
            current = stage_from_value(row.stage)
            context = _context(row)
            if not is_transition_allowed(current, target, context):
                self._reject(
                    session, row,
                    transition_error_message(current, target, context),
                    to_stage=target.value,
                )

            if target is TaskStage.PAUSED:
                # Пауза не двигает задачу: шаг остаётся тем, на котором встали.
                if new_step is not None and new_step != row.current_step:
                    self._reject(
                        session, row,
                        f"пауза сохраняет шаг {row.current_step}, а не {new_step}",
                        to_stage=target.value, to_step=new_step,
                    )
                step = step_from_value(row.current_step)
            elif target is TaskStage.DONE:
                # У done собственных шагов нет, но current_step остаётся finalize.
                if new_step is not None and new_step != TaskStep.FINALIZE.value:
                    self._reject(
                        session, row,
                        f"шаг {new_step} не принадлежит этапу done",
                        to_stage=target.value, to_step=new_step,
                    )
                step = TaskStep.FINALIZE
            else:
                step = step_from_value(new_step) if new_step else first_step(target)
                if step not in steps_of(target):
                    self._reject(
                        session, row,
                        f"шаг {step.value} не принадлежит этапу {target.value}",
                        to_stage=target.value, to_step=step.value,
                    )

            action = (expected_action or "").strip()
            if not action:
                action = default_expected_action(target, step)
            elif len(action) > config.EXPECTED_ACTION_MAX:
                raise ValueError(
                    f"expected_action длиннее {config.EXPECTED_ACTION_MAX} символов"
                )

            # Эффективный этап-источник для сброса флагов: у задачи на паузе это
            # этап возврата (продолжение в свой же этап согласований не отменяет),
            # у активной — текущий этап.
            source = current
            if current is TaskStage.PAUSED and row.paused_from_stage:
                source = stage_from_value(row.paused_from_stage)
            paused_from = (
                (current, step_from_value(row.current_step))
                if target is TaskStage.PAUSED else None
            )
            return self._store.apply(
                session, row, stage=target, step=step, expected_action=action,
                reason=(reason or "").strip() or REASON_DEFAULT,
                from_stage=row.stage, from_step=row.current_step,
                paused_from=paused_from,
                clear_flags=cleared_flags(source, target),
            )

    def pause(self, task_id: str) -> dict:
        """Ставит задачу на паузу, сохраняя этап и шаг для продолжения."""
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            current = stage_from_value(row.stage)
            context = _context(row)
            # Граф решает и здесь: повторная пауза и пауза завершённой задачи
            # отклоняются с объяснением, а не молчанием автомата шагов.
            if not is_transition_allowed(current, TaskStage.PAUSED, context):
                self._reject(
                    session, row,
                    transition_error_message(current, TaskStage.PAUSED, context),
                    to_stage=TaskStage.PAUSED.value,
                )
            step = step_from_value(row.current_step)
            return self._dispatch(session, row, TaskEvent.PAUSE, REASON_PAUSE,
                                  paused_from=(current, step))

    def resume(self, task_id: str) -> dict:
        """Продолжает задачу с того этапа и шага, на которых она встала.

        Продолжение в ДРУГОЙ доступный этап — это осознанный переход кнопкой
        этапа (``transition_to``), а не «resume»: здесь возвращается ровно то
        место, где задача была приостановлена.
        """
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            if row.stage != TaskStage.PAUSED.value:
                self._reject(session, row, "задача не на паузе")
            target_value = row.paused_from_stage
            if not target_value:
                self._reject(session, row, "у паузы не сохранён этап возврата")
            target = stage_from_value(target_value)
            context = _context(row)
            if not is_transition_allowed(TaskStage.PAUSED, target, context):
                self._reject(
                    session, row,
                    transition_error_message(TaskStage.PAUSED, target, context),
                    to_stage=target.value,
                )
            step = step_from_value(row.current_step)
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
            self._require_active(session, row)
            return self._dispatch(session, row, TaskEvent.ADVANCE, REASON_NEXT_STEP)

    def rollback(self, task_id: str, to_stage: Optional[str] = None,
                 reason: str = REASON_ROLLBACK) -> dict:
        """Откат на один этап назад (переданный этап обязан быть целью отката)."""
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            self._require_active(session, row)
            current = stage_from_value(row.stage)
            target = rollback_target(current)
            if target is None:
                self._reject(
                    session, row,
                    f"у этапа {current.value} нет предыдущего этапа",
                )
            if to_stage is not None and stage_from_value(to_stage) is not target:
                self._reject(
                    session, row,
                    f"откат с этапа {current.value} возможен только на этап "
                    f"{target.value}",
                    to_stage=to_stage,
                )
            return self._dispatch(session, row, TaskEvent.ROLLBACK,
                                  (reason or "").strip() or REASON_ROLLBACK)

    def set_flags(self, task_id: str, flags: dict[str, bool]) -> dict:
        """Выставить флаги-согласования этапов (guard-условия переходов вперёд).

        Флаг — это подтверждение пользователя, что этап действительно пройден.
        Неизвестный флаг — ошибка запроса: опечатка в имени не должна молча
        оставить переход закрытым.
        """
        unknown = sorted(set(flags) - set(TASK_FLAGS))
        if unknown:
            raise ValueError(f"неизвестные флаги задачи: {', '.join(unknown)}")
        if not flags:
            raise ValueError("не передан ни один флаг")
        with self._store.session() as session:
            row = self._store.state_row(session, task_id)
            return self._store.set_flags(
                session, row, {flag: bool(value) for flag, value in flags.items()}
            )

    # --- внутреннее ---
    def _reject(self, session, row: TaskState, message: str,
                to_stage: Optional[str] = None,
                to_step: Optional[str] = None) -> NoReturn:
        """Единственная точка отказа: журнал попытки, затем исключение.

        Порядок именно такой: сначала строка журнала (``accepted=False``), потом
        исключение. Состояние задачи отказ не меняет — строка ``task_states``
        остаётся прежней.
        """
        self._store.log_rejection(
            session, row, to_stage=to_stage, to_step=to_step, reason=message
        )
        raise InvalidTransitionError(message)

    def _require_active(self, session, row: TaskState) -> None:
        """Пауза — не место для шага вперёд и отката: сначала продолжение."""
        if row.stage == TaskStage.PAUSED.value:
            self._reject(
                session, row, "задача на паузе: сначала продолжите её (resume)"
            )

    def _dispatch(self, session, row: TaskState, event: TaskEvent, reason: str,
                  paused_from: Optional[tuple[TaskStage, TaskStep]] = None) -> dict:
        """Событие → пара «этап, шаг» по автомату → проверка допуска → запись.

        Проверка графа стоит здесь, а не в классах этапов: класс говорит, какая
        пара получится, а право на неё даёт ``ALLOWED_TRANSITIONS`` с guards.
        Выход из этапа на последнем шаге закрыт, если согласование этапа не
        выставлено, — и тогда отказ объясняет, какой флаг нужен.
        """
        current = stage_from_value(row.stage)
        context = _context(row)
        step = step_from_value(row.current_step)
        target, new_step = stage_state_from_value(row.stage).handle(event, step)
        if target is not current and not is_transition_allowed(current, target, context):
            self._reject(
                session, row,
                transition_error_message(current, target, context),
                to_stage=target.value,
            )
        return self._store.apply(
            session, row, stage=target, step=new_step,
            expected_action=default_expected_action(target, new_step),
            reason=reason, from_stage=row.stage, from_step=row.current_step,
            paused_from=paused_from,
            clear_flags=cleared_flags(current, target),
        )
