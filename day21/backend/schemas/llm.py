"""Pydantic-схемы API оптимизации затрат на LLM (день 21).

Схемы повторяют форму словарей из хранилища журнала и домена стоимости
(``storage/llm_usage_rows.py``, ``domain/llm_cost.py``), поэтому роутер не
переупаковывает данные, а только объявляет контракт: запись журнала
(``LLMUsageOut``), агрегированная статистика (``LLMStatsOut``), ответ журнала
(``LLMUsageResponse``), состояние рычагов экономии (``LLMStatusOut``) и прогноз
(``LLMSavingsOut``).

Никаких «своих» чисел в схемах нет: всё считается в домене и хранилище, иначе
интерфейс и отчёт показывали бы разные суммы по одним и тем же запросам.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core import config


class LLMUsageOut(BaseModel):
    """Одна строка журнала расходов: что за запрос, сколько токенов и сколько денег."""

    id: int = Field(..., description="Номер строки журнала")
    agent_id: Optional[str] = Field(None, description="Агент (None — вызов вне агента)")
    timestamp: Optional[str] = Field(None, description="Когда запрос ушёл (ISO-8601, UTC)")
    model: str = Field(..., description="Модель, которая отвечала")
    prompt_tokens: int = Field(0, description="Токенов на входе")
    completion_tokens: int = Field(0, description="Токенов на выходе")
    cache_hit_tokens: int = Field(0, description="Ввод, попавший в кэш контекста")
    cache_miss_tokens: int = Field(0, description="Ввод, кэш которого не нашёлся")
    cost_estimate: float = Field(0.0, description="Оценка стоимости запроса, $")
    request_type: str = Field(..., description="Тип задачи: chat | summarize | classify | …")
    created_at: Optional[str] = Field(None, description="Когда строка записана (ISO-8601, UTC)")

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "LLMUsageOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class LLMStatsOut(BaseModel):
    """Агрегированная статистика расходов за период — то, что считает вкладка «Расходы»."""

    period: str = Field(config.LLM_USAGE_PERIOD_DEFAULT, description="Период агрегации")
    requests: int = Field(0, description="Сколько запросов попало в период")
    prompt_tokens: int = Field(0, description="Сумма токенов ввода")
    completion_tokens: int = Field(0, description="Сумма токенов вывода")
    total_tokens: int = Field(0, description="Ввод + вывод")
    cache_hit_tokens: int = Field(0, description="Ввод из кэша контекста")
    cache_miss_tokens: int = Field(0, description="Ввод мимо кэша")
    cache_hit_percent: float = Field(0.0, description="Доля ввода, взятого из кэша, %")
    cost_estimate: float = Field(0.0, description="Суммарная оценка стоимости, $")
    by_model: Dict[str, Any] = Field(default_factory=dict, description="Разбивка по моделям")
    by_type: Dict[str, Any] = Field(default_factory=dict, description="Разбивка по типам задач")
    daily: List[Dict[str, Any]] = Field(
        default_factory=list, description="Расход по дням: date, requests, total_tokens, cost_estimate"
    )


class LLMUsageResponse(BaseModel):
    """GET /llm/usage — статистика за период и последние запросы."""

    stats: LLMStatsOut = Field(..., description="Агрегаты периода")
    requests: List[LLMUsageOut] = Field(default_factory=list, description="Свежие запросы первыми")
    count: int = Field(0, description="Сколько записей в ответе")


class LLMPromptStatsOut(BaseModel):
    """Статистика строителя промптов: сколько раз стабильный префикс взят из кэша."""

    cache_hits: int = Field(0, description="Сколько раз стабильный префикс взят из кэша")
    cache_misses: int = Field(0, description="Сколько раз префикс собирался заново")
    cache_hit_percent: float = Field(0.0, description="Доля попаданий, %")
    cache_size: int = Field(0, description="Сколько разных префиксов в кэше")
    stable_tokens: int = Field(0, description="Токенов в стабильных префиксах (суммарно)")
    dynamic_tokens: int = Field(0, description="Токенов в динамических частях (суммарно)")
    saved_tokens: int = Field(0, description="Токенов снято сжатием динамической части")
    requests: int = Field(0, description="Сколько раз собирался промпт")


class LLMCompressorStatsOut(BaseModel):
    """Статистика сжатия промптов: сколько токенов убрано."""

    calls: int = Field(0, description="Сколько блоков прошло через сжатие")
    tokens_before: int = Field(0, description="Токенов до сжатия")
    tokens_after: int = Field(0, description="Токенов после сжатия")
    saved_tokens: int = Field(0, description="Сколько токенов снято")
    saved_percent: float = Field(0.0, description="Доля снятых токенов, %")


class LLMStatusOut(BaseModel):
    """GET /llm/status — состояние рычагов экономии прямо сейчас."""

    off_peak: bool = Field(..., description="Сейчас непиковые часы (дешевле)")
    peak: bool = Field(..., description="Сейчас пиковые часы")
    window_label: str = Field("", description="Текущее окно словами, например «01:00–04:00 UTC»")
    next_off_peak: Optional[str] = Field(None, description="Когда начнётся непиковое окно (ISO, UTC)")
    next_off_peak_in_seconds: int = Field(0, description="Сколько секунд до непикового окна")
    discount_percent: int = Field(0, description="Скидка провайдера на непиковых часах, %")
    description: str = Field("", description="Человекочитаемое пояснение окна")
    prompt: LLMPromptStatsOut = Field(..., description="Статистика стабильного префикса")
    compressor: LLMCompressorStatsOut = Field(..., description="Статистика сжатия промптов")
    task_models: Dict[str, str] = Field(
        default_factory=dict, description="Какая модель выбрана для какого типа задачи"
    )
    task_max_tokens: Dict[str, int] = Field(
        default_factory=dict, description="Предел длины ответа по типу задачи"
    )


class LLMEstimateIn(BaseModel):
    """POST /llm/estimate — прогноз экономии по заданным числам токенов."""

    model: str = Field(config.MODEL_CHAT, max_length=config.LLM_USAGE_MODEL_MAX,
                       description="Модель, по тарифам которой считаем")
    task_type: str = Field(config.LLM_TASK_CHAT, max_length=config.LLM_USAGE_TYPE_MAX,
                           description="Тип задачи (он же выбирает модель по умолчанию)")
    prompt_tokens: int = Field(0, ge=0, description="Токенов ввода БЕЗ оптимизации")
    completion_tokens: int = Field(0, ge=0, description="Токенов вывода")
    cache_hit_tokens: int = Field(0, ge=0, description="Сколько ввода попало в кэш контекста")
    compressed_tokens: int = Field(0, ge=0, description="Сколько токенов сняло сжатие динамики")
    max_response_tokens: int = Field(0, ge=0, description="Предел длины ответа в этом запросе")
    off_peak_share: float = Field(
        0.0, ge=0.0, le=1.0, description="Доля запроса, ушедшая в непиковые часы (0…1)"
    )


class LLMSavingsOut(BaseModel):
    """GET/POST прогноза: цена запроса, вклад каждого рычага и общая экономия."""

    model: str = Field(..., description="Модель расчёта")
    cost: float = Field(0.0, description="Стоимость запроса с оптимизацией, $")
    baseline_cost: float = Field(0.0, description="Стоимость без оптимизации, $")
    cache: Dict[str, Any] = Field(default_factory=dict, description="Вклад кэша контекста")
    compression: Dict[str, Any] = Field(default_factory=dict, description="Вклад сжатия промпта")
    response_limit: Dict[str, Any] = Field(default_factory=dict, description="Вклад предела ответа")
    off_peak: Dict[str, Any] = Field(default_factory=dict, description="Вклад непиковых часов")
    core_saving: float = Field(0.0, description="Экономия измеряемых рычагов (кэш + сжатие + непик), $")
    core_saving_percent: float = Field(0.0, description="Она же в процентах от базовой стоимости")
    total_saving: float = Field(0.0, description="Экономия со всеми рычагами, $")
    saving_percent: float = Field(0.0, description="Экономия со всеми рычагами, %")


class LLMModelsOut(BaseModel):
    """GET /llm/models — какие модели и пределы выбраны для каких задач (данные конфига)."""

    task_models: Dict[str, str] = Field(default_factory=dict, description="Тип задачи → модель")
    task_max_tokens: Dict[str, int] = Field(default_factory=dict, description="Тип задачи → предел ответа")
    default_model: str = Field(config.MODEL_CHAT, description="Модель простых задач")
    cache_input_ratio: float = Field(config.LLM_CACHE_INPUT_RATIO,
                                     description="Цена попадания в кэш как доля цены ввода")
    prices: Dict[str, Any] = Field(default_factory=dict, description="Тарифы моделей за 1M токенов")
