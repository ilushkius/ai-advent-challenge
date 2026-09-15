"""Схемы API дня 12: сжатие истории, стратегии управления контекстом,
ветки и факты (sticky_facts).

Перенесено из монолитного ``backend/models.py`` без изменения полей.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from .. import config
from ..strategies import AVAILABLE_STRATEGIES


class CompressionInfo(BaseModel):
    """Сжатие в одном ходе: применён ли конспект и сколько токенов сэкономлено."""
    enabled: bool = config.DEFAULT_SUMMARY_ENABLED
    mode: str = "full"
    summary_used: bool = False
    summary_tokens: int = 0
    kept_messages: int = 0
    summarized_messages: int = 0
    covered_messages: int = 0
    full_context_tokens: int = 0
    sent_context_tokens: int = 0
    saved_tokens: int = 0
    saved_percent: float = 0.0
    error: Optional[str] = None


class ContextInfo(BaseModel):
    """Состояние контекста модели после хода (для индикатора в UI)."""
    max_model_tokens: int = 0
    payload_tokens: int = 0
    context_tokens: int = 0
    remaining_tokens: int = 0
    over_limit: bool = False
    trimmed_messages: int = 0
    warning: Optional[str] = None
    state: str = "idle"
    strategy: str = config.DEFAULT_STRATEGY
    compression: Optional[CompressionInfo] = None


class SummaryOut(BaseModel):
    """Одна запись таблицы summaries (история конспектов агента)."""
    id: int
    agent_id: str
    content: str
    covered_from_message_id: int
    covered_to_message_id: int
    covered_messages: int
    source_tokens: int
    summary_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cost: float
    created_at: datetime


class SummaryInfo(BaseModel):
    """Текущее состояние сжатия агента (GET /agents/{id}/summary).

    ``current`` — последний конспект (None, если диалог ещё не сжимался),
    ``uncovered_messages`` — сколько реплик ещё не покрыто конспектом,
    ``net_saved_tokens`` — экономия за вычетом стоимости вызовов суммаризации.
    """
    agent_id: str
    model: str
    enabled: bool = config.DEFAULT_SUMMARY_ENABLED
    keep_last_messages: int = config.DEFAULT_KEEP_LAST_MESSAGES
    summarize_every: int = config.DEFAULT_SUMMARIZE_EVERY
    state: str = "idle"
    message_count: int = 0
    summary_count: int = 0
    covered_messages: int = 0
    uncovered_messages: int = 0
    current: Optional[SummaryOut] = None
    history: List[SummaryOut] = Field(default_factory=list)
    total_source_tokens: int = 0
    total_summary_tokens: int = 0
    summary_cost: float = 0.0
    saved_tokens: int = 0
    net_saved_tokens: int = 0
    next_compression_in: int = 0


class SummarizeRequest(BaseModel):
    """Тело POST /agents/{agent_id}/summarize (принудительное сжатие)."""
    force: bool = Field(
        False,
        description=(
            "True — сжать всё, что выше keep_last_messages, даже если порог "
            "summarize_every ещё не набран (демо-кнопка «Сжать сейчас»)"
        ),
    )


class CompareRequest(BaseModel):
    """Тело POST /agents/{agent_id}/compare — сравнение режимов на одном промпте.

    ``call_api=False`` считает только токены (работает без ключа API);
    ``call_api=True`` делает два реальных вызова DeepSeek (со сжатием и без).
    История диалога не изменяется ни в одном режиме.
    """
    prompt: str = Field(..., min_length=1, max_length=16000)
    call_api: bool = False

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("промпт не может быть пустым")
        return value


class CompareSide(BaseModel):
    """Одна сторона сравнения: как собран контекст и что ответила модель."""
    mode: str  # "full" | "compressed"
    sent_context_tokens: int = 0
    full_context_tokens: int = 0
    summary_used: bool = False
    kept_messages: int = 0
    summarized_messages: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost: float = 0.0
    duration_sec: Optional[float] = None
    response: Optional[str] = None
    error: Optional[str] = None


class CompareResult(BaseModel):
    """Результат сравнения режимов (POST /agents/{id}/compare)."""
    agent_id: str
    prompt: str
    call_api: bool = False
    history_messages: int = 0
    full: CompareSide
    compressed: CompareSide
    saved_tokens: int = 0
    saved_percent: float = 0.0
    warning: Optional[str] = None


class StrategySetRequest(BaseModel):
    """Тело POST /agents/{agent_id}/strategy (смена стратегии и, опц., окна)."""
    strategy: str = Field(
        ...,
        description=(
            "Стратегия управления контекстом: sliding_window | sticky_facts | "
            "branching | summary"
        ),
    )
    window_size: Optional[int] = Field(
        default=None, ge=config.WINDOW_SIZE_MIN, le=config.WINDOW_SIZE_MAX,
        description="Размер скользящего окна (если не задан — сохраняется текущий)",
    )

    @field_validator("strategy")
    @classmethod
    def _strategy_known(cls, value: str) -> str:
        if value not in AVAILABLE_STRATEGIES:
            raise ValueError(
                f"неизвестная стратегия {value!r}; допустимые: "
                f"{', '.join(AVAILABLE_STRATEGIES)}"
            )
        return value


class StrategiesOut(BaseModel):
    """Текущая стратегия агента + список доступных (GET /agents/{id}/strategies)."""
    agent_id: str
    strategy: str = config.DEFAULT_STRATEGY
    window_size: int = config.DEFAULT_WINDOW_SIZE
    available: List[str] = Field(default_factory=lambda: list(AVAILABLE_STRATEGIES))


class BranchCreateRequest(BaseModel):
    """Тело POST /agents/{agent_id}/branches (создать ветку).

    ``checkpoint_id`` — от какого чекпоинта ответвляться. ``None``/пропущен —
    от текущего состояния (текущего сообщения): снимок текущей истории
    становится новой веткой.
    """
    checkpoint_id: Optional[int] = None


class BranchOut(BaseModel):
    """Одна ветка (чекпоинт) агента (список/дерево веток)."""
    id: int
    agent_id: str
    parent_id: Optional[int] = None
    message_count: int = 0
    created_at: datetime
    is_active: bool = False


class BranchListOut(BaseModel):
    """Дерево веток агента (GET /agents/{id}/branches)."""
    agent_id: str
    active_branch_id: Optional[int] = None
    branches: List[BranchOut] = Field(default_factory=list)


class FactOut(BaseModel):
    """Один факт диалога «ключ → значение» (стратегия sticky_facts)."""
    key: str
    value: str
    updated_at: datetime


class FactsOut(BaseModel):
    """Текущие факты агента (GET /agents/{id}/facts)."""
    agent_id: str
    facts: List[FactOut] = Field(default_factory=list)
