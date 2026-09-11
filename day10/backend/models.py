"""Pydantic-схемы API дня 9 (единое место моделей — конвенция дня 6).

День 9 развивает день 8: агент умеет сжимать историю, поэтому к схемам
добавлены настройки сжатия в ``AgentConfig``/``AgentInfo``, блок ``Compression``
в ответе генерации (конспект, экономия токенов), схемы сводки по конспектам
(``SummaryOut``, ``SummaryInfo``) и тел запросов ``SummarizeRequest`` /
``CompareRequest``.
"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from . import config
from .strategies import AVAILABLE_STRATEGIES


class AgentConfig(BaseModel):
    """Конфигурация нового агента (тело POST /agents).

    model по умолчанию — deepseek-chat; deepseek-reasoner допустима, но может
    игнорировать temperature (поведение провайдера, см. docs/api.md).
    Сжатие истории: ``summary_enabled`` включает конспект вместо старых реплик,
    ``keep_last_messages`` — сколько последних реплик всегда уходят «как есть»,
    ``summarize_every`` — порог: конспектируем, когда непокрытых реплик
    накопилось не меньше этого числа.
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
    summary_enabled: bool = Field(
        config.DEFAULT_SUMMARY_ENABLED,
        description="Сжимать ли историю в конспект (день 9)",
    )
    keep_last_messages: int = Field(
        config.DEFAULT_KEEP_LAST_MESSAGES, ge=config.KEEP_LAST_MIN,
        le=config.KEEP_LAST_MAX,
        description="Сколько последних реплик отправлять «как есть» (2–20)",
    )
    summarize_every: int = Field(
        config.DEFAULT_SUMMARIZE_EVERY, ge=config.SUMMARIZE_EVERY_MIN,
        le=config.SUMMARIZE_EVERY_MAX,
        description="Порог сжатия: конспектируем каждые N непокрытых реплик (2–40)",
    )
    strategy: str = Field(
        config.DEFAULT_STRATEGY,
        description=(
            "Стратегия управления контекстом (день 10): sliding_window | "
            "sticky_facts | branching | summary"
        ),
    )
    window_size: int = Field(
        config.DEFAULT_WINDOW_SIZE, ge=config.WINDOW_SIZE_MIN,
        le=config.WINDOW_SIZE_MAX,
        description=(
            "Размер скользящего окна: сколько последних реплик уходит в запрос "
            "для sliding_window и sticky_facts (2–50)"
        ),
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустое/пробельное имя."""
        value = value.strip()
        if not value:
            raise ValueError("имя агента не может быть пустым")
        return value

    @field_validator("strategy")
    @classmethod
    def _strategy_known(cls, value: str) -> str:
        """Допустимы только значения из Enum Strategy."""
        if value not in AVAILABLE_STRATEGIES:
            raise ValueError(
                f"неизвестная стратегия {value!r}; допустимые: "
                f"{', '.join(AVAILABLE_STRATEGIES)}"
            )
        return value


class AgentPatch(BaseModel):
    """Частичное обновление агента (тело PATCH /agents/{agent_id}).

    Все поля необязательные: переключать сжатие можно на живом агенте, не
    теряя диалог (нужно для сравнения режимов в одном диалоге).
    """
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    temperature: Optional[float] = Field(
        default=None, ge=config.TEMPERATURE_MIN, le=config.TEMPERATURE_MAX
    )
    system_prompt: Optional[str] = Field(default=None, max_length=4000)
    max_tokens: Optional[int] = Field(
        default=None, ge=config.MAX_TOKENS_MIN, le=config.MAX_TOKENS_MAX
    )
    summary_enabled: Optional[bool] = None
    keep_last_messages: Optional[int] = Field(
        default=None, ge=config.KEEP_LAST_MIN, le=config.KEEP_LAST_MAX
    )
    summarize_every: Optional[int] = Field(
        default=None, ge=config.SUMMARIZE_EVERY_MIN,
        le=config.SUMMARIZE_EVERY_MAX,
    )
    strategy: Optional[str] = None
    window_size: Optional[int] = Field(
        default=None, ge=config.WINDOW_SIZE_MIN, le=config.WINDOW_SIZE_MAX
    )

    @field_validator("strategy")
    @classmethod
    def _strategy_known(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in AVAILABLE_STRATEGIES:
            raise ValueError(
                f"неизвестная стратегия {value!r}; допустимые: "
                f"{', '.join(AVAILABLE_STRATEGIES)}"
            )
        return value


class AgentSummary(BaseModel):
    """Короткая запись об агенте для списка GET /agents."""
    agent_id: str
    name: str
    model: str
    message_count: int = 0
    summary_enabled: bool = config.DEFAULT_SUMMARY_ENABLED
    keep_last_messages: int = config.DEFAULT_KEEP_LAST_MESSAGES
    summarize_every: int = config.DEFAULT_SUMMARIZE_EVERY
    summary_count: int = 0
    strategy: str = config.DEFAULT_STRATEGY
    window_size: int = config.DEFAULT_WINDOW_SIZE


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
    # Покрыто ли сообщение конспектом (день 9): фронтенд рисует маркер сжатия.
    summarized: bool = False


class TokenMetrics(BaseModel):
    """Метрики токенов одного хода диалога (поля таблицы token_usage)."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    history_tokens: int = 0
    response_tokens: int = 0
    cost: float = 0.0
    mode: str = "full"
    full_context_tokens: int = 0
    sent_context_tokens: int = 0
    saved_tokens: int = 0
    summary_tokens: int = 0
    summarized_messages: int = 0
    summary_used: bool = False


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
    mode: str = "full"
    full_context_tokens: int = 0
    sent_context_tokens: int = 0
    saved_tokens: int = 0
    summary_tokens: int = 0
    summarized_messages: int = 0
    summary_used: bool = False


class UsageSummary(BaseModel):
    """Сводка токенов агента (GET /agents/{agent_id}/usage)."""
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
    # Экономия от сжатия (день 9).
    total_full_context_tokens: int = 0
    total_sent_context_tokens: int = 0
    total_saved_tokens: int = 0
    total_summary_cost: float = 0.0
    total_net_saved_tokens: int = 0
    compressed_requests: int = 0


class GenerateResponse(BaseModel):
    """Результат генерации: метаданные попытки + обновлённая история.

    Поля response/error взаимоисключающие: при status="ok" заполнен response,
    при status="error" — error. messages — актуальный диалог агента ПОСЛЕ
    попытки. День 9: при status="ok" заполнены token_metrics (метрики хода,
    включая экономию сжатия), context (лимит/остаток/обрезка/состояние FSM/
    блок compression).
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


# ---------- стратегии управления контекстом (день 10) ----------
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
