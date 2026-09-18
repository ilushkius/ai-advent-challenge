"""Роутер API дня 15: CRUD агентов, генерация, диалог и статистика токенов.

Эндпоинты перенесены из монолитного ``backend/main.py`` дословно (пути, тексты
описаний, коды ответов): изменений логики нет, добавлен только префикс
``@router.`` и обращение к менеджеру через ``backend.core.dependencies``.

Корневая точка ``GET /`` — подсказка по запуску: перечисляет группы эндпоинтов,
включая инварианты дня 14 (``/invariants...``, см. ``backend/api/invariants.py``).
"""
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..core import dependencies
from ..schemas import (
    AgentConfig, AgentInfo, AgentPatch, AgentSummary, GenerateRequest,
    GenerateResponse, MessageOut, UsageOut, UsageSummary,
)

router = APIRouter()


def _to_summary(agent) -> AgentSummary:
    return AgentSummary(
        agent_id=agent.agent_id,
        name=agent.name,
        model=agent.model,
        message_count=agent.message_count,
        summary_enabled=agent.config.summary_enabled,
        keep_last_messages=agent.config.keep_last_messages,
        summarize_every=agent.config.summarize_every,
        summary_count=len(agent.compressor.history()),
        strategy=agent.strategy,
        window_size=agent.window_size,
        session_id=agent.session_id,
        task_id=agent.task_id,
        user_id=agent.user_id,
    )


def _to_info(agent) -> AgentInfo:
    base = _to_summary(agent)
    return AgentInfo(
        **base.model_dump(),
        temperature=agent.config.temperature,
        system_prompt=agent.config.system_prompt,
        max_tokens=agent.config.max_tokens,
        created_at=agent.created_at,
    )


def _with_history(record: dict) -> dict:
    """Добавляет в запись-результат актуальный диалог агента (после попытки)."""
    record["messages"] = dependencies.get_manager().get_agent_history(record["agent_id"])
    return record


# ---------- CRUD агентов ----------
@router.post(
    "/agents",
    response_model=AgentInfo,
    status_code=201,
    summary="Создать агента",
    description=(
        "Создаёт агента (конфигурация и настройки сжатия сохраняются в SQLite) "
        "и возвращает id, параметры и message_count."
    ),
)
def create_agent(payload: AgentConfig):
    agent_id = dependencies.get_manager().create_agent(payload)
    return _to_info(dependencies.get_manager().require_agent(agent_id))


@router.get(
    "/agents",
    response_model=List[AgentSummary],
    summary="Список агентов",
    description="Все агенты с числом сообщений и настройками сжатия.",
)
def list_agents():
    return [_to_summary(a) for a in dependencies.get_manager().list_agents()]


@router.get(
    "/agents/{agent_id}",
    response_model=AgentInfo,
    summary="Информация об агенте",
    description="Полная конфигурация агента + дата создания и число сообщений.",
)
def get_agent(agent_id: str):
    return _to_info(dependencies.agent_or_404(agent_id))


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentInfo,
    summary="Изменить агента",
    description=(
        "Частичное обновление: можно переключить сжатие или изменить "
        "keep_last_messages/summarize_every на живом агенте, не теряя диалог."
    ),
)
def patch_agent(agent_id: str, body: AgentPatch):
    dependencies.agent_or_404(agent_id)
    agent = dependencies.get_manager().patch_agent(agent_id, body)
    return _to_info(agent)


@router.delete(
    "/agents/{agent_id}",
    summary="Удалить агента",
    description="Удаляет агента вместе с диалогом, конспектами и метриками.",
)
def delete_agent(agent_id: str):
    if not dependencies.get_manager().remove_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Агент {agent_id} не найден")
    return {"status": "deleted", "agent_id": agent_id}


# ---------- генерация, диалог, очистка истории ----------
@router.post(
    "/agents/{agent_id}/generate",
    response_model=GenerateResponse,
    summary="Отправить запрос агенту",
    description=(
        "Собирает контекст (системное сообщение с профилем пользователя, "
        "конспект + последние N реплик), отправляет его в DeepSeek и сохраняет "
        "пару реплик вместе с метриками (в том числе экономией токенов) в "
        "SQLite. Поля ответа profile и system_prompt показывают, какой профиль "
        "применён и что он добавил в промпт. При сбое — 502 со status:error и "
        "неизменной историей."
    ),
)
def generate(agent_id: str, body: GenerateRequest):
    dependencies.agent_or_404(agent_id)
    record = dependencies.get_manager().generate_response(agent_id, body.prompt)
    record = _with_history(record)  # актуальный диалог после попытки
    if record["status"] == "ok":
        return record
    # Сбой генерации: структурированная ошибка без traceback (контракт дня 6).
    return JSONResponse(status_code=502, content=jsonable_encoder(record))


