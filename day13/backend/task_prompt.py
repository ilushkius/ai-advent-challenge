"""Тексты состояния задачи для системного промпта (день 13).

Что это.
    Один блок системного сообщения, из которого модель узнаёт, на каком этапе
    и шаге стоит задача, чего от пользователя ждут и что уже пройдено. Блок
    собирается из состояния задачи (``backend/task_state.py``) и добавляется в
    системный промпт КАЖДОГО запроса — поэтому после перезапуска процесса
    агенту не нужно объяснять, где он остановился.

    Формат — ровно две строки: заголовок и одна строка состояния. Пример:

        Состояние задачи (текущий этап и шаг; продолжай с этого места):
        Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие:
        ожидается реализация модуля. Предыдущие шаги: planning
        (gather_requirements, define_scope, create_plan) — завершены.

    (в действительности — без переносов: одна длинная строка).

Как запустить.
    Модуль чистый: только ``enum``-члены из ``backend/task_fsm.py`` и строковые
    литералы, никаких БД, сети и UI. Проверяется тестами:

        # из папки day13
        python -m pytest -q tests/test_task_prompt.py
"""

from __future__ import annotations

from .task_fsm import (
    STAGE_ORDER,
    TaskStage,
    TaskStep,
    stage_from_value,
    step_from_value,
    steps_of,
)

__all__ = [
    "TASK_STATE_HEADER",
    "EXPECTED_ACTIONS",
    "PAUSED_ACTION",
    "DONE_ACTION",
    "default_expected_action",
    "previous_stages_text",
    "build_prompt_block",
    "render_task_state_block",
]

# Заголовок блока: он же объясняет модели, что это не описание диалога, а место
# задачи, с которого надо продолжать.
TASK_STATE_HEADER = "Состояние задачи (текущий этап и шаг; продолжай с этого места):"

# Ожидаемое действие по паре «этап, шаг»: чего именно ждём от пользователя
# (или от агента), пока задача стоит на этом шаге.
EXPECTED_ACTIONS: dict[tuple[TaskStage, TaskStep], str] = {
    (TaskStage.PLANNING, TaskStep.GATHER_REQUIREMENTS): (
        "ожидается уточнение требований пользователем"
    ),
    (TaskStage.PLANNING, TaskStep.DEFINE_SCOPE): (
        "ожидается определение границ задачи агентом"
    ),
    (TaskStage.PLANNING, TaskStep.CREATE_PLAN): (
        "ожидается утверждение плана пользователем"
    ),
    (TaskStage.EXECUTION, TaskStep.IMPLEMENT): "ожидается реализация модуля",
    (TaskStage.EXECUTION, TaskStep.TEST_LOCALLY): (
        "ожидается локальная проверка реализации"
    ),
    (TaskStage.VALIDATION, TaskStep.REVIEW): "ожидается ревью результата пользователем",
    (TaskStage.VALIDATION, TaskStep.RUN_TESTS): "ожидается проверка тестов",
    (TaskStage.VALIDATION, TaskStep.FINALIZE): (
        "ожидается итоговое подтверждение задачи пользователем"
    ),
}

# У паузы и у завершённой задачи шаг на ожидаемое действие не влияет.
PAUSED_ACTION = "задача на паузе; ожидается продолжение (resume)"
DONE_ACTION = "задача завершена; ожидается новая задача"

# Этапы прямого хода, у которых есть собственные шаги и своё ожидаемое действие.
_STEPPED_STAGES = (TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION)


def _stage(value: str | TaskStage) -> TaskStage:
    """Этап из строки (БД/API) или из члена Enum."""
    return stage_from_value(value) if isinstance(value, str) else value


def _step(value: str | TaskStep) -> TaskStep:
    """Шаг из строки (БД/API) или из члена Enum."""
    return step_from_value(value) if isinstance(value, str) else value


def default_expected_action(stage: str | TaskStage, step: str | TaskStep) -> str:
    """Ожидаемое действие для пары «этап, шаг».

    У активных этапов действие берётся из ``EXPECTED_ACTIONS`` (пары нет —
    явный ``ValueError``: молча пустая строка в промпте хуже ошибки). У
    ``done`` и ``paused`` действие не зависит от шага.
    """
    current = _stage(stage)
    if current is TaskStage.DONE:
        return DONE_ACTION
    if current is TaskStage.PAUSED:
        return PAUSED_ACTION
    current_step = _step(step)
    try:
        return EXPECTED_ACTIONS[(current, current_step)]
    except KeyError:
        raise ValueError(
            f"Ожидаемое действие для пары {current.value}/{current_step.value} "
            "не описано"
        ) from None


def previous_stages_text(
    stage: str | TaskStage, resume_stage: str | TaskStage | None = None
) -> str:
    """Список завершённых этапов прямого хода — всё, что строго до текущего.

    У ``paused`` своего места в ``STAGE_ORDER`` нет, поэтому ориентир — этап
    возврата ``resume_stage``; если он неизвестен, ориентиром считается
    ``validation`` (то есть перечисляются планирование и выполнение).
    """
    current = _stage(stage)
    if current is TaskStage.PAUSED:
        anchor = (
            _stage(resume_stage)
            if resume_stage is not None
            else TaskStage.VALIDATION
        )
    else:
        anchor = current

    index = STAGE_ORDER.index(anchor) if anchor in STAGE_ORDER else len(STAGE_ORDER)
    finished = [
        f"{done.value} ({', '.join(step.value for step in steps_of(done))}) — завершены"
        for done in STAGE_ORDER[:index]
        if steps_of(done)
    ]
    return "; ".join(finished) if finished else "нет"


def build_prompt_block(
    stage: str | TaskStage,
    step: str | TaskStep,
    expected_action: str,
    resume_stage: str | TaskStage | None = None,
) -> str:
    """Одна строка состояния задачи для системного промпта."""
    current = _stage(stage)
    return (
        f"Текущий этап: {current.value}. "
        f"Текущий шаг: {_step(step).value}. "
        f"Ожидаемое действие: {expected_action}. "
        f"Предыдущие шаги: {previous_stages_text(current, resume_stage)}."
    )


def render_task_state_block(
    stage: str | TaskStage,
    step: str | TaskStep,
    expected_action: str,
    resume_stage: str | TaskStage | None = None,
) -> str:
    """Готовый блок системного промпта: заголовок + строка состояния.

    Именно этот текст подставляет ``Agent._system_message`` (день 13).
    """
    return (
        TASK_STATE_HEADER
        + "\n"
        + build_prompt_block(stage, step, expected_action, resume_stage)
    )
