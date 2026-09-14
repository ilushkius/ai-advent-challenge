"""FastAPI-приложение дня 11: агенты DeepSeek с тремя слоями памяти.

Запуск из папки day11/:  .venv/Scripts/python -m uvicorn backend.main:app --port 8000
Swagger-документация:  http://127.0.0.1:8000/docs

При старте (lifespan) создаются таблицы SQLite и агенты восстанавливаются из
базы вместе с диалогом активной сессии, рабочей и долговременной памятью.
День 11 добавляет к дню 10 явные слои памяти:

- POST /agents/{agent_id}/generate возвращает поле memory — разбивку контекста
  по слоям (краткосрочная/рабочая/долговременная) с токенами каждого слоя;
- POST /agents/{agent_id}/memory/session — новая сессия (краткосрочный слой
  очищается, рабочая и долговременная память остаются);
- PUT /agents/{agent_id}/memory/task — переключение активной задачи;
- CRUD слоёв: POST/GET/DELETE /memory/short-term, POST/GET /memory/working,
  POST/GET /memory/long-term, DELETE /memory/long-term/{entry_id}.

Контракт ошибок (как в день 6):
- 404 — неизвестный agent_id (и запись долговременной памяти у DELETE);
- 422 — невалидное тело запроса (Pydantic/FastAPI);
- 502 — сбой генерации: тело {status:"error", messages: <текущий диалог>, ...}
  без traceback.
"""
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, database
from .agent import AgentError
from .agent_manager import get_manager
from .models import (
    AgentConfig, AgentInfo, AgentPatch, AgentSummary, BranchCreateRequest,
    BranchListOut, CompareRequest, CompareResult, FactsOut, GenerateRequest,
    GenerateResponse, LongTermDeleteOut, LongTermEntryIn, LongTermEntryOut,
    LongTermMemoryOut, MessageOut, SessionOut, ShortTermClearOut,
    ShortTermMessageIn, ShortTermMessageOut, ShortTermOut, StrategiesOut,
    StrategySetRequest, SummarizeRequest, SummaryInfo, TaskOut, TaskSetRequest,
    UsageOut, UsageSummary, WorkingEntryIn, WorkingEntryOut, WorkingMemoryOut,
)


@asynccontextmanager
async def _lifespan(_app):
    """Старт приложения: создание таблиц + восстановление агентов с историей."""
    database.init_db()
    get_manager().restore_from_db()
    yield