@router.get(
    "/agents/{agent_id}/history",
    response_model=List[MessageOut],
    summary="Диалог агента",
    description=(
        "Все сообщения диалога агента в хронологическом порядке. Поле "
        "summarized отмечает реплики, покрытые конспектом (они не уходят в "
        "следующий запрос, но остаются в истории)."
    ),
)
def get_history(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_agent_history(agent_id)


@router.delete(
    "/agents/{agent_id}/history",
    summary="Очистить историю агента",
    description=(
        "Удаляет сообщения, конспекты и метрики агента из SQLite. "
        "Конфигурация агента не изменяется."
    ),
)
def clear_history(agent_id: str):
    dependencies.agent_or_404(agent_id)
    dependencies.get_manager().clear_agent_history(agent_id)
    return {"status": "cleared", "agent_id": agent_id, "message_count": 0}


# ---------- статистика токенов ----------
@router.get(
    "/agents/{agent_id}/usage",
    response_model=UsageSummary,
    summary="Сводка токенов агента",
    description=(
        "Агрегаты по таблице token_usage (запросы, суммы токенов, стоимость) + "
        "занятость контекста + экономия от сжатия (saved/net_saved токены)."
    ),
)
def get_usage(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_usage_summary(agent_id)


@router.get(
    "/agents/{agent_id}/usage/graph",
    response_model=List[UsageOut],
    summary="Данные для графика токенов",
    description=(
        "Записи token_usage агента в хронологическом порядке — для таблицы и "
        "графика роста токенов и экономии в интерфейсе."
    ),
)
def get_usage_graph(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_usage_rows(agent_id)


# Корневая точка — подсказка по запуску/документации.
@router.get("/", summary="О приложении")
def root():
    return {
        "name": "Агенты DeepSeek с контролируемыми переходами — День 15",
        "docs": "/docs",
        "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
        "personalization": "/users, /users/{user_id}/profile, /agents/{agent_id}/profile",
        "tasks": "/agents/{agent_id}/tasks, /tasks/{task_id}/state, ... (11 эндпоинтов)",
        "task_transitions": "/tasks/{task_id}/transition, /tasks/{task_id}/allowed-next, /tasks/{task_id}/context",
        "invariants": "/invariants, /invariants/{invariant_id}, /invariants/check (6 эндпоинтов)",
        "endpoints": [
            "POST /agents", "GET /agents", "GET /agents/{agent_id}",
            "PATCH /agents/{agent_id}", "DELETE /agents/{agent_id}",
            "POST /agents/{agent_id}/generate",
            "GET /agents/{agent_id}/history",
            "DELETE /agents/{agent_id}/history",
            "POST /agents/{agent_id}/summarize",
            "GET /agents/{agent_id}/summary",
            "POST /agents/{agent_id}/compare",
            "GET /agents/{agent_id}/usage",
            "GET /agents/{agent_id}/usage/graph",
            "POST /agents/{agent_id}/strategy",
            "GET /agents/{agent_id}/strategies",
            "POST /agents/{agent_id}/branches",
            "GET /agents/{agent_id}/branches",
            "POST /agents/{agent_id}/branches/{branch_id}/switch",
            "GET /agents/{agent_id}/facts",
            "POST /agents/{agent_id}/memory/short-term",
            "GET /agents/{agent_id}/memory/short-term",
            "DELETE /agents/{agent_id}/memory/short-term",
            "POST /agents/{agent_id}/memory/working",
            "GET /agents/{agent_id}/memory/working",
            "POST /agents/{agent_id}/memory/long-term",
            "GET /agents/{agent_id}/memory/long-term",
            "DELETE /agents/{agent_id}/memory/long-term/{entry_id}",
            "POST /agents/{agent_id}/memory/session",
            "PUT /agents/{agent_id}/memory/task",
            "GET /users",
            "GET /users/{user_id}/profile",
            "POST /users/{user_id}/profile",
            "PUT /users/{user_id}/profile",
            "DELETE /users/{user_id}/profile",
            "GET /agents/{agent_id}/profile",
            "POST /agents/{agent_id}/tasks",
            "GET /agents/{agent_id}/tasks",
            "GET /tasks/{task_id}/state",
            "GET /tasks/{task_id}/history",
            "GET /tasks/{task_id}/allowed-next",
            "PATCH /tasks/{task_id}/context",
            "POST /tasks/{task_id}/pause",
            "POST /tasks/{task_id}/resume",
            "POST /tasks/{task_id}/advance",
            "POST /tasks/{task_id}/rollback",
            "POST /tasks/{task_id}/transition",
            "POST /invariants",
            "GET /invariants",
            "GET /invariants/{invariant_id}",
            "PUT /invariants/{invariant_id}",
            "DELETE /invariants/{invariant_id}",
            "POST /invariants/check",
        ],
    }
