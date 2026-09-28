"""Арифметика стоимости LLM: цена запроса, вклад кэша, сжатия и непика (день 21).

Формулы — единственное место, где токены превращаются в деньги, и по ним считают
три потребителя: журнал `llm_usage`, статистика расхода в API и отчёт об
оптимизации. Поэтому здесь проверяются не только суммы, но и границы: попадание в
кэш дешевле обычного ввода, отсутствие данных о кэше не завышает долю попаданий, а
вклад предела длины ответа НЕ входит в «ядро» экономии (он ограничивает вывод
сверху, а не сокращает полученный ответ).
"""
import pytest

from backend.core import config
from backend.domain.llm_cost import (
    cache_savings,
    compression_savings,
    estimate_cost,
    off_peak_savings,
    prices_for,
    savings_summary,
)

CHAT = config.MODEL_CHAT
REASONER = config.MODEL_REASONER


def test_prices_known_and_unknown_model():
    """Тариф известной модели берётся из конфига, неизвестной — как у чата."""
    assert prices_for(CHAT) == config.MODEL_PRICES[CHAT]
    assert prices_for("какая-то-модель") == config.MODEL_PRICES[CHAT]


def test_cost_of_input_and_output():
    """Стоимость запроса = ввод по цене ввода + вывод по цене вывода."""
    cost = estimate_cost(model=CHAT, prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost == pytest.approx(config.MODEL_PRICES[CHAT]["in"]
                                 + config.MODEL_PRICES[CHAT]["out"], abs=1e-6)


def test_cache_hit_is_cheaper_than_miss():
    """Попадание в кэш считается по доле цены ввода и дешевле полного ввода."""
    full = estimate_cost(model=CHAT, prompt_tokens=100_000, cache_hit_tokens=0)
    cached = estimate_cost(model=CHAT, prompt_tokens=100_000, cache_hit_tokens=100_000)
    assert cached < full
    assert cached == pytest.approx(full * config.LLM_CACHE_INPUT_RATIO, rel=1e-6)


def test_cache_hit_is_clamped_to_prompt():
    """Хитов не может быть больше, чем ввода: лишнее значение не меняет цену."""
    assert estimate_cost(model=CHAT, prompt_tokens=100, cache_hit_tokens=10_000) == \
        estimate_cost(model=CHAT, prompt_tokens=100, cache_hit_tokens=100)


def test_different_models_cost_differently():
    """Дорогая модель дороже дешёвой на тех же токенах (на этом держится выбор модели)."""
    cheap = estimate_cost(model=CHAT, prompt_tokens=50_000, completion_tokens=500)
    dear = estimate_cost(model=REASONER, prompt_tokens=50_000, completion_tokens=500)
    assert dear > cheap


def test_cache_savings_shape():
    """Экономия кэша — разница между полной ценой хитов и ценой со скидкой."""
    saving = cache_savings(model=CHAT, cache_hit_tokens=200_000)
    assert saving["tokens"] == 200_000
    assert saving["cost_without_cache"] > saving["cost_with_cache"]
    assert saving["saving"] == pytest.approx(
        saving["cost_without_cache"] - saving["cost_with_cache"], abs=1e-9)


def test_compression_savings_counts_input_price():
    """Сжатие экономит ввод: снятые токены оцениваются по цене ввода."""
    saving = compression_savings(model=CHAT, saved_tokens=50_000)
    assert saving["saving"] == pytest.approx(
        (50_000 / 1_000_000) * config.MODEL_PRICES[CHAT]["in"], abs=1e-9)
    assert compression_savings(model=CHAT, saved_tokens=0)["saving"] == 0


def test_off_peak_savings_applies_discount():
    """Скидка непиковых часов — доля стоимости; границы процента зажаты 0…100."""
    forecast = off_peak_savings(cost=1.0, discount_percent=50)
    assert forecast["saving"] == pytest.approx(0.5)
    assert forecast["cost_off_peak"] == pytest.approx(0.5)
    assert off_peak_savings(cost=1.0, discount_percent=500)["discount_percent"] == 100
    assert off_peak_savings(cost=1.0, discount_percent=-5)["discount_percent"] == 0


def test_summary_separates_core_from_response_limit():
    """«Ядро» экономии — кэш и сжатие; предел ответа показан отдельно.

    Это правило отчёта: цифра «минимум 30%» не должна держаться на оценке сверху,
    поэтому вклад предела длины ответа виден, но в `core_saving` не входит.
    """
    summary = savings_summary(model=CHAT, prompt_tokens=100_000, completion_tokens=400,
                              cache_hit_tokens=60_000, compressed_tokens=10_000,
                              max_response_tokens=1_000, off_peak_share=0.0)
    assert summary["core_saving"] == pytest.approx(
        summary["cache"]["saving"] + summary["compression"]["saving"], abs=1e-9)
    assert summary["response_limit"]["tokens"] == config.DEFAULT_MAX_TOKENS - 1_000
    assert summary["total_saving"] > summary["core_saving"]
    assert 0 < summary["saving_percent"] < 100


def test_summary_without_cache_data():
    """Без данных о кэше и сжатии экономия нулевая, стоимость считается по полной цене."""
    summary = savings_summary(model=CHAT, prompt_tokens=10_000, completion_tokens=100,
                              max_response_tokens=config.DEFAULT_MAX_TOKENS)
    assert summary["cache"]["saving"] == 0
    assert summary["compression"]["saving"] == 0
    assert summary["core_saving_percent"] == 0.0


def test_off_peak_share_limits_forecast():
    """Доля непика ограничена 0…1: доля больше единицы не даёт лишней экономии."""
    full = savings_summary(model=CHAT, prompt_tokens=10_000, off_peak_share=1.0)
    clamped = savings_summary(model=CHAT, prompt_tokens=10_000, off_peak_share=5.0)
    assert clamped["off_peak"]["saving"] == full["off_peak"]["saving"]
    assert savings_summary(model=CHAT, prompt_tokens=10_000,
                           off_peak_share=0.0)["off_peak"]["saving"] == 0
