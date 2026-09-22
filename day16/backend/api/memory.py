"""Роутер API дня 16: три слоя памяти агента (short-term, working, long-term).

Эндпоинты перенесены из монолитного ``backend/main.py`` дословно (пути, тексты
описаний, коды ответов): изменений логики нет, добавлен только префикс
``@router.`` и обращение к менеджеру через ``backend.core.dependencies``.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core import config, dependencies
from ..agents.agent import AgentError
from ..schemas import (
    LongTermDeleteOut, LongTermEntryIn, LongTermEntryOut, LongTermMemoryOut,
    SessionOut, ShortTermClearOut, ShortTermMessageIn, ShortTermMessageOut,
    ShortTermOut, TaskOut, TaskSetRequest, WorkingEntryIn, WorkingEntryOut,
    WorkingMemoryOut,
)

router = APIRouter()


# ---------- слои памяти (день 11) ----------
@router.post(
    "/agents/{agent_id}/memory/short-term",
    response_model=ShortTermMessageOut,
    status_code=201,
    summary="Добавить реплику в краткосрочную память",
    description=(
        "Пишет реплику в краткосрочный слой указанной сессии (по умолчанию — "
        "текущей сессии агента). Возвращает запись с её id и created_at."
    ),
)
def add_short_term(agent_id: str, body: ShortTermMessageIn):
    agent = dependencies.agent_or_404(agent_id)
    session_id = body.session_id or agent.session_id
    return agent.memory.add_short_term(
        agent_id, session_id, body.role, body.content
    )


@router.get(
    "/agents/{agent_id}/memory/short-term",
    response_model=ShortTermOut,
    summary="Реплики краткосрочной памяти",
    description=(
        "Последние `limit` реплик сессии в хронологическом порядке "
        "(по умолчанию — текущей сессии агента; всего до 500)."
    ),
)
def get_short_term(
    agent_id: str,
    session_id: Optional[str] = None,
    limit: int = Query(config.SHORT_TERM_API_LIMIT, ge=1, le=500),
):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_short_term(agent_id, session_id=session_id, limit=limit)


@router.delete(
    "/agents/{agent_id}/memory/short-term",
    response_model=ShortTermClearOut,
    summary="Очистить краткосрочную память",
    description=(
        "Удаляет реплики сессии (по умолчанию — текущей). Возвращает число "
        "удалённых; 0 — не ошибка. Рабочая и долговременная память не трогаются."
    ),
)
def clear_short_term(agent_id: str, session_id: Optional[str] = None):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().clear_short_term(agent_id, session_id=session_id)


@router.post(
    "/agents/{agent_id}/memory/working",
    response_model=WorkingEntryOut,
    status_code=201,
    summary="Сохранить запись рабочей памяти",
    description=(
        "Upsert по (task_id, key): повторный POST с тем же ключом перезаписывает "
        "значение. task_id в теле не указан — используется активная задача."
    ),
)
def add_working(agent_id: str, body: WorkingEntryIn):
    agent = dependencies.agent_or_404(agent_id)
    return agent.add_working(body.key, body.value, task_id=body.task_id)


@router.get(
    "/agents/{agent_id}/memory/working",
    response_model=WorkingMemoryOut,
    summary="Записи рабочей памяти задачи",
    description=(
        "Записи активной (или указанной query-параметром task_id) задачи "
        "и список всех задач агента — для селектора в интерфейсе."
    ),
)
def get_working(agent_id: str, task_id: Optional[str] = None):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_working(agent_id, task_id=task_id)


@router.post(
    "/agents/{agent_id}/memory/long-term",
    response_model=LongTermEntryOut,
    status_code=201,
    summary="Сохранить запись долговременной памяти",
    description=(
        "Upsert по (category, key). Категории: profile, preference, decision, "
        "knowledge. Уверенность — 0..1 (по умолчанию 1.0)."
    ),
)
def add_long_term(agent_id: str, body: LongTermEntryIn):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().add_long_term(
        agent_id, body.category, body.key, body.value,
        confidence=body.confidence,
    )


@router.get(
    "/agents/{agent_id}/memory/long-term",
    response_model=LongTermMemoryOut,
    summary="Записи долговременной памяти",
    description=(
        "Все записи агента или только указанной категории, плюс список "
        "доступных категорий."
    ),
)
def get_long_term(agent_id: str, category: Optional[str] = None):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_long_term(agent_id, category=category)


@router.delete(
    "/agents/{agent_id}/memory/long-term/{entry_id}",
    response_model=LongTermDeleteOut,
    summary="Удалить запись долговременной памяти",
    description="Удаляет запись по id; если записи нет — 404.",
)
def delete_long_term(agent_id: str, entry_id: int):
    dependencies.agent_or_404(agent_id)
    if not dependencies.get_manager().delete_long_term(agent_id, entry_id):
        raise HTTPException(
            status_code=404, detail=f"Запись {entry_id} не найдена"
        )
    return {"status": "deleted", "agent_id": agent_id, "entry_id": entry_id}


@router.post(
    "/agents/{agent_id}/memory/session",
    response_model=SessionOut,
    summary="Начать новую сессию",
    description=(
        "Краткосрочный слой завершает текущую сессию: её реплики, конспекты и "
        "факты удаляются, у агента появляется новый session_id. Рабочая и "
        "долговременная память, ветки и метрики сохраняются."
    ),
)
def new_session(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().new_session(agent_id)


@router.put(
    "/agents/{agent_id}/memory/task",
    response_model=TaskOut,
    summary="Переключить активную задачу",
    description=(
        "Меняет активную задачу агента: рабочая память в следующих запросах "
        "фильтруется по новому task_id. Диалог и краткосрочный слой не "
        "затрагиваются."
    ),
)
def set_task(agent_id: str, body: TaskSetRequest):
    dependencies.agent_or_404(agent_id)
    try:
        return dependencies.get_manager().set_task(agent_id, body.task_id)
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