app = FastAPI(
    title="Агенты DeepSeek с трёхслойной памятью — День 11",
    description=(
        "FastAPI-бэкенд веб-приложения: у каждого агента три явных слоя памяти "
        "в SQLite — краткосрочная (short_term_messages, привязана к сессии), "
        "рабочая (working_memory, привязана к задаче) и долговременная "
        "(long_term_memory: profile/preference/decision/knowledge). Контекст "
        "для DeepSeek собирает одна из четырёх стратегий дня 10: "
        "sliding_window, sticky_facts, branching или summary (сжатие дня 9). "
        "GET /agents/{id} отдаёт активные session_id и task_id."
    ),
    version="5.0.0",
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
        strategy=agent.strategy,
        window_size=agent.window_size,
        session_id=agent.session_id,
        task_id=agent.task_id,
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


# ---------- стратегии управления контекстом (день 11) ----------
@app.post(
    "/agents/{agent_id}/strategy",
    response_model=StrategiesOut,
    summary="Сменить стратегию управления контекстом",
    description=(
        "Меняет стратегию агента (sliding_window | sticky_facts | branching | "
        "summary) и, опционально, размер скользящего окна. Диалог не теряется."
    ),
)
def set_strategy(agent_id: str, body: StrategySetRequest):
    _agent_or_404(agent_id)
    manager = get_manager()
    manager.set_strategy(agent_id, body.strategy, window_size=body.window_size)
    return manager.get_strategy_state(agent_id)


@app.get(
    "/agents/{agent_id}/strategies",
    response_model=StrategiesOut,
    summary="Текущая стратегия и список доступных",
    description="Возвращает текущую стратегию агента, window_size и все доступные.",
)
def get_strategies(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_strategy_state(agent_id)


@app.post(
    "/agents/{agent_id}/branches",
    response_model=BranchListOut,
    summary="Создать ветку (чекпоинт)",
    description=(
        "Создаёт ветку. При checkpoint_id — ветка наследует снимок указанного "
        "чекпоинта; без него — снимок текущего состояния (от текущего сообщения). "
        "Новая ветка становится активной."
    ),
)
def create_branch(agent_id: str, body: BranchCreateRequest):
    _agent_or_404(agent_id)
    get_manager().create_branch(agent_id, body.checkpoint_id)
    return get_manager().list_branches(agent_id)


@app.get(
    "/agents/{agent_id}/branches",
    response_model=BranchListOut,
    summary="Дерево веток агента",
    description="Все чекпоинты/ветки агента с parent_id и флагом активной ветки.",
)
def list_branches(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().list_branches(agent_id)


@app.post(
    "/agents/{agent_id}/branches/{branch_id}/switch",
    response_model=BranchListOut,
    summary="Переключить активную ветку",
    description="Заменяет историю агента снимком выбранной ветки и делает её активной.",
)
def switch_branch(agent_id: str, branch_id: int):
    _agent_or_404(agent_id)
    get_manager().switch_branch(agent_id, branch_id)
    return get_manager().list_branches(agent_id)


@app.get(
    "/agents/{agent_id}/facts",
    response_model=FactsOut,
    summary="Факты агента (sticky_facts)",
    description="Текущие факты диалога «ключ → значение» с временем обновления.",
)
def get_facts(agent_id: str):
    _agent_or_404(agent_id)
    return get_manager().get_facts(agent_id)


# ---------- слои памяти (день 11) ----------
@app.post(
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
    agent = _agent_or_404(agent_id)
    session_id = body.session_id or agent.session_id
    return agent.memory.add_short_term(
        agent_id, session_id, body.role, body.content
    )


@app.get(
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
    _agent_or_404(agent_id)
    return get_manager().get_short_term(agent_id, session_id=session_id, limit=limit)


@app.delete(
    "/agents/{agent_id}/memory/short-term",
    response_model=ShortTermClearOut,
    summary="Очистить краткосрочную память",
    description=(
        "Удаляет реплики сессии (по умолчанию — текущей). Возвращает число "
        "удалённых; 0 — не ошибка. Рабочая и долговременная память не трогаются."
    ),
)
def clear_short_term(agent_id: str, session_id: Optional[str] = None):
    _agent_or_404(agent_id)
    return get_manager().clear_short_term(agent_id, session_id=session_id)


@app.post(
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
    agent = _agent_or_404(agent_id)
    return agent.add_working(body.key, body.value, task_id=body.task_id)


@app.get(
    "/agents/{agent_id}/memory/working",
    response_model=WorkingMemoryOut,
    summary="Записи рабочей памяти задачи",
    description=(
        "Записи активной (или указанной query-параметром task_id) задачи "
        "и список всех задач агента — для селектора в интерфейсе."
    ),
)
def get_working(agent_id: str, task_id: Optional[str] = None):
    _agent_or_404(agent_id)
    return get_manager().get_working(agent_id, task_id=task_id)


@app.post(
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
    _agent_or_404(agent_id)
    return get_manager().add_long_term(
        agent_id, body.category, body.key, body.value,
        confidence=body.confidence,
    )


@app.get(
    "/agents/{agent_id}/memory/long-term",
    response_model=LongTermMemoryOut,
    summary="Записи долговременной памяти",
    description=(
        "Все записи агента или только указанной категории, плюс список "
        "доступных категорий."
    ),
)
def get_long_term(agent_id: str, category: Optional[str] = None):
    _agent_or_404(agent_id)
    return get_manager().get_long_term(agent_id, category=category)


@app.delete(
    "/agents/{agent_id}/memory/long-term/{entry_id}",
    response_model=LongTermDeleteOut,
    summary="Удалить запись долговременной памяти",
    description="Удаляет запись по id; если записи нет — 404.",
)
def delete_long_term(agent_id: str, entry_id: int):
    _agent_or_404(agent_id)
    if not get_manager().delete_long_term(agent_id, entry_id):
        raise HTTPException(
            status_code=404, detail=f"Запись {entry_id} не найдена"
        )
    return {"status": "deleted", "agent_id": agent_id, "entry_id": entry_id}


@app.post(
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
    _agent_or_404(agent_id)
    return get_manager().new_session(agent_id)


@app.put(
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
    _agent_or_404(agent_id)
    try:
        return get_manager().set_task(agent_id, body.task_id)
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        "name": "Агенты DeepSeek с трёхслойной памятью — День 11",
        "docs": "/docs",
        "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
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
        ],
    }
