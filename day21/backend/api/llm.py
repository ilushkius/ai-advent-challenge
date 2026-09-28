"""Роутер API дня 21: расходы на LLM и рычаги их снижения.

Четыре эндпоинта — журнал, состояние, прогноз и справка по моделям:

- ``GET /llm/usage`` — агрегированная статистика расходов за период (токены, доля
  попаданий в кэш контекста, стоимость, разбивка по моделям и типам задач) плюс
  последние запросы с ``cache_hit_tokens``/``cache_miss_tokens``;
- ``GET /llm/status`` — пик или непик прямо сейчас, когда начнётся дешёвое окно и
  скидка провайдера, плюс статистика стабильного префикса промптов (сколько раз он
  взят из кэша) и сжатия;
- ``POST /llm/estimate`` — прогноз экономии по числам токенов: вклад кэша, сжатия,
  предела длины ответа и непиковых часов по отдельности;
- ``GET /llm/models`` — какие модели и пределы выбраны для каких типов задач.

Числа нигде не пересчитываются на стороне роутера: их дают хранилище журнала
(``storage/llm_usage_store.py``) и домен стоимости (``domain/llm_cost.py``), поэтому
вкладка «Расходы», отчёт об оптимизации и этот API показывают одни и те же суммы.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core import config
from ..core import dependencies
from ..domain import peak_hours
from ..domain.llm_cost import prices_for, savings_summary
from ..schemas import (
    LLMEstimateIn,
    LLMModelsOut,
    LLMSavingsOut,
    LLMStatusOut,
    LLMUsageResponse,
)

router = APIRouter()


@router.get(
    "/llm/usage",
    response_model=LLMUsageResponse,
    summary="Журнал расходов на LLM",
    description=(
        "Статистика за период (`day` | `week` | `month` | `all`, по умолчанию "
        "`week`): сколько запросов, токенов ввода и вывода, **сколько ввода попало "
        "в кэш контекста** (`cache_hit_tokens` против `cache_miss_tokens`), доля "
        "попаданий, оценка стоимости и разбивка по моделям, типам задач и дням. "
        "Рядом — последние запросы (по умолчанию 50): по ним видно, какие типы "
        "задач ушли на дешёвую модель и где кэш не сработал. Необязательный "
        "`agent_id` сужает выборку до одного агента. Неизвестный период — 400."
    ),
)
def llm_usage(
    agent_id: Optional[str] = Query(None, description="Только запросы этого агента"),
    period: Optional[str] = Query(None, description="Период: day | week | month | all"),
    limit: int = Query(config.LLM_USAGE_LIMIT, ge=1, description="Сколько последних запросов отдать"),
) -> LLMUsageResponse:
    """Статистика расходов и последние запросы из журнала `llm_usage`."""
    try:
        payload = dependencies.get_llm_client().usage(agent_id=agent_id, period=period,
                                                     limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LLMUsageResponse(**payload)


@router.get(
    "/llm/status",
    response_model=LLMStatusOut,
    summary="Состояние рычагов экономии",
    description=(
        "Пиковые или непиковые часы сейчас (`peak`/`off_peak`), когда начнётся "
        "дешёвое окно и какова скидка провайдера, плюс статистика кэша стабильных "
        "префиксов промпта (сколько раз префикс собран заново и сколько раз взят из "
        "кэша) и сжатия динамической части (сколько токенов снято). Здесь же — "
        "таблица «тип задачи → модель» и «тип задачи → предел длины ответа», чтобы "
        "маршрутизацию моделей было видно без чтения конфига."
    ),
)
def llm_status() -> LLMStatusOut:
    """Пик/непик и статистика кэша промптов — то, что показывает вкладка «Расходы»."""
    scheduler_peak = dependencies.get_scheduler().peak_status()
    builder = dependencies.get_prompt_builder()
    prompt = builder.stats()
    compressor = builder.compressor.stats
    return LLMStatusOut(
        **scheduler_peak,
        prompt=prompt,
        compressor=compressor,
        task_models=dict(config.LLM_TASK_MODELS),
        task_max_tokens=dict(config.LLM_TASK_MAX_TOKENS),
    )


@router.post(
    "/llm/estimate",
    response_model=LLMSavingsOut,
    summary="Прогноз экономии по числам токенов",
    description=(
        "Считает стоимость запроса и вклад каждого рычага по отдельности: кэш "
        "контекста, сжатие динамической части промпта, предел длины ответа и скидка "
        "непиковых часов. `core_saving` — только измеряемые рычаги (кэш, сжатие, "
        "непик): предел ответа ограничивает вывод сверху, поэтому в него не входит и "
        "показан отдельной строкой. Этим же расчётом пользуется отчёт об оптимизации."
    ),
)
def llm_estimate(body: LLMEstimateIn) -> LLMSavingsOut:
    """Прогноз экономии (тот же расчёт, что в отчёте `docs/reports/cost_optimization.md`)."""
    payload = savings_summary(
        model=body.model,
        prompt_tokens=body.prompt_tokens,
        completion_tokens=body.completion_tokens,
        cache_hit_tokens=body.cache_hit_tokens,
        compressed_tokens=body.compressed_tokens,
        max_response_tokens=body.max_response_tokens,
        off_peak_share=body.off_peak_share,
    )
    return LLMSavingsOut(**payload)


@router.get(
    "/llm/models",
    response_model=LLMModelsOut,
    summary="Модель и предел ответа по типу задачи",
    description=(
        "Данные маршрутизации моделей: какие типы задач идут на дешёвую модель, а "
        "какие — на основную, какой предел длины ответа задан каждому типу, какова "
        "цена попадания в кэш относительно обычного ввода и тарифы моделей за 1M "
        "токенов. Это тот же конфиг, по которому работает `LLMClient`, поэтому "
        "таблица не может разойтись с поведением."
    ),
)
def llm_models() -> LLMModelsOut:
    """Справка по маршрутизации моделей и пределам длины ответа."""
    return LLMModelsOut(
        task_models=dict(config.LLM_TASK_MODELS),
        task_max_tokens=dict(config.LLM_TASK_MAX_TOKENS),
        default_model=config.LLM_TASK_MODELS[config.LLM_TASK_DEFAULT],
        prices={model: prices_for(model) for model in config.MODEL_PRICES},
    )


@router.get(
    "/llm/peak",
    summary="Пиковые и непиковые окна DeepSeek (UTC)",
    description=(
        "Правило окон словами и таблицей: непик — будни 00:00–01:00, 04:00–06:00 и "
        "10:00–24:00 UTC плюс все выходные; пик — будни 01:00–04:00 и 06:00–10:00 "
        "UTC. Отдаётся вместе с текущим статусом и моментом следующего дешёвого "
        "окна: по нему планировщик ставит тяжёлые задачи (`prefer_off_peak`)."
    ),
)
def llm_peak() -> dict:
    """Правило непиковых окон и текущий статус (для интерфейса и документации)."""
    return {
        "off_peak_weekday_hours_utc": [list(item) for item in
                                       config.OFF_PEAK_WEEKDAY_HOURS_UTC],
        "peak_weekday_hours_utc": [list(item) for item in config.PEAK_WEEKDAY_HOURS_UTC],
        "weekends_off_peak": True,
        "discount_percent": config.OFF_PEAK_DISCOUNT_PERCENT,
        "status": peak_hours.peak_status(config_now()),
    }


def config_now():
    """Текущий момент в UTC (функция, а не значение: роутер вызывается многократно)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
