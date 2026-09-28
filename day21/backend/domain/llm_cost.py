"""Стоимость запроса к LLM и оценка экономии (день 21).

Чистая арифметика денег: сколько стоил запрос, сколько сэкономил кэш контекста,
сколько дала бы скидка непиковых часов и во что превращается разница токенов после
сжатия промпта. Здесь нет ни сети, ни БД, ни Streamlit — только числа, поэтому
формулы проверяются таблицей тестов, а отчёт об оптимизации считает по ним.

Почему отдельный модуль, а не методы клиента: одна и та же формула нужна трём
потребителям (журнал `llm_usage` при записи, статистика расходов в API, отчёт о
сравнении «до и после»), и второй её экземпляр рано или поздно разошёлся бы с
первым.

Модуль знает только ``config`` и стандартную библиотеку.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core import config

__all__ = [
    "cache_savings",
    "compression_savings",
    "estimate_cost",
    "off_peak_savings",
    "prices_for",
    "savings_summary",
]

#: Токенов в миллионе — цены провайдера заданы за миллион.
MILLION = 1_000_000


def prices_for(model: str) -> dict[str, float]:
    """Цены модели за 1M токенов (``{"in", "out"}``); неизвестная — как у чата.

    Неизвестная модель не должна валить журнал: стоимость — оценка, а не отказ,
    поэтому берём прайс модели по умолчанию.
    """
    return dict(config.MODEL_PRICES.get(model, config.MODEL_PRICES[config.MODEL_CHAT]))


def estimate_cost(*, model: str, prompt_tokens: int = 0, completion_tokens: int = 0,
                  cache_hit_tokens: int = 0) -> float:
    """Оценка стоимости запроса в долларах.

    Ввод делится на две части: попадание в кэш контекста дешевле обычного ввода
    (``LLM_CACHE_INPUT_RATIO``), а промах считается по полной цене. Именно поэтому
    кэш-хит — деньги, а не только скорость: один и тот же запрос с прогретым
    префиксом стоит дешевле, чем без него.
    """
    prices = prices_for(model)
    prompt = max(0, int(prompt_tokens))
    hit = min(max(0, int(cache_hit_tokens)), prompt)
    miss = prompt - hit
    cost = (miss / MILLION) * prices["in"]
    cost += (hit / MILLION) * prices["in"] * config.LLM_CACHE_INPUT_RATIO
    cost += (max(0, int(completion_tokens)) / MILLION) * prices["out"]
    return round(cost, 6)


def cache_savings(*, model: str, cache_hit_tokens: int) -> dict[str, Any]:
    """Сколько сэкономил кэш контекста: цена хитов без кэша минус цена с кэшем."""
    prices = prices_for(model)
    hit = max(0, int(cache_hit_tokens))
    full = (hit / MILLION) * prices["in"]
    cached = full * config.LLM_CACHE_INPUT_RATIO
    return {
        "tokens": hit,
        "cost_without_cache": round(full, 6),
        "cost_with_cache": round(cached, 6),
        "saving": round(full - cached, 6),
    }


def compression_savings(*, model: str, saved_tokens: int) -> dict[str, Any]:
    """Сколько даёт сжатие динамической части промпта (токены → деньги).

    Сжатие уменьшает ВВОД, поэтому считается по цене ввода: полная цена, если бы
    эти токены ушли в запрос, минус ноль (в запрос они не уходят).
    """
    prices = prices_for(model)
    saved = max(0, int(saved_tokens))
    value = (saved / MILLION) * prices["in"]
    return {"tokens": saved, "price_per_million": prices["in"],
            "saving": round(value, 6)}


def off_peak_savings(*, cost: float, discount_percent: Optional[int] = None) -> dict[str, Any]:
    """Сколько дала бы скидка непиковых часов на уже потраченную сумму.

    Это ПРОГНОЗ, а не факт: провайдер снижает цену в непиковых окнах, и перенос
    тяжёлой задачи туда экономит долю стоимости. Проценты берутся из конфига
    (``OFF_PEAK_DISCOUNT_PERCENT``) или из аргумента (тогда их источник —
    `domain/peak_hours.py`).
    """
    percent = int(discount_percent if discount_percent is not None
                  else config.OFF_PEAK_DISCOUNT_PERCENT)
    percent = max(0, min(100, percent))
    value = max(0.0, float(cost))
    saving = value * percent / 100
    return {"cost": round(value, 6), "discount_percent": percent,
            "saving": round(saving, 6),
            "cost_off_peak": round(value - saving, 6)}


def savings_summary(*, model: str = config.MODEL_CHAT, prompt_tokens: int = 0,
                    completion_tokens: int = 0, cache_hit_tokens: int = 0,
                    compressed_tokens: int = 0, max_response_tokens: int = 0,
                    off_peak_share: float = 0.0,
                    discount_percent: Optional[int] = None) -> dict[str, Any]:
    """Итог по одному запросу: цена, вклад каждого рычага и общая экономия.

    Рычаги считаются по отдельности, чтобы в отчёте было видно, ЧТО именно дало
    экономию, а не одна общая цифра:

    * **кэш контекста** — доля ввода, попавшая в префиксный кэш;
    * **сжатие промпта** — токены, снятые с динамической части;
    * **ограничение длины ответа** — сколько НЕ потрачено на вывод относительно
      ``config.DEFAULT_MAX_TOKENS`` (если предел ниже);
    * **непиковые часы** — доля запроса, которую удалось бы увести в скидку.

    ``off_peak_share`` — доля (0…1) стоимости, попавшая в непиковое окно: 1.0 —
    запрос целиком в непик, 0.0 — целиком в пик.
    """
    cost = estimate_cost(model=model, prompt_tokens=prompt_tokens,
                         completion_tokens=completion_tokens,
                         cache_hit_tokens=cache_hit_tokens)
    cache = cache_savings(model=model, cache_hit_tokens=cache_hit_tokens)
    compression = compression_savings(model=model, saved_tokens=compressed_tokens)
    prices = prices_for(model)
    response_saved_tokens = max(0, config.DEFAULT_MAX_TOKENS - int(max_response_tokens)) \
        if max_response_tokens else 0
    response = {
        "tokens": response_saved_tokens,
        "saving": round((response_saved_tokens / MILLION) * prices["out"], 6),
    }
    share = min(1.0, max(0.0, float(off_peak_share)))
    off_peak = off_peak_savings(cost=cost * share, discount_percent=discount_percent)
    #: Экономия «ядра» — только измеряемые рычаги (кэш, сжатие) и скидка непика.
    #: Потолок вывода сюда НЕ входит: он ограничивает ответ сверху, а не сокращает
    #: его, поэтому его вклад показывается отдельной строкой отчёта.
    core_saving = round(cache["saving"] + compression["saving"] + off_peak["saving"], 6)
    baseline = round(cost + cache["saving"] + compression["saving"] + response["saving"]
                     + off_peak["saving"], 6)
    total_saving = round(core_saving + response["saving"], 6)
    return {
        "model": model,
        "cost": cost,
        "baseline_cost": baseline,
        "cache": cache,
        "compression": compression,
        "response_limit": response,
        "off_peak": off_peak,
        "core_saving": core_saving,
        "core_saving_percent": round(core_saving / baseline * 100, 1) if baseline else 0.0,
        "total_saving": total_saving,
        "saving_percent": round(total_saving / baseline * 100, 1) if baseline else 0.0,
    }
