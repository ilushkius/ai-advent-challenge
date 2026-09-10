"""FastAPI-приложение дня 9: агенты со сжатием истории и контролем токенов.

Запуск из папки day9/:  .venv/Scripts/python -m uvicorn backend.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с историей и конспектами. День 9 добавляет к дню 8 сжатие истории:
- POST /agents/{agent_id}/generate возвращает блок context.compression
  (применён ли конспект, сколько токенов сэкономлено);
- POST /agents/{agent_id}/summarize — принудительное сжатие («Сжать сейчас»);
- POST /agents/{agent_id}/compare — сравнение режимов «полная история» и
  «конспект + последние N» на одном промпте (с реальными вызовами или без);
- GET /agents/{agent_id}/summary — конспект, watermark и экономика;
- PATCH /agents/{agent_id} — переключение сжатия на живом агенте.

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
    AgentConfig, AgentInfo, AgentPatch, AgentSummary, CompareRequest,
    CompareResult, GenerateRequest, GenerateResponse, MessageOut, SummarizeRequest,
    SummaryInfo, UsageOut, UsageSummary,
)


@asynccontextmanager
async def _lifespan(_app):
    """Старт приложения: создание таблиц + восстановление агентов с историей."""
    database.init_db()
    get_manager().restore_from_db()
    yield


app = FastAPI(
    title="Агенты DeepSeek со сжатием истории — День 9",
    description=(
        "FastAPI-бэкенд веб-приложения: каждый агент ведёт диалог в SQLite "
        "(таблицы agents, messages, summaries, token_usage), отправляет в "
        "DeepSeek конспект старых реплик вместо полной истории и считает "
        "сэкономленные токены."
    ),
    version="3.0.0",
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
        summary_enabled=agent.config.summary_enabled,
        keep_last_messages=agent.config.keep_last_messages,
        summarize_every=agent.config.summarize_every,
        summary_count=len(agent.compressor.history()),
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
    record["messages"] = get_manager().get_agent_history(record["agent_id"])
    return record


# ---------- CRUD агентов ----------
@app.post(
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
    agent_id = get_manager().create_agent(payload)
    return _to_info(get_manager().require_agent(agent_id))


@app.get(
    "/agents",
    response_model=List[AgentSummary],
    summary="Список агентов",
    description="Все агенты с числом сообщений и настройками сжатия.",
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


@app.patch(
    "/agents/{agent_id}",
    response_model=AgentInfo,
    summary="Изменить агента",
    description=(
        "Частичное обновление: можно переключить сжатие или изменить "
        "keep_last_messages/summarize_every на живом агенте, не теряя диалог."
    ),
)
def patch_agent(agent_id: str, body: AgentPatch):
    _agent_or_404(agent_id)
    agent = get_manager().patch_agent(agent_id, body)
    return _to_info(agent)


@app.delete(
    "/agents/{agent_id}",
    summary="Удалить агента",
    description="Удаляет агента вместе с диалогом, конспектами и метриками.",
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
        "Собирает контекст (конспект + последние N реплик), отправляет его в "
        "DeepSeek и сохраняет пару реплик вместе с метриками (в том числе "
        "экономией токенов) в SQLite. При сбое — 502 со status:error и "
        "неизменной историей."
    ),
)
def generate(agent_id: str, body: GenerateRequest):
    _agent_or_404(agent_id)
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
    description=(
        "Все сообщения диалога агента в хронологическом порядке. Поле "
        "summarized отмечает реплики, покрытые конспектом (они не уходят в "
        "следующий запрос, но остаются в истории)."
    ),
)
def get_history(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_agent_history(agent_id)


@app.delete(
    "/agents/{agent_id}/history",
    summary="Очистить историю агента",
    description=(
        "Удаляет сообщения, конспекты и метрики агента из SQLite. "
        "Конфигурация агента не изменяется."
    ),
)
def clear_history(agent_id: str):
    _agent_or_404(agent_id)
    get_manager().clear_agent_history(agent_id)
    return {"status": "cleared", "agent_id": agent_id, "message_count": 0}


# ---------- сжатие истории (день 9) ----------
@app.post(
    "/agents/{agent_id}/summarize",
    summary="Сжать историю сейчас",
    description=(
        "Принудительное сжатие: старые реплики (всё выше keep_last_messages) "
        "уходят в конспект. Без force=True срабатывает только при набранном "
        "пороге summarize_every — иначе возвращается created:false с причиной."
    ),
)
def summarize(agent_id: str, body: SummarizeRequest):
    _agent_or_404(agent_id)
    return get_manager().force_summarize(agent_id, force=body.force)


@app.get(
    "/agents/{agent_id}/summary",
    response_model=SummaryInfo,
    summary="Состояние сжатия агента",
    description=(
        "Текущий конспект, watermark (сколько реплик покрыто), история "
        "конспектов и экономика: сэкономленные токены за вычетом стоимости "
        "вызовов суммаризации."
    ),
)
def get_summary(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_summary(agent_id)


@app.post(
    "/agents/{agent_id}/compare",
    response_model=CompareResult,
    summary="Сравнить режимы без сжатия и со сжатием",
    description=(
        "Считает токены обоих вариантов контекста для одного промпта; при "
        "call_api=true делает два реальных вызова DeepSeek и возвращает оба "
        "ответа. История диалога не изменяется."
    ),
)
def compare(agent_id: str, body: CompareRequest):
    _agent_or_404(agent_id)
    return get_manager().compare_modes(
        agent_id, body.prompt, call_api=body.call_api
    )


# ---------- статистика токенов ----------
@app.get(
    "/agents/{agent_id}/usage",
    response_model=UsageSummary,
    summary="Сводка токенов агента",
    description=(
        "Агрегаты по таблице token_usage (запросы, суммы токенов, стоимость) + "
        "занятость контекста + экономия от сжатия (saved/net_saved токены)."
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
        "графика роста токенов и экономии в интерфейсе."
    ),
)
def get_usage_graph(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_usage_rows(agent_id)


# Корневая точка — подсказка по запуску/документации.
@app.get("/", summary="О приложении")
def root():
    return {
        "name": "Агенты DeepSeek со сжатием истории — День 9",
        "docs": "/docs",
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
        ],
    }
