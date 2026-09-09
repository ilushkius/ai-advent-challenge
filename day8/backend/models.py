"""Pydantic-схемы API дня 8 (единое место моделей — конвенция дня 6).

Здесь описаны тела запросов/ответов эндпоинтов FastAPI. Отличие от дня 6:
история агента — это диалог (``MessageOut``), а не записи-попытки; поэтому у
агента ``message_count`` (вместо ``history_count``), а ``GenerateResponse``
содержит обновлённую историю ``messages``. День 8 добавляет схемы метрик
токенов: ``TokenMetrics`` и ``ContextInfo`` в ответе генерации, а также
``UsageOut``/``UsageSummary`` для эндпоинтов ``/usage`` и ``/usage/graph``.
"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from . import config


class AgentConfig(BaseModel):
    """Конфигурация нового агента (тело POST /agents).

    model по умолчанию — deepseek-chat; deepseek-reasoner допустима, но может
    игнорировать temperature (поведение провайдера, см. docs/api.md).
    """
    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Человекочитаемое имя агента",
    )
    model: str = Field(
        config.DEFAULT_MODEL, min_length=1, max_length=100,
        description="Модель DeepSeek (deepseek-chat | deepseek-reasoner)",
    )
    temperature: float = Field(
        config.DEFAULT_TEMPERATURE, ge=config.TEMPERATURE_MIN,
        le=config.TEMPERATURE_MAX, description="Температура генерации 0.0–2.0",
    )
    system_prompt: str = Field(
        default="", max_length=4000,
        description="Системный промпт (роль) агента; пустой — без system-сообщения",
    )
    max_tokens: int = Field(
        config.DEFAULT_MAX_TOKENS, ge=config.MAX_TOKENS_MIN,
        le=config.MAX_TOKENS_MAX,
        description="Максимум токенов в ответе (1–8192)",
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустое/пробельное имя."""
        value = value.strip()
        if not value:
            raise ValueError("имя агента не может быть пустым")
        return value


class AgentSummary(BaseModel):
    """Короткая запись об агенте для списка GET /agents.

    message_count — число реплик диалога: фронтенд показывает счётчики в
    боковой панели без отдельных запросов к истории каждого агента.
    """
    agent_id: str
    name: str
    model: str
    message_count: int = 0


class AgentInfo(AgentSummary):
    """Полная информация об агенте (GET /agents/{agent_id}, ответ на создание)."""
    temperature: float
    system_prompt: str
    max_tokens: int
    created_at: datetime


class GenerateRequest(BaseModel):
    """Тело POST /agents/{agent_id}/generate."""
    prompt: str = Field(
        ..., min_length=1, max_length=16000,
        description="Текст запроса к агенту",
    )

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустой/пробельный промпт."""
        value = value.strip()
        if not value:
            raise ValueError("промпт не может быть пустым")
        return value


class MessageOut(BaseModel):
    """Одно сообщение диалога агента (GET history и поле messages в ответе)."""
    id: int
    agent_id: str
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime


class TokenMetrics(BaseModel):
    """Метрики токенов одного хода диалога (поля таблицы token_usage).

    Числа запроса/ответа (prompt/completion/total) — из usage API при наличии,
    иначе локальные оценки tiktoken; history_tokens/response_tokens — оценки
    (см. design.md, D3). cost — приблизительная стоимость в долларах.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    history_tokens: int = 0
    response_tokens: int = 0
    cost: float = 0.0


class ContextInfo(BaseModel):
    """Состояние контекста модели после хода (для индикатора в UI).

    context_tokens — оценка «занятости» контекста (системный промпт + вся
    история диалога после ответа); remaining_tokens — остаток до лимита.
    over_limit/trimmed_messages/warning описывают автообрезку при переполнении.
    """

    max_model_tokens: int = 0
    payload_tokens: int = 0
    context_tokens: int = 0
    remaining_tokens: int = 0
    over_limit: bool = False
    trimmed_messages: int = 0
    warning: Optional[str] = None


class UsageOut(BaseModel):
    """Одна запись token_usage (GET /agents/{agent_id}/usage/graph)."""

    id: int
    agent_id: str
    timestamp: datetime
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    history_tokens: int
    response_tokens: int
    cost: float


class UsageSummary(BaseModel):
    """Сводка токенов агента (GET /agents/{agent_id}/usage).

    Агрегаты по таблице token_usage + оценка текущей занятости контекста
    агента (для индикатора в интерфейсе).
    """

    agent_id: str
    model: str
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_usage_at: Optional[datetime] = None
    context_limit_tokens: int = 0
    current_history_tokens: int = 0
    remaining_tokens: int = 0


class GenerateResponse(BaseModel):
    """Результат генерации: метаданные попытки + обновлённая история.

    Поля response/error взаимоисключающие: при status="ok" заполнен response,
    при status="error" — error. messages — актуальный диалог агента ПОСЛЕ
    попытки (при сбое — неизменная история): фронтенд перерисовывает чат из
    этого списка. День 8: при status="ok" заполнены token_metrics (метрики
    хода, сохранённые в token_usage) и context (лимит/остаток/обрезка); при
    ошибке оба поля None.
    """
    agent_id: str
    status: str  # "ok" | "error"
    prompt: str
    response: Optional[str] = None
    error: Optional[str] = None
    model: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None  # prompt/completion/total_tokens
    token_metrics: Optional[TokenMetrics] = None
    context: Optional[ContextInfo] = None
    duration_sec: Optional[float] = None
    timestamp: datetime
    messages: List[MessageOut] = Field(default_factory=list)
