"""Роутер API дня 13: состояние задачи (этап, шаг, пауза, откат, журнал).

Девять эндпоинтов:

- ``POST /agents/{agent_id}/tasks`` — завести состояние задачи;
- ``GET  /agents/{agent_id}/tasks`` — незавершённые задачи агента;
- ``GET  /tasks/{task_id}/state`` — текущий этап и шаг;
- ``GET  /tasks/{task_id}/history`` — журнал переходов;
- ``POST /tasks/{task_id}/pause`` — пауза (этап и шаг запоминаются);
- ``POST /tasks/{task_id}/resume`` — продолжение с того же места;
- ``POST /tasks/{task_id}/advance`` — следующий шаг;
- ``POST /tasks/{task_id}/rollback`` — откат на предыдущий этап;
- ``POST /tasks/{task_id}/transition`` — переход в указанный этап/шаг (им
  пользуется кнопка «Завершить задачу»).

Контракт ошибок: неизвестная задача и неизвестный агент — 404; недопустимый
переход — 400; повторный ``task_id`` — 409; невалидное тело — 422.
"""
from typing import List

from fastapi import APIRouter, HTTPException

from .. import dependencies
from ..models import (
    TaskCreateIn, TaskHistoryOut, TaskRollbackIn, TaskStateOut,
    TaskTransitionIn,
)
from ..task_fsm import InvalidTaskTransition, UnknownTaskEvent
from ..task_state import TaskExistsError, TaskNotFoundError

router = APIRouter()


# ---------- состояние задачи (день 13) ----------
@router.post(
    "/agents/{agent_id}/tasks",
    response_model=TaskStateOut,
    status_code=201,
    summary="Завести состояние задачи",
    description=(
        "Создаёт строку task_states для существующего агента: этап (по "
        "умолчанию planning), первый шаг этапа и ожидаемое действие. Повторный "
        "task_id — 409: состояние не перезаписывается."
    ),
)
def create_task(agent_id: str, body: TaskCreateIn):
    dependencies.agent_or_404(agent_id)
    try:
        return dependencies.get_manager().create_task(
            agent_id, body.task_id, body.initial_stage
        )
    except TaskExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/agents/{agent_id}/tasks",
    response_model=List[TaskStateOut],
    summary="Незавершённые задачи агента",
    description=(
        "Состояния всех незавершённых задач агента (пауза считается активной). "
        "Завершённые задачи не возвращаются — они видны в журнале и в "
        "GET /tasks/{task_id}/state."
    ),
)
def list_tasks(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().list_active_tasks(agent_id)


@router.get(
    "/tasks/{task_id}/state",
    response_model=TaskStateOut,
    summary="Состояние задачи",
    description=(
        "Текущий этап, шаг, ожидаемое действие и производные поля: "
        "`rollback_stage` (куда приведёт откат), `paused_from_stage`, "
        "`is_active` и `prompt_block` — тот же текст, что уходит в системный "
        "промпт запроса."
    ),
)
def get_task_state(task_id: str):
    return dependencies.task_or_404(task_id)


@router.get(
    "/tasks/{task_id}/history",
    response_model=TaskHistoryOut,
    summary="Журнал переходов задачи",
    description=(
        "Все переходы по возрастанию id, включая создание задачи (у него "
        "`from_stage`/`from_step` пусты). Причины: «задача создана», «следующий "
        "шаг», «пауза», «продолжение после паузы», «откат на предыдущий этап»."
    ),
)
def get_task_history(task_id: str):
    dependencies.task_or_404(task_id)
    entries = dependencies.get_manager().get_task_history(task_id)
    return {"task_id": task_id, "entries": entries}


@router.post(
    "/tasks/{task_id}/pause",
    response_model=TaskStateOut,
    summary="Поставить задачу на паузу",
    description=(
        "Переводит задачу в paused, сохраняя текущий шаг: продолжение вернёт её "
        "ровно в тот же этап и шаг. Повторная пауза — 400."
    ),
)
def pause_task(task_id: str):
    return _mutate(lambda manager: manager.pause_task(task_id))


@router.post(
    "/tasks/{task_id}/resume",
    response_model=TaskStateOut,
    summary="Продолжить задачу",
    description=(
        "Возвращает задачу из paused в этап и шаг, с которых она встала. "
        "Продолжение задачи, которая не на паузе, — 400."
    ),
)
def resume_task(task_id: str):
    return _mutate(lambda manager: manager.resume_task(task_id))


@router.post(
    "/tasks/{task_id}/advance",
    response_model=TaskStateOut,
    summary="Следующий шаг задачи",
    description=(
        "Следующий шаг текущего этапа; с последнего шага этапа — первый шаг "
        "следующего этапа (planning → execution → validation → done). Из done и "
        "из paused шаг вперёд не описан: 400."
    ),
)
def advance_task(task_id: str):
    return _mutate(lambda manager: manager.advance_task_step(task_id))


@router.post(
    "/tasks/{task_id}/rollback",
    response_model=TaskStateOut,
    summary="Откатить задачу на предыдущий этап",
    description=(
        "Откат ровно на один этап назад (validation → execution, "
        "execution → planning) с шагом на первый шаг целевого этапа. "
        "`to_stage` обязан совпасть с целью отката, иначе 400."
    ),
)
def rollback_task(task_id: str, body: TaskRollbackIn):
    return _mutate(lambda manager: manager.rollback_task(task_id, body.to_stage))


@router.post(
    "/tasks/{task_id}/transition",
    response_model=TaskStateOut,
    summary="Переход в указанный этап и шаг",
    description=(
        "Прямой переход: `step`, `expected_action` и `reason` необязательны — "
        "без них берётся первый шаг целевого этапа (для done — finalize, для "
        "paused — текущий шаг), ожидаемое действие этапа и причина «переход по "
        "запросу». Так завершение задачи описывается одним вызовом: "
        "`{\"stage\": \"done\", \"reason\": \"задача завершена\"}`."
    ),
)
def transition_task(task_id: str, body: TaskTransitionIn):
    return _mutate(lambda manager: manager.transition_task(
        task_id, body.stage, body.step, body.expected_action, body.reason
    ))


def _mutate(call):
    """Общий контракт ошибок переходов: 404 — задачи нет, 400 — переход не тот."""
    try:
        return call(dependencies.get_manager())
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidTaskTransition, UnknownTaskEvent) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
