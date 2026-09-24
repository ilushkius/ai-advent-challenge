"""Роутер API дня 18: планировщик фоновых задач.

Четырнадцать эндпоинтов — три группы и служебная точка:

- **задачи**: ``GET/POST /scheduler/tasks``, ``DELETE /scheduler/tasks/{id}``,
  ``POST .../pause``, ``POST .../resume``, ``POST .../run``,
  ``GET .../history``, ``GET /scheduler/tools``, ``GET /scheduler/status``;
- **что инструменты накопили**: ``GET /scheduler/reminders``, ``/collected``,
  ``/summaries``;
- **очередь уведомлений**: ``GET /scheduler/notifications``,
  ``POST /scheduler/notifications/{id}/read``.

``POST /scheduler/tasks`` — ОБЩИЙ код-путь дня: им пользуются и MCP-инструменты
(их тела — один HTTP-вызов этой ручки, ``mcp_server/backend_api.py``), и человек в
интерфейсе. Он идёт в ``ScheduleService.create_task``, поэтому распознавание
аргументов, расписание и немедленное действие у обоих входов одинаковы.

Контракт ошибок: незнакомый инструмент, негодные аргументы, неразобранное
расписание — 400; удалённая или несуществующая задача — 404; пауза не активной
задачи и возобновление не стоящей на паузе — 409 (это конфликт состояний, а не
ошибка запроса); невалидное тело — 422 (Pydantic). Отказ приходит из домена
данными (``ScheduleRejected.reason_code``) и переводится в код здесь.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..core import config
from ..core import dependencies
from ..domain.schedule_spec import ScheduleRejected
from ..domain.scheduler_values import (
    REASON_NOT_ACTIVE,
    REASON_NOT_FOUND,
    REASON_NOT_PAUSED,
    ReminderState,
    ScheduledTaskState,
)
from ..schemas import (
    CollectedResponse,
    NotificationOut,
    NotificationsResponse,
    RemindersResponse,
    ScheduledTaskOut,
    SchedulerRunOut,
    SchedulerRunsResponse,
    SchedulerStatusOut,
    SchedulerTaskCreateOut,
    SchedulerTaskIn,
    SchedulerTasksResponse,
    SchedulerToolsResponse,
    SummariesResponse,
)

router = APIRouter()

#: Код причины отказа → HTTP-статус (остальные причины — 400: негодный запрос).
_STATUS_BY_REASON = {
    REASON_NOT_FOUND: 404,
    REASON_NOT_ACTIVE: 409,
    REASON_NOT_PAUSED: 409,
}


def _rejected(exc: ScheduleRejected) -> HTTPException:
    """Переводит отказ планировщика в HTTP-ошибку с его текстом."""
    code = _STATUS_BY_REASON.get(exc.reason_code, 400)
    return HTTPException(status_code=code, detail=exc.message)


# ---------- задачи ----------
@router.get(
    "/scheduler/tasks",
    response_model=SchedulerTasksResponse,
    summary="Список задач планировщика",
    description=(
        "Все задачи планировщика (по возрастанию номера) с расписанием, "
        "состоянием, метками последнего и следующего запуска и допустимыми "
        "событиями FSM. Необязательный `status` фильтрует по состоянию "
        "(`active` | `paused` | `completed`); блок `scheduler` показывает, "
        "работает ли обслуживание таймеров и сколько задач поставлено."
    ),
)
def scheduler_tasks(status: Optional[str] = None):
    _check_state(status)
    return dependencies.get_schedule_service().list_tasks(status=status)


@router.post(
    "/scheduler/tasks",
    response_model=SchedulerTaskCreateOut,
    status_code=201,
    summary="Создать задачу планировщика",
    description=(
        "Проверяет аргументы инструмента, выводит расписание (или берёт "
        "переопределённое `schedule_type`/`schedule_value`), создаёт строку в "
        "`scheduled_tasks` и ставит задачу в планировщик. При `run_now=true` "
        "(по умолчанию) немедленно выполняет действие инструмента: напоминание "
        "сохраняется, сбор делает первый запрос, сводка считается сразу за "
        "прошедший интервал — результат виден в `result`, подтверждение в "
        "`message`. Неудача немедленного шага не отменяет задачу: причина в "
        "`error`, а попытка повторится по расписанию."
    ),
)
def scheduler_create(body: SchedulerTaskIn):
    service = dependencies.get_schedule_service()
    try:
        return service.create_task(
            tool=body.tool, arguments=body.arguments, name=body.name,
            run_now=body.run_now, schedule_type=_type_value(body.schedule_type),
            schedule_value=body.schedule_value,
        )
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc


@router.delete(
    "/scheduler/tasks/{task_id}",
    summary="Удалить задачу планировщика",
    description=(
        "Снимает задачу с обслуживания и удаляет её строку вместе с журналом "
        "запусков (каскад). Напоминания, сводки и уведомления остаются — у них "
        "ссылка на задачу обнуляется. Нет такой задачи — 404."
    ),
)
def scheduler_delete(task_id: int):
    service = dependencies.get_schedule_service()
    try:
        service.delete_task(task_id)
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc
    return {"status": "deleted", "task_id": task_id}


@router.post(
    "/scheduler/tasks/{task_id}/pause",
    response_model=ScheduledTaskOut,
    summary="Поставить задачу на паузу",
    description=(
        "Переводит задачу из `active` в `paused`: расписание сохраняется, "
        "запусков нет. Попытка поставить на паузу не активную задачу — 409 с "
        "перечнем допустимых событий; удалённая задача — 404."
    ),
)
def scheduler_pause(task_id: int) -> ScheduledTaskOut:
    return _task_action(task_id, "pause")


@router.post(
    "/scheduler/tasks/{task_id}/resume",
    response_model=ScheduledTaskOut,
    summary="Возобновить задачу",
    description=(
        "Переводит задачу из `paused` в `active` и ставит её в планировщик заново "
        "(если пауза пережила перезапуск процесса). Возобновление не стоящей на "
        "паузе задачи — 409; удалённая задача — 404."
    ),
)
def scheduler_resume(task_id: int) -> ScheduledTaskOut:
    return _task_action(task_id, "resume")


def _task_action(task_id: int, action: str) -> ScheduledTaskOut:
    """Общий путь паузы и возобновления: одна точка перевода отказа в статус."""
    service = dependencies.get_schedule_service()
    try:
        row = (service.pause_task(task_id) if action == "pause"
               else service.resume_task(task_id))
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc
    return ScheduledTaskOut.from_row(row)


@router.post(
    "/scheduler/tasks/{task_id}/run",
    response_model=SchedulerRunOut,
    summary="Запустить задачу вне расписания",
    description=(
        "Выполняет тик задачи прямо сейчас — тем же кодом, что и запуск по "
        "расписанию, поэтому запись попадает в журнал запусков. Разовая задача "
        "после успешного запуска переходит в `completed` и снимается; уже "
        "выполненная задача — 409; удалённая — 404."
    ),
)
def scheduler_run(task_id: int):
    service = dependencies.get_schedule_service()
    try:
        return service.run_task_now(task_id)
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc


@router.get(
    "/scheduler/tasks/{task_id}/history",
    response_model=SchedulerRunsResponse,
    summary="История запусков задачи",
    description=(
        "Задача и её запуски по убыванию времени: фаза (`prepare` — немедленное "
        "действие при регистрации, `tick` — запуск по расписанию), результат, "
        "длительность, детали и текст ошибки. `limit` ограничивает число записей."
    ),
)
def scheduler_history(task_id: int, limit: int = config.SCHEDULER_RUNS_LIMIT):
    service = dependencies.get_schedule_service()
    try:
        return service.task_history(task_id, limit=limit)
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc


@router.get(
    "/scheduler/tools",
    response_model=SchedulerToolsResponse,
    summary="Инструменты планировщика",
    description=(
        "Каталог трёх инструментов дня: `schedule_reminder` (разовое "
        "напоминание), `collect_data` (периодический сбор данных из внешнего API) "
        "и `generate_summary` (регулярная сводка по накопленным данным). У каждого — "
        "аргументы с типами и границами и подсказка о расписании."
    ),
)
def scheduler_tools():
    tools = dependencies.get_schedule_service().tools()
    return {"tools": tools, "count": len(tools)}


@router.get(
    "/scheduler/status",
    response_model=SchedulerStatusOut,
    summary="Состояние планировщика",
    description=(
        "Работает ли обслуживание таймеров, в каком часовом поясе идут расписания, "
        "сколько задач поставлено в APScheduler и как часто таблица задач "
        "сверяется с планировщиком."
    ),
)
def scheduler_status():
    return dependencies.get_schedule_service().scheduler.status()


# ---------- данные, которые накопили инструменты ----------
@router.get(
    "/scheduler/reminders",
    response_model=RemindersResponse,
    summary="Напоминания",
    description=(
        "Напоминания по возрастанию момента выдачи. `status` фильтрует по "
        "состоянию (`scheduled` — ждёт выдачи, `done` — выдано)."
    ),
)
def scheduler_reminders(status: Optional[str] = None,
                        limit: int = config.SCHEDULER_LIST_LIMIT):
    _check_reminder_state(status)
    return dependencies.get_schedule_service().reminders(status=status, limit=limit)


@router.get(
    "/scheduler/collected",
    response_model=CollectedResponse,
    summary="Накопленные записи сбора",
    description=(
        "Записи таблицы `collected_data` по возрастанию времени (свежие — "
        "последними): что вернул источник при каждом сборе инструмента "
        "`collect_data`. `name` фильтрует по имени сбора, `limit` ограничивает "
        "ответ, `total` показывает общее число записей с тем же фильтром."
    ),
)
def scheduler_collected(name: Optional[str] = None,
                        limit: int = config.SCHEDULER_LIST_LIMIT):
    return dependencies.get_schedule_service().collected(name=name, limit=limit)


@router.get(
    "/scheduler/summaries",
    response_model=SummariesResponse,
    summary="Регулярные сводки",
    description=(
        "Сводки инструмента `generate_summary` (свежие — первыми): текст, период "
        "(`period_start`…`period_end`), число записей за период и ключевые метрики "
        "(числовые поля — среднее, минимум и максимум; категориальные — сколько "
        "уникальных значений)."
    ),
)
def scheduler_summaries(name: Optional[str] = None,
                        limit: int = config.SCHEDULER_LIST_LIMIT):
    return dependencies.get_schedule_service().summaries(name=name, limit=limit)


# ---------- уведомления ----------
@router.get(
    "/scheduler/notifications",
    response_model=NotificationsResponse,
    summary="Уведомления планировщика",
    description=(
        "Очередь уведомлений (свежие — первыми): напоминание сработало, сводка "
        "готова, тик завершился ошибкой. Уведомления durable — их видно и после "
        "перезапуска страницы. `unread_only=true` отдаёт только непрочитанные, "
        "`unread` — их общее число."
    ),
)
def scheduler_notifications(unread_only: bool = False,
                            limit: int = config.SCHEDULER_LIST_LIMIT):
    return dependencies.get_schedule_service().notifications(
        unread_only=unread_only, limit=limit
    )


@router.post(
    "/scheduler/notifications/{notification_id}/read",
    response_model=NotificationOut,
    summary="Отметить уведомление прочитанным",
    description=(
        "Ставит отметку `read_at` и возвращает уведомление. Повторная отметка — "
        "безопасный no-op (не сдвигает время); неизвестное уведомление — 404."
    ),
)
def scheduler_notification_read(notification_id: int):
    service = dependencies.get_schedule_service()
    try:
        return service.mark_notification_read(notification_id)
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc


def _check_state(status: Optional[str]) -> None:
    """Проверяет фильтр состояния задачи (иначе список молча был бы пустым)."""
    if status is None:
        return
    allowed = {item.value for item in ScheduledTaskState}
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестное состояние задачи «{status}»; допустимы: "
                   + ", ".join(sorted(allowed)),
        )


def _check_reminder_state(status: Optional[str]) -> None:
    """Проверяет фильтр состояния напоминания."""
    if status is None:
        return
    allowed = {item.value for item in ReminderState}
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестное состояние напоминания «{status}»; допустимы: "
                   + ", ".join(sorted(allowed)),
        )


def _type_value(value) -> Optional[str]:
    """Значение типа расписания строкой (``Enum`` из схемы → строка для домена)."""
    return None if value is None else getattr(value, "value", str(value))
