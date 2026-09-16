"""Тесты чистой арифметики сжатия контекста (день 9).

Что это.
    Модульные тесты `backend/context_policy.py` на pytest: границы порога
    сжатия, инвариант «сумма частей равна целому», негативные входы и защита
    от рассинхрона плана и данных в `split_uncovered`.

Как запустить.
        # из папки day9 (pytest.ini добавит корень дня в sys.path)
        python -m pytest -q tests/test_context_policy.py
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.context_policy import (
    CompressionPlan,
    CompressionPolicy,
    ContextPayload,
    plan_compression,
    split_uncovered,
)

DEFAULT_KEEP_LAST = 6
DEFAULT_SUMMARIZE_EVERY = 10


@pytest.mark.parametrize(
    "uncovered_count, expected_should, expected_summarize, expected_keep",
    [
        (DEFAULT_KEEP_LAST - 1, False, 0, 5),  # keep_last - 1
        (DEFAULT_KEEP_LAST, False, 0, 6),  # keep_last — ровно граница
        (DEFAULT_KEEP_LAST + 1, False, 0, 7),  # keep_last + 1
        (DEFAULT_KEEP_LAST + DEFAULT_SUMMARIZE_EVERY - 1, False, 0, 15),  # порог - 1
        (DEFAULT_KEEP_LAST + DEFAULT_SUMMARIZE_EVERY, True, 10, 6),  # ровно порог
        (DEFAULT_KEEP_LAST + DEFAULT_SUMMARIZE_EVERY + 3, True, 13, 6),  # порог + 3
    ],
)
def test_threshold_boundaries(
    uncovered_count: int,
    expected_should: bool,
    expected_summarize: int,
    expected_keep: int,
) -> None:
    """Границы порога: до — копим, ровно на пороге — сжимаем."""
    plan = plan_compression(CompressionPolicy(), uncovered_count)

    assert plan.should_compress is expected_should
    assert plan.summarize_count == expected_summarize
    assert plan.keep_count == expected_keep
    assert plan.uncovered_count == uncovered_count


@pytest.mark.parametrize("uncovered_count", range(0, 41))
def test_counts_invariant(uncovered_count: int) -> None:
    """keep_count + summarize_count == uncovered_count на всём диапазоне 0..40."""
    plan = plan_compression(CompressionPolicy(), uncovered_count)

    assert plan.uncovered_count == uncovered_count
    assert plan.summarize_count >= 0
    assert plan.keep_count >= 0
    assert plan.keep_count + plan.summarize_count == uncovered_count


@pytest.mark.parametrize("uncovered_count", [0, 1, 5, 6, 15])
def test_no_compression_keeps_whole_history(uncovered_count: int) -> None:
    """Без сжатия summarize_count == 0, а как есть уходит вся история."""
    plan = plan_compression(CompressionPolicy(), uncovered_count)

    assert plan.should_compress is False
    assert plan.summarize_count == 0
    assert plan.keep_count == uncovered_count


def test_disabled_policy_never_compresses() -> None:
    """Выключенное сжатие не срабатывает даже на огромной истории."""
    plan = plan_compression(CompressionPolicy(enabled=False), 1000)

    assert plan.should_compress is False
    assert plan.summarize_count == 0
    assert plan.keep_count == 1000


def test_zero_uncovered_is_noop() -> None:
    """Пустая непокрытая история — ничего не делаем."""
    plan = plan_compression(CompressionPolicy(), 0)

    assert plan == CompressionPlan(
        should_compress=False,
        summarize_count=0,
        keep_count=0,
        uncovered_count=0,
    )


def test_negative_uncovered_raises() -> None:
    """Отрицательное число реплик — ValueError."""
    with pytest.raises(ValueError):
        plan_compression(CompressionPolicy(), -1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"keep_last": 0},
        {"keep_last": -3},
        {"summarize_every": 0},
        {"summarize_every": -1},
    ],
)
def test_invalid_policy_raises(kwargs: dict) -> None:
    """keep_last и summarize_every меньше 1 — ValueError при создании политики."""
    with pytest.raises(ValueError):
        CompressionPolicy(**kwargs)


def test_split_uncovered_with_compression() -> None:
    """При сжатии самые старые уходят в конспект, последние — как есть."""
    policy = CompressionPolicy(keep_last=2, summarize_every=3)
    plan = plan_compression(policy, 10)  # backlog = 8 >= 3
    assert plan.should_compress is True

    uncovered = tuple(f"реплика-{i}" for i in range(10))
    payload = split_uncovered(uncovered, plan)

    assert payload.to_summarize == uncovered[:8]
    assert payload.to_keep == uncovered[8:]
    assert isinstance(payload.to_summarize, tuple)
    assert isinstance(payload.to_keep, tuple)


def test_split_uncovered_without_compression() -> None:
    """Без сжатия всё уходит в to_keep, to_summarize пуст."""
    plan = plan_compression(CompressionPolicy(), 3)
    assert plan.should_compress is False

    uncovered = ("a", "b", "c")
    payload = split_uncovered(uncovered, plan)

    assert payload.to_summarize == ()
    assert payload.to_keep == uncovered


def test_split_uncovered_count_mismatch_raises() -> None:
    """Рассинхрон плана и данных — ValueError, а не молчаливая обрезка."""
    plan = plan_compression(CompressionPolicy(), 3)

    with pytest.raises(ValueError):
        split_uncovered(("a", "b"), plan)


def test_split_uncovered_does_not_mutate_input() -> None:
    """Вход-кортеж не меняется, а результат — новый объект ContextPayload."""
    policy = CompressionPolicy(keep_last=1, summarize_every=1)
    plan = plan_compression(policy, 4)
    uncovered = ("a", "b", "c", "d")

    payload = split_uncovered(uncovered, plan)

    assert uncovered == ("a", "b", "c", "d")
    assert payload.to_summarize == ("a", "b", "c")
    assert payload.to_keep == ("d",)
    assert isinstance(payload, ContextPayload)


def test_policy_is_frozen() -> None:
    """CompressionPolicy — frozen dataclass."""
    policy = CompressionPolicy()

    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.keep_last = 99  # type: ignore[misc]


def test_plan_is_frozen() -> None:
    """CompressionPlan — frozen dataclass."""
    plan = CompressionPlan(
        should_compress=True,
        summarize_count=1,
        keep_count=1,
        uncovered_count=2,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.should_compress = False  # type: ignore[misc]


def test_policy_from_dict_roundtrip() -> None:
    """from_dict восстанавливает политику из словаря (БД/API)."""
    policy = CompressionPolicy.from_dict(
        {"enabled": False, "keep_last": 3, "summarize_every": 5}
    )

    assert policy == CompressionPolicy(enabled=False, keep_last=3, summarize_every=5)


def test_policy_from_dict_uses_defaults_for_missing_keys() -> None:
    """Частичный словарь дополняется значениями по умолчанию."""
    assert CompressionPolicy.from_dict({}) == CompressionPolicy()
