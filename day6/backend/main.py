"""FastAPI-приложение дня 6: эндпоинты управления агентами DeepSeek.

Запуск из папки day6/:  .venv/Scripts/python -m uvicorn backend.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

Контракт ошибок (см. design.md D7 и docs/api.md):
- 404 — неизвестный agent_id;
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации: тело {status:"error", message/error, ...} без traceback.
"""
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent_manager import get_manager
from .models import (
    AgentConfig, AgentInfo, AgentSummary, GenerateRequest, HistoryEntry,
)

app = FastAPI(
    title="Менеджер агентов DeepSeek — День 6",
    description=(
        "FastAPI-бэкенд веб-приложения управления агентами: каждый агент — "
        "сущность со своей конфигурацией (модель, температура, системный "
        "промпт, max_tokens), историей запросов и вызовом DeepSeek. "
        "Единый менеджер-синглтон хранит всех агентов в памяти процесса."
    ),
    version="1.0.0",
)

# CORS для браузерных клиентов Streamlit (серверный `requests` CORS не требует,
# но middleware дёшев и полезен для Swagger/будущих клиентов).
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
    return AgentSummary(agent_id=agent.agent_id, name=agent.name, model=agent.model)


def _to_info(agent) -> AgentInfo:
    return AgentInfo(
        agent_id=agent.agent_id,
        name=agent.name,
        model=agent.model,
        temperature=agent.config.temperature,
        system_prompt=agent.config.system_prompt,
        max_tokens=agent.config.max_tokens,
        created_at=agent.created_at,
        history_count=len(agent.history),
    )


# ---------- CRUD агентов ----------
@app.post(
    "/agents",
    response_model=AgentInfo,
    status_code=201,
    summary="Создать агента",
    description="Создаёт агента с указанной конфигурацией и возвращает его id и параметры.",
)
def create_agent(payload: AgentConfig):
    agent_id = get_manager().create_agent(payload)
    return _to_info(get_manager().require_agent(agent_id))


@app.get(
    "/agents",
    response_model=List[AgentSummary],
    summary="Список агентов",
    description="Возвращает всех созданных агентов (id, имя, модель).",
)
def list_agents():
    return [_to_summary(a) for a in get_manager().list_agents()]


@app.get(
    "/agents/{agent_id}",
    response_model=AgentInfo,
    summary="Информация об агенте",
    description="Полная конфигурация агента + дата создания и число записей истории.",
)
def get_agent(agent_id: str):
    return _to_info(_agent_or_404(agent_id))


@app.delete(
    "/agents/{agent_id}",
    summary="Удалить агента",
    description="Удаляет агента вместе с его историей запросов.",
)
def delete_agent(agent_id: str):
    if not get_manager().remove_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Агент {agent_id} не найден")
    return {"status": "deleted", "agent_id": agent_id}


# ---------- генерация и история ----------
@app.post(
    "/agents/{agent_id}/generate",
    response_model=HistoryEntry,
    summary="Отправить запрос агенту",
    description=(
        "Отправляет промпт в DeepSeek с конфигурацией агента. При успехе — "
        "текст ответа, время, токены и finish_reason. При сбое (включая "
        "отсутствие ключа) — HTTP 502 с телом {status:\"error\", ...}."
    ),
)
def generate(agent_id: str, body: GenerateRequest):
    agent = _agent_or_404(agent_id)
    record = agent.generate(body.prompt)  # всегда возвращает структурированную запись
    if record["status"] == "ok":
        return record
    # Сбой генерации: структурированная ошибка без traceback (контракт D7).
    # jsonable_encoder нужен: в record лежит datetime (timestamp).
    return JSONResponse(status_code=502, content=jsonable_encoder(record))


@app.get(
    "/agents/{agent_id}/history",
    response_model=List[HistoryEntry],
    summary="История запросов агента",
    description="Все попытки агента (успех и ошибки), новые — первыми.",
)
def get_history(agent_id: str):
    agent = _agent_or_404(agent_id)
    return agent.history


# Корневая точка — подсказка по запуску/документации.
@app.get("/", summary="О приложении")
def root():
    return {
        "name": "Менеджер агентов DeepSeek — День 6",
        "docs": "/docs",
        "endpoints": ["POST /agents", "GET /agents", "GET /agents/{agent_id}",
                      "DELETE /agents/{agent_id}",
                      "POST /agents/{agent_id}/generate",
                      "GET /agents/{agent_id}/history"],
    }
