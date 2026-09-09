"""FastAPI-приложение дня 8: агенты с памятью и контролем токенов.

Запуск из папки day8/:  .venv/Scripts/python -m uvicorn backend.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с историей диалогов. День 8 добавляет к дню 7 контроль токенов:
- POST generate возвращает метрики токенов хода (token_metrics) и состояние
  контекста (context: лимит, занятость, остаток, автообрезка при переполнении);
- GET /agents/{agent_id}/usage — сводка токенов агента (агрегаты token_usage +
  занятость контекста);
- GET /agents/{agent_id}/usage/graph — записи token_usage для таблицы/графика.

Контракт ошибок (как в день 6):
- 404 — неизвестный agent_id;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации: тело {status:"error", messages: <текущий диалог>, ...}
  без traceback.
"""
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import database
from .agent_manager import get_manager
from .models import (
    AgentConfig, AgentInfo, AgentSummary, GenerateRequest, GenerateResponse,
    MessageOut, UsageOut, UsageSummary,
)


@asynccontextmanager
async def _lifespan(_app):
    """Старт приложения: создание таблиц + восстановление агентов с историей."""
    database.init_db()
    get_manager().restore_from_db()
    yield


app = FastAPI(
    title="Агенты DeepSeek с памятью — День 8",
    description=(
        "FastAPI-бэкенд веб-приложения: каждый агент ведёт диалог, который "
        "сохраняется в SQLite (таблицы agents и messages) и целиком передаётся "
        "в DeepSeek при генерации. Диалоги переживают перезапуск сервера."
    ),
    version="2.0.0",
    lifespan=_lifespan,
)

# CORS для браузерных клиентов Streamlit (серверный `requests` CORS не требует).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- помощники ----------
def _agent_or_404(agent_id: str):
    """Возвращает агента или бросает HTTPException(404) с понятным текстом."""
    agent = get_manager().get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Агент {agent_id} не найден")
    return agent


def _to_summary(agent) -> AgentSummary:
    return AgentSummary(
        agent_id=agent.agent_id,
        name=agent.name,
        model=agent.model,
        message_count=agent.message_count,
    )


def _to_info(agent) -> AgentInfo:
    return AgentInfo(
        agent_id=agent.agent_id,
        name=agent.name,
        model=agent.model,
        message_count=agent.message_count,
        temperature=agent.config.temperature,
        system_prompt=agent.config.system_prompt,
        max_tokens=agent.config.max_tokens,
        created_at=agent.created_at,
    )


def _with_history(record: dict) -> dict:
    """Добавляет в запись-результат актуальный диалог агента (после попытки)."""
    record["messages"] = get_manager().get_agent_history(record["agent_id"])
    return record

# ---------- CRUD агентов ----------
@app.post(
    "/agents",
    response_model=AgentInfo,
    status_code=201,
    summary="Создать агента",
    description="Создаёт агента (конфигурация сохраняется в SQLite) и возвращает id, параметры и message_count.",
)
def create_agent(payload: AgentConfig):
    agent_id = get_manager().create_agent(payload)
    return _to_info(get_manager().require_agent(agent_id))


@app.get(
    "/agents",
    response_model=List[AgentSummary],
    summary="Список агентов",
    description="Все агенты с числом сообщений (id, имя, модель, message_count).",
)
def list_agents():
    return [_to_summary(a) for a in get_manager().list_agents()]


@app.get(
    "/agents/{agent_id}",
    response_model=AgentInfo,
    summary="Информация об агенте",
    description="Полная конфигурация агента + дата создания и число сообщений.",
)
def get_agent(agent_id: str):
    return _to_info(_agent_or_404(agent_id))


@app.delete(
    "/agents/{agent_id}",
    summary="Удалить агента",
    description="Удаляет агента вместе с его диалогом из БД.",
)
def delete_agent(agent_id: str):
    if not get_manager().remove_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Агент {agent_id} не найден")
    return {"status": "deleted", "agent_id": agent_id}


# ---------- генерация, диалог, очистка истории ----------
@app.post(
    "/agents/{agent_id}/generate",
    response_model=GenerateResponse,
    summary="Отправить запрос агенту",
    description=(
        "Добавляет сообщение пользователя в диалог, отправляет ВСЮ историю в "
        "DeepSeek, добавляет ответ ассистента и сохраняет в SQLite. Ответ — "
        "текст, метрики и обновлённая история messages. При сбое — 502 со "
        "status:error и неизменной историей."
    ),
)
def generate(agent_id: str, body: GenerateRequest):
    agent = _agent_or_404(agent_id)
    record = get_manager().generate_response(agent_id, body.prompt)
    record = _with_history(record)  # актуальный диалог после попытки
    if record["status"] == "ok":
        return record
    # Сбой генерации: структурированная ошибка без traceback (контракт дня 6).
    return JSONResponse(status_code=502, content=jsonable_encoder(record))


@app.get(
    "/agents/{agent_id}/history",
    response_model=List[MessageOut],
    summary="Диалог агента",
    description="Все сообщения диалога агента в хронологическом порядке.",
)
def get_history(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_agent_history(agent_id)


@app.delete(
    "/agents/{agent_id}/history",
    summary="Очистить историю агента",
    description=(
        "Удаляет все сообщения диалога агента из SQLite и памяти. Конфигурация "
        "агента не изменяется — дальнейший диалог начинается с пустой истории."
    ),
)
def clear_history(agent_id: str):
    _agent_or_404(agent_id)
    get_manager().clear_agent_history(agent_id)
    return {"status": "cleared", "agent_id": agent_id, "message_count": 0}


# ---------- статистика токенов (день 8) ----------
@app.get(
    "/agents/{agent_id}/usage",
    response_model=UsageSummary,
    summary="Сводка токенов агента",
    description=(
        "Агрегаты по таблице token_usage (число запросов, суммы prompt/completion/"
        "total токенов, общая стоимость, время последней записи) + оценка "
        "занятости контекста агента (лимит модели, текущая история, остаток)."
    ),
)
def get_usage(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_usage_summary(agent_id)


@app.get(
    "/agents/{agent_id}/usage/graph",
    response_model=List[UsageOut],
    summary="Данные для графика токенов",
    description=(
        "Записи token_usage агента в хронологическом порядке — для таблицы и "
        "графика роста токенов в интерфейсе."
    ),
)
def get_usage_graph(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_usage_rows(agent_id)


# Корневая точка — подсказка по запуску/документации.
@app.get("/", summary="О приложении")
def root():
    return {
        "name": "Агенты DeepSeek с памятью — День 8",
        "docs": "/docs",
        "endpoints": ["POST /agents", "GET /agents", "GET /agents/{agent_id}",
                      "DELETE /agents/{agent_id}",
                      "POST /agents/{agent_id}/generate",
                      "GET /agents/{agent_id}/history",
                      "DELETE /agents/{agent_id}/history",
                      "GET /agents/{agent_id}/usage",
                      "GET /agents/{agent_id}/usage/graph"],
    }

