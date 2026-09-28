"""Правила непиковых часов DeepSeek (``domain/peak_hours.py``) — таблицей моментов.

Модуль чистый, поэтому проверяется без БД и планировщика: все моменты заданы
константами UTC, а не берутся из ``datetime.now`` — иначе тест зависел бы от дня
недели и часа запуска.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.core import config
from backend.domain import peak_hours

UTC = timezone.utc


def moment(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Момент UTC в читаемой форме (без этого строки теста не различить)."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# 2026-09-28 — понедельник, 2026-09-26 — суббота, 2026-09-27 — воскресенье,
# 2026-10-02 — пятница: дни подобраны так, чтобы таблица читалась без вычислений.
OFF_PEAK_TABLE = [
    (moment(2026, 9, 28, 0, 30), True, "будни 00:30 — непик"),
    (moment(2026, 9, 28, 2, 0), False, "будни 02:00 — пик"),
    (moment(2026, 9, 28, 4, 30), True, "будни 04:30 — непик"),
    (moment(2026, 9, 28, 7, 0), False, "будни 07:00 — пик"),
    (moment(2026, 9, 28, 11, 0), True, "будни 11:00 — непик"),
    (moment(2026, 9, 28, 23, 30), True, "будни 23:30 — непик"),
    (moment(2026, 9, 26, 2, 0), True, "суббота 02:00 — непик круглые сутки"),
    (moment(2026, 9, 27, 7, 0), True, "воскресенье 07:00 — непик круглые сутки"),
]


@pytest.mark.parametrize("value,expected,note", OFF_PEAK_TABLE,
                         ids=[item[2] for item in OFF_PEAK_TABLE])
def test_is_off_peak_table(value: datetime, expected: bool, note: str) -> None:
    """Таблица «момент → непик»: границы пика 01–04 и 06–10 в будни."""
    assert peak_hours.is_off_peak(value) is expected


@pytest.mark.parametrize("value,expected,note", OFF_PEAK_TABLE,
                         ids=[item[2] for item in OFF_PEAK_TABLE])
def test_peak_status_matches_is_off_peak(value: datetime, expected: bool,
                                         note: str) -> None:
    """``peak_status`` не расходится с ``is_off_peak`` и всегда даёт одно из двух."""
    status = peak_hours.peak_status(value)
    assert status["off_peak"] is expected
    assert status["peak"] is (not expected)
    assert status["peak"] != status["off_peak"]


def test_next_off_peak_at_peak_start() -> None:
    """Ровно 01:00 — начало пика, значит ближайший непик 04:00 (искать не от себя)."""
    assert peak_hours.next_off_peak(moment(2026, 9, 28, 1)) == moment(2026, 9, 28, 4)


def test_next_off_peak_before_weekend() -> None:
    """Пятница 23:59 → суббота 00:00: выходные целиком непик."""
    assert peak_hours.next_off_peak(moment(2026, 10, 2, 23, 59)) == moment(2026, 10, 3, 0)


def test_next_off_peak_during_weekend_goes_forward() -> None:
    """Воскресенье 12:00 уже непик, но ``next_off_peak`` идёт строго вперёд."""
    assert peak_hours.is_off_peak(moment(2026, 9, 27, 12)) is True
    assert peak_hours.next_off_peak(moment(2026, 9, 27, 12)) == moment(2026, 9, 27, 12, 1)


def test_next_off_peak_after_weekend() -> None:
    """Воскресенье 23:59 → понедельник 00:00 (непиковая полоса 00–01)."""
    assert peak_hours.next_off_peak(moment(2026, 9, 27, 23, 59)) == moment(2026, 9, 28, 0)


@pytest.mark.parametrize("value,expected,note", OFF_PEAK_TABLE,
                         ids=[item[2] for item in OFF_PEAK_TABLE])
def test_next_off_peak_is_strictly_monotonic(value: datetime, expected: bool,
                                             note: str) -> None:
    """Монотонность: следующий непик всегда строго позже переданного момента."""
    following = peak_hours.next_off_peak(value)
    assert following > value
    assert peak_hours.is_off_peak(following) is True


def test_window_label_names_the_band() -> None:
    """Подпись окна содержит его часовые границы (пик и непик — разные полосы)."""
    peak = peak_hours.window_label(moment(2026, 9, 28, 2))
    assert "01:00" in peak and "04:00" in peak
    late = peak_hours.window_label(moment(2026, 9, 28, 23))
    assert "10:00" in late and "24:00" in late


def test_window_label_marks_weekend() -> None:
    """У выходных часовой полосы нет — подпись говорит об этом словами."""
    label = peak_hours.window_label(moment(2026, 9, 26, 2))
    assert "выходной" in label


def test_peak_status_keys_and_forecast() -> None:
    """Состав ключей ``peak_status`` и согласованность прогноза с моментом."""
    value = moment(2026, 9, 28, 2)
    status = peak_hours.peak_status(value)
    assert set(status) == {
        "peak", "off_peak", "window_label", "next_off_peak",
        "next_off_peak_in_seconds", "discount_percent", "description",
    }
    assert status["discount_percent"] == config.OFF_PEAK_DISCOUNT_PERCENT
    assert status["next_off_peak_in_seconds"] > 0
    assert datetime.fromisoformat(status["next_off_peak"]) == peak_hours.next_off_peak(value)
    assert status["description"]


def test_peak_status_accepts_discount_override() -> None:
    """Скидку можно переопределить: константа дня — лишь значение по умолчанию."""
    status = peak_hours.peak_status(moment(2026, 9, 28, 2), discount_percent=25)
    assert status["discount_percent"] == 25


def test_naive_datetime_is_treated_as_utc() -> None:
    """Наивный момент считаем UTC: так же трактует время хранилище дня."""
    naive = datetime(2026, 9, 28, 2, 0)
    aware = moment(2026, 9, 28, 2)
    assert peak_hours.is_off_peak(naive) is peak_hours.is_off_peak(aware) is False


def test_aware_datetime_is_converted_to_utc() -> None:
    """Осведомлённый момент переводим в UTC: 05:00+03:00 — это пиковые 02:00 UTC."""
    shifted = datetime(2026, 9, 28, 5, 0, tzinfo=timezone(timedelta(hours=3)))
    assert peak_hours.is_off_peak(shifted) is False


def test_savings_forecast_applies_discount() -> None:
    """Скидка 50% на миллион входных токенов по 0.27 — экономия 0.135 доллара."""
    forecast = peak_hours.savings_forecast(1_000_000, 0.27)
    assert forecast == {
        "tokens": 1_000_000,
        "price_per_million": 0.27,
        "cost_now": 0.27,
        "cost_off_peak": 0.135,
        "saving": 0.135,
        "saving_percent": 50,
    }


def test_savings_forecast_zero_tokens() -> None:
    """Ноль токенов не делит на ноль: все суммы нулевые, цена сохраняется."""
    forecast = peak_hours.savings_forecast(0, 0.55)
    assert forecast["cost_now"] == 0.0
    assert forecast["cost_off_peak"] == 0.0
    assert forecast["saving"] == 0.0
    assert forecast["price_per_million"] == 0.55


def test_savings_forecast_uses_explicit_discount() -> None:
    """Явная скидка перебивает константу дня (в отчёте бывает другой сценарий)."""
    forecast = peak_hours.savings_forecast(1_000_000, 1.0, discount_percent=25)
    assert forecast["saving"] == 0.25
    assert forecast["saving_percent"] == 25
