"""Непиковые часы DeepSeek: чистые правила окна скидки (день 21).

Зачем модуль. Провайдер даёт скидку на запросы вне пиковых часов, поэтому тяжёлые
и не срочные задачи (индексация, сбор данных, сводки) дешевле ставить в непиковое
окно, а не «когда пользователь создал задачу». Здесь живёт ровно эта арифметика:
какое окно сейчас, когда начнётся следующее и сколько даст скидка. Модуль чистый —
``datetime`` и константы ``core.config``, ни БД, ни сети, ни планировщика: правила
проверяются таблицей моментов, не поднимая ничего вокруг.

Окно задано в UTC и округляется до минуты:

* будни 00:00–01:00, 04:00–06:00, 10:00–24:00 — непик;
* будни 01:00–04:00, 06:00–10:00 — пик;
* суббота и воскресенье — непик круглые сутки.

Отсюда важное следствие для ``next_off_peak``: он ищет СТРОГО позже переданного
момента, поэтому «пик начался ровно в 01:00» даёт ближайший непик 04:00, а
пятница 23:59 — субботу 00:00 (выходные целиком непик).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..core import config

__all__ = [
    "is_off_peak",
    "next_off_peak",
    "peak_status",
    "savings_forecast",
    "window_label",
]

#: Токенов в миллионе — цены провайдера заданы за миллион (как в ``MODEL_PRICES``).
MILLION = 1_000_000
#: Шаг поиска следующего окна: окно округляется до минуты, мельче смысла нет.
STEP = timedelta(minutes=1)
#: Предел поиска в днях: даже будний день гарантирует непик, это лишь страховка.
MAX_SEARCH_DAYS = 8
#: С какого дня недели начинаются выходные (``datetime.weekday``: понедельник — 0).
WEEKEND_START = 5
#: Запасные границы непика для выходных: сутки целиком.
ALL_DAY_BAND = ((0, 24),)


def _to_utc(moment: datetime) -> datetime:
    """Приводит момент к UTC-aware: наивный ``datetime`` считаем UTC.

    Так же трактует время хранилище дня (naive из SQLite — это UTC), поэтому
    правило не зависит от того, пришёл момент из БД или из ``datetime.now``.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _is_weekend(moment: datetime) -> bool:
    """Выходной ли день (в выходные непик круглые сутки)."""
    return moment.weekday() >= WEEKEND_START


def _off_peak_bands(moment: datetime) -> tuple[tuple[int, int], ...]:
    """Часовые полосы непика для дня этого момента."""
    if _is_weekend(moment):
        return ALL_DAY_BAND
    return config.OFF_PEAK_WEEKDAY_HOURS_UTC


def _band_of(moment: datetime, bands: tuple[tuple[int, int], ...]
             ) -> Optional[tuple[int, int]]:
    """Полоса ``(начало, конец)``, в которую попадает час момента (``None`` — нет)."""
    for start, end in bands:
        if start <= moment.hour < end:
            return start, end
    return None


def _discount_percent(discount_percent: Optional[int]) -> int:
    """Скидка непикового окна в процентах (по умолчанию — константа дня)."""
    if discount_percent is None:
        return int(config.OFF_PEAK_DISCOUNT_PERCENT)
    return max(0, min(100, int(discount_percent)))


def is_off_peak(moment: datetime) -> bool:
    """Идёт ли непиковое окно DeepSeek в этот момент (скидка провайдера)."""
    utc = _to_utc(moment)
    return _band_of(utc, _off_peak_bands(utc)) is not None


def next_off_peak(moment: datetime) -> datetime:
    """Ближайший момент непикового окна СТРОГО позже ``moment``.

    Поиск идёт по минутной сетке (окно целочисленных часов): переводим момент на
    минуту вперёд и идём, пока не попадём в непик. Страховочный предел — восемь
    дней; по правилам окна непик наступает внутри суток, так что предел не
    достигается никогда.
    """
    utc = _to_utc(moment)
    candidate = utc.replace(second=0, microsecond=0) + STEP
    limit = candidate + timedelta(days=MAX_SEARCH_DAYS)
    while candidate <= limit:
        if is_off_peak(candidate):
            return candidate
        candidate += STEP
    return candidate


def window_label(moment: datetime) -> str:
    """Подпись окна, в которое попал момент, например ``2026-09-28 01:00–04:00 UTC``.

    У выходных окно — сутки, поэтому подпись говорит об этом словами: часовые
    полосы буднего дня к ним неприменимы.
    """
    utc = _to_utc(moment)
    date = utc.strftime("%Y-%m-%d")
    if _is_weekend(utc):
        return f"{date} — выходной: непик круглые сутки UTC"
    band = _band_of(utc, config.OFF_PEAK_WEEKDAY_HOURS_UTC)
    if band is None:
        band = _band_of(utc, config.PEAK_WEEKDAY_HOURS_UTC)
    if band is None:  # страховка: полосы буднего дня покрывают сутки целиком
        return f"{date} — непик круглые сутки UTC"
    start, end = band
    return f"{date} {start:02d}:00–{end:02d}:00 UTC"


def peak_status(moment: datetime, *,
                discount_percent: Optional[int] = None) -> dict[str, Any]:
    """Состояние непикового окна на момент: для ``GET /scheduler/status`` и UI.

    Собирает всё, что нужно интерфейсу и планировщику, одним словарём: пик или
    непик, подпись окна, когда начнётся следующее непиковое окно (ISO и через
    сколько секунд) и размер скидки. ``peak`` и ``off_peak`` — отрицания друг
    друга, чтобы читателю не приходилось выводить одно из другого.
    """
    utc = _to_utc(moment)
    off = is_off_peak(utc)
    following = next_off_peak(utc)
    percent = _discount_percent(discount_percent)
    if off:
        description = (
            f"Непиковое окно DeepSeek ({window_label(utc)}): скидка {percent}%"
        )
    else:
        description = (
            f"Пиковые часы DeepSeek ({window_label(utc)}); ближайшее непиковое "
            f"окно — {following.strftime('%d.%m %H:%M')} UTC (скидка {percent}%)"
        )
    return {
        "peak": not off,
        "off_peak": off,
        "window_label": window_label(utc),
        "next_off_peak": following.isoformat(),
        "next_off_peak_in_seconds": int((following - utc).total_seconds()),
        "discount_percent": percent,
        "description": description,
    }


def savings_forecast(tokens: int, price_in: float, *,
                     discount_percent: Optional[int] = None) -> dict[str, Any]:
    """Прогноз экономии на непиковом окне для объёма входных токенов.

    Цена берётся за 1 млн токенов (как в ``config.MODEL_PRICES``), поэтому сумма —
    это ``tokens / 1_000_000 * price_in``. Возвращаем и стоимость «сейчас», и
    стоимость со скидкой, и саму экономию: так отчёт показывает оба варианта, а не
    только выгоду. Ноль токенов даёт нули без деления на ноль.
    """
    percent = _discount_percent(discount_percent)
    amount = max(0, int(tokens))
    million_price = float(price_in)
    cost_now = amount / MILLION * million_price
    saving = cost_now * percent / 100
    return {
        "tokens": amount,
        "price_per_million": round(million_price, 6),
        "cost_now": round(cost_now, 6),
        "cost_off_peak": round(cost_now - saving, 6),
        "saving": round(saving, 6),
        "saving_percent": percent,
    }
