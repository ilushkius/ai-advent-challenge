"""Схемы API дня 14: агент, генерация и метрики использования токенов.

Перенесено из монолитного ``backend/models.py`` без изменения полей. Схемы
отчёта генерации (``GenerateResponse``) тянут соседей из ``context`` / ``memory``
/ ``profile`` / ``task`` / ``invariant`` — эти модули от ``agent`` не зависят,
цикла нет.
"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..core import config
from ..domain.strategies import AVAILABLE_STRATEGIES

from .context import CompressionInfo, ContextInfo
from .invariant import InvariantCheckOut
from .memory import MemoryInfo
from .profile import AppliedProfileOut
from .task import TaskStateOut


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
            "Стратегия управления контекстом (день 11): sliding_window | "
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
    user_id: str = Field(
        config.DEFAULT_USER_ID, min_length=1, max_length=config.USER_ID_MAX,
        description=(
            "Пользователь (день 12): его профиль подключается к системному "
            "промпту каждого запроса агента"
        ),
    )

    @field_validator("user_id")
    @classmethod
    def _user_id_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустой идентификатор пользователя."""
        value = value.strip()
        if not value:
            raise ValueError("user_id не может быть пустым")
        return value

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
    # Персонализация (день 12): смена пользователя меняет профиль, который
    # подключается к системному промпту следующего же запроса.
    user_id: Optional[str] = Field(
        default=None, min_length=1, max_length=config.USER_ID_MAX
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
    # Слои памяти (день 11): какая сессия и задача активны у агента.
    session_id: str = ""
    task_id: str = config.DEFAULT_TASK_ID
    # Персонализация (день 12): чей профиль применяется к запросам агента.
    user_id: str = config.DEFAULT_USER_ID


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
    """Одна реплика краткосрочной памяти (GET history, поле messages ответа)."""
    id: int
    agent_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime
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
    # Фактический расход по слоям памяти (день 11).
    short_term_tokens: int = 0
    working_tokens: int = 0
    long_term_tokens: int = 0


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
    # Расход по слоям памяти (день 11).
    short_term_tokens: int = 0
    working_tokens: int = 0
    long_term_tokens: int = 0


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
    # Расход по слоям памяти за все ходы (день 11).
    total_short_term_tokens: int = 0
    total_working_tokens: int = 0
    total_long_term_tokens: int = 0


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
    # Разбивка контекста по слоям памяти (день 11) — заполняется и при ошибке.
    memory: Optional[MemoryInfo] = None
    # Персонализация (день 12): какой профиль применён и что он добавил в
    # системный промпт; system_prompt — итоговое system-сообщение запроса.
    # Оба поля заполняются ДО вызова DeepSeek, поэтому видны и при 502.
    profile: Optional[AppliedProfileOut] = None
    # Состояние задачи (день 13): этап/шаг/ожидаемое действие на момент ответа.
    # Заполняется ДО вызова DeepSeek, поэтому видно и при 502.
    task_state: Optional[TaskStateOut] = None
    # Инварианты (день 14): какие активные правила проверены и не было ли
    # нарушений. Заполняется и при отказе, и при 502 — проверка ЗАПРОСА идёт
    # до вызова DeepSeek.
    invariants: Optional[InvariantCheckOut] = None
    system_prompt: str = ""
    duration_sec: Optional[float] = None
    timestamp: datetime
    messages: List[MessageOut] = Field(default_factory=list)
