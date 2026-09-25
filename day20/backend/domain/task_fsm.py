"""Стейт-машина состояния задачи (день 13).

Что это.
    Конечный автомат «где мы в задаче»: этап (``TaskStage``), шаг внутри этапа
    (``TaskStep``), ожидаемое действие и возможность встать на паузу и
    продолжить с того же места. Состояния и события описаны через
    ``enum.Enum``, переходы — паттерном State: у каждого этапа свой маленький
    класс с общим интерфейсом ``handle(event, step)``, который возвращает пару
    «следующий этап, следующий шаг». Классы этапов не знают ни про UI, ни про
    БД, ни про сеть — это чистый домен (см. AGENTS.md и скилл
    ``python-fsm-agent``).

    Диаграмма переходов (единственный источник правды, см. TRANSITIONS в тестах):

        PLANNING   --ADVANCE--> PLANNING (след. шаг) | с create_plan -> EXECUTION(implement)
        EXECUTION  --ADVANCE--> EXECUTION (след. шаг) | с test_locally -> VALIDATION(review)
        VALIDATION --ADVANCE--> VALIDATION (след. шаг) | с finalize -> DONE(finalize)
        PLANNING|EXECUTION|VALIDATION --PAUSE--> PAUSED (шаг сохраняется)
        PAUSED     --RESUME--> тот же этап и шаг, с которого встали
        EXECUTION  --ROLLBACK--> PLANNING(gather_requirements)
        VALIDATION --ROLLBACK--> EXECUTION(implement)
        PLANNING|PAUSED --ROLLBACK--> InvalidTransitionError
        DONE       --PAUSE|ADVANCE|ROLLBACK--> InvalidTransitionError
        любой не-paused --RESUME--> UnknownTaskEvent

    Иначе говоря: у каждого события в конкретном этапе ровно один результат,
    а всё, что не описано, — явная ошибка (``InvalidTransitionError`` для
    недопустимого перехода, ``UnknownTaskEvent`` для события, которого у этапа
    нет). Никаких «тихих» зависаний. Здесь описаны только события и шаги
    ВНУТРИ этапа; таблица допуска переходов между этапами и guard-условия
    живут в ``backend/domain/task_state_machine.py`` (день 15).

Как запустить.
    Модуль не имеет побочных эффектов на импорте и не требует зависимостей
    кроме стандартной библиотеки. Проверяется тестами:

        # из папки day20
        uv run pytest -q tests/unit/test_task_fsm.py

    Пример использования:

        state = PlanningState()
        state.handle(TaskEvent.ADVANCE, TaskStep.CREATE_PLAN)
        # -> (TaskStage.EXECUTION, TaskStep.IMPLEMENT)
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "TaskStage",
    "TaskStep",
    "TaskEvent",
    "UnknownTaskEvent",
    "InvalidTransitionError",
    "TaskStageBase",
    "PlanningState",
    "ExecutionState",
    "ValidationState",
    "DoneState",
    "PausedState",
    "STAGE_STEPS",
    "STAGE_ORDER",
    "STAGE_BY_VALUE",
    "STEP_BY_VALUE",
    "STAGE_CLASS_BY_STAGE",
    "stage_from_value",
    "step_from_value",
    "stage_state_from_value",
    "steps_of",
    "first_step",
    "next_step",
    "rollback_target",
]


class TaskStage(Enum):
    """Этапы задачи: прямой ход планирование → выполнение → валидация → готово."""

    PLANNING = "planning"
    EXECUTION = "execution"
    VALIDATION = "validation"
    DONE = "done"
    PAUSED = "paused"  # пауза: этап и шаг запоминаются и восстанавливаются


class TaskStep(Enum):
    """Шаги внутри этапа задачи."""

    GATHER_REQUIREMENTS = "gather_requirements"
    DEFINE_SCOPE = "define_scope"
    CREATE_PLAN = "create_plan"
    IMPLEMENT = "implement"
    TEST_LOCALLY = "test_locally"
    REVIEW = "review"
    RUN_TESTS = "run_tests"
    FINALIZE = "finalize"


class TaskEvent(Enum):
    """События, которые машина умеет обрабатывать."""

    ADVANCE = "advance"
    ROLLBACK = "rollback"
    PAUSE = "pause"
    RESUME = "resume"


class UnknownTaskEvent(Exception):
    """Событие не описано для текущего этапа (см. AGENTS.md: явная ошибка)."""


class InvalidTransitionError(Exception):
    """Переход между этапами недопустим (таблица допуска — в ``task_state_machine``).

    Явная ошибка вместо «тихого» перехода: в сообщении — короткая причина
    отказа, её же видит пользователь в панели задачи и в ответе API.
    """


# Шаги каждого этапа по порядку. У done и paused собственных шагов нет: у
# завершённой задачи current_step остаётся finalize, у паузы — шаг, с которого
# встали (он приходит аргументом в handle).
STAGE_STEPS: dict[TaskStage, tuple[TaskStep, ...]] = {
    TaskStage.PLANNING: (
        TaskStep.GATHER_REQUIREMENTS,
        TaskStep.DEFINE_SCOPE,
        TaskStep.CREATE_PLAN,
    ),
    TaskStage.EXECUTION: (TaskStep.IMPLEMENT, TaskStep.TEST_LOCALLY),
    TaskStage.VALIDATION: (TaskStep.REVIEW, TaskStep.RUN_TESTS, TaskStep.FINALIZE),
    TaskStage.DONE: (),
    TaskStage.PAUSED: (),
}

# Прямой ход задачи. paused в него не входит: её место задаёт метка паузы
# (paused_from_stage), а не позиция в списке этапов.
STAGE_ORDER: tuple[TaskStage, ...] = (
    TaskStage.PLANNING,
    TaskStage.EXECUTION,
    TaskStage.VALIDATION,
    TaskStage.DONE,
)

# Таблицы «значение → член Enum»: состояние приходит из БД и API строкой.
STAGE_BY_VALUE: dict[str, TaskStage] = {stage.value: stage for stage in TaskStage}
STEP_BY_VALUE: dict[str, TaskStep] = {step.value: step for step in TaskStep}


def stage_from_value(value: str) -> TaskStage:
    """Этап по строковому значению из БД/API; неизвестное — явный ValueError."""
    try:
        return STAGE_BY_VALUE[value]
    except KeyError:
        allowed = ", ".join(stage.value for stage in TaskStage)
        raise ValueError(
            f"Неизвестный этап задачи: {value!r}. Допустимые: {allowed}"
        ) from None


def step_from_value(value: str) -> TaskStep:
    """Шаг по строковому значению из БД/API; неизвестное — явный ValueError."""
    try:
        return STEP_BY_VALUE[value]
    except KeyError:
        allowed = ", ".join(step.value for step in TaskStep)
        raise ValueError(
            f"Неизвестный шаг задачи: {value!r}. Допустимые: {allowed}"
        ) from None


def steps_of(stage: TaskStage) -> tuple[TaskStep, ...]:
    """Шаги этапа по порядку (у done и paused — пустой кортеж)."""
    return STAGE_STEPS[stage]


def next_step(stage: TaskStage, step: TaskStep) -> TaskStep | None:
    """Следующий шаг того же этапа; ``None`` — если шаг в этапе последний."""
    steps = STAGE_STEPS[stage]
    if step not in steps:
        raise ValueError(f"Шаг {step.value} не принадлежит этапу {stage.value}")
    index = steps.index(step)
    return steps[index + 1] if index + 1 < len(steps) else None


def first_step(stage: TaskStage) -> TaskStep:
    """Первый шаг этапа; этап без шагов — явная ошибка.

    У ``done`` собственных шагов нет, но ``current_step`` завершённой задачи
    остаётся ``finalize`` — поэтому для ``done`` возвращается именно он.
    """
    if stage is TaskStage.DONE:
        return TaskStep.FINALIZE
    steps = STAGE_STEPS[stage]
    if not steps:
        raise InvalidTransitionError(f"у этапа {stage.value} нет собственных шагов")
    return steps[0]


def rollback_target(stage: TaskStage) -> TaskStage | None:
    """Предыдущий этап прямого хода; ``None`` — откатываться некуда.

    ``None`` у ``planning`` (это первый этап), у ``paused`` (её место задаёт
    метка паузы, а не порядок этапов) и у ``done``: задача сдана, откат из
    терминального этапа не описан.
    """
    if stage not in STAGE_ORDER or stage is TaskStage.DONE:
        return None
    index = STAGE_ORDER.index(stage)
    return STAGE_ORDER[index - 1] if index > 0 else None


class TaskStageBase:
    """Базовый этап: общий интерфейс ``handle`` и поведение по умолчанию.

    Поведение по умолчанию — явная ошибка: если подкласс не переопределил
    событие, значит, для этого этапа оно не описано.
    """

    stage: TaskStage

    def handle(self, event: TaskEvent, step: TaskStep) -> tuple[TaskStage, TaskStep]:
        """Обработать событие и вернуть пару «следующий этап, следующий шаг».

        Подклассы переопределяют метод только для своих событий, а для всех
        прочих вызывают ``super().handle(event, step)`` — так таблица переходов
        каждого этапа читается одним взглядом.
        """
        raise UnknownTaskEvent(
            f"Событие {event.value} не описано для этапа {self.stage.value}"
        )

    def __str__(self) -> str:
        return self.stage.value


class PlanningState(TaskStageBase):
    """PLANNING: собираем требования, определяем границы, утверждаем план."""

    stage = TaskStage.PLANNING

    def handle(self, event: TaskEvent, step: TaskStep) -> tuple[TaskStage, TaskStep]:
        if event is TaskEvent.ADVANCE:
            following = next_step(self.stage, step)
            if following is not None:
                return (self.stage, following)
            return (TaskStage.EXECUTION, first_step(TaskStage.EXECUTION))
        if event is TaskEvent.PAUSE:
            return (TaskStage.PAUSED, step)
        if event is TaskEvent.ROLLBACK:
            raise InvalidTransitionError("у этапа planning нет предыдущего этапа")
        return super().handle(event, step)


class ExecutionState(TaskStageBase):
    """EXECUTION: реализация и локальная проверка."""

    stage = TaskStage.EXECUTION

    def handle(self, event: TaskEvent, step: TaskStep) -> tuple[TaskStage, TaskStep]:
        if event is TaskEvent.ADVANCE:
            following = next_step(self.stage, step)
            if following is not None:
                return (self.stage, following)
            return (TaskStage.VALIDATION, first_step(TaskStage.VALIDATION))
        if event is TaskEvent.PAUSE:
            return (TaskStage.PAUSED, step)
        if event is TaskEvent.ROLLBACK:
            target = rollback_target(self.stage)
            return (target, first_step(target))
        return super().handle(event, step)


class ValidationState(TaskStageBase):
    """VALIDATION: ревью, прогон тестов, финализация."""

    stage = TaskStage.VALIDATION

    def handle(self, event: TaskEvent, step: TaskStep) -> tuple[TaskStage, TaskStep]:
        if event is TaskEvent.ADVANCE:
            following = next_step(self.stage, step)
            if following is not None:
                return (self.stage, following)
            return (TaskStage.DONE, first_step(TaskStage.DONE))
        if event is TaskEvent.PAUSE:
            return (TaskStage.PAUSED, step)
        if event is TaskEvent.ROLLBACK:
            target = rollback_target(self.stage)
            return (target, first_step(target))
        return super().handle(event, step)


class DoneState(TaskStageBase):
    """DONE: задача завершена.

    Этап терминальный: из сданной задачи переходов нет вовсе — ни вперёд, ни
    назад, ни на паузу. Приостановить сданную задачу нельзя: продолжать её
    некуда, а «пауза» подразумевала бы возврат. Нужна доработка — заводится
    новая задача (таблица допуска — в ``backend/domain/task_state_machine.py``).
    """

    stage = TaskStage.DONE

    def handle(self, event: TaskEvent, step: TaskStep) -> tuple[TaskStage, TaskStep]:
        if (
            event is TaskEvent.PAUSE
            or event is TaskEvent.ADVANCE
            or event is TaskEvent.ROLLBACK
        ):
            raise InvalidTransitionError("завершена: этап done терминальный")
        return super().handle(event, step)


class PausedState(TaskStageBase):
    """PAUSED: задача на паузе; помнит этап, с которого встали.

    Шаг пауза не меняет — он приходит аргументом ``step`` и возвращается как
    есть при RESUME. Поэтому «продолжить без повторных объяснений» — это
    ровно пара «этап возврата, тот же шаг».
    """

    stage = TaskStage.PAUSED

    def __init__(self, resume_stage: TaskStage) -> None:
        self.resume_stage = resume_stage

    def handle(self, event: TaskEvent, step: TaskStep) -> tuple[TaskStage, TaskStep]:
        if event is TaskEvent.RESUME:
            return (self.resume_stage, step)
        if (
            event is TaskEvent.ADVANCE
            or event is TaskEvent.ROLLBACK
            or event is TaskEvent.PAUSE
        ):
            raise InvalidTransitionError(
                "задача на паузе: сначала продолжите её (resume)"
            )
        return super().handle(event, step)


# Таблица «этап → класс этапа»: нужна, чтобы восстанавливать машину из БД, где
# этап хранится строкой. У PausedState конструктор требует этап возврата.
STAGE_CLASS_BY_STAGE: dict[TaskStage, type[TaskStageBase]] = {
    TaskStage.PLANNING: PlanningState,
    TaskStage.EXECUTION: ExecutionState,
    TaskStage.VALIDATION: ValidationState,
    TaskStage.DONE: DoneState,
    TaskStage.PAUSED: PausedState,
}


def stage_state_from_value(
    value: str, resume_stage: TaskStage | None = None
) -> TaskStageBase:
    """Восстановить объект этапа по значению из БД/API.

    Для ``paused`` обязателен ``resume_stage`` (этап, с которого встали): без
    него пауза не знает, куда возвращать, — это явная ошибка, а не догадка.
    """
    stage = stage_from_value(value)
    if stage is TaskStage.PAUSED:
        if resume_stage is None:
            raise ValueError("этап paused требует resume_stage")
        return PausedState(resume_stage)
    return STAGE_CLASS_BY_STAGE[stage]()
