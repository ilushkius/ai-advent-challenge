"""Перенос первого запуска задачи в непиковое окно DeepSeek (день 21).

Вынесено из ``scheduler.py`` отдельным модулем по той же причине, по которой
знание классов APScheduler живёт в ``apscheduler_bridge.py``: ``TaskScheduler``
уперся в лимит 400 строк скилла ``fastapi-streamlit-day-structure``. Здесь — одна
функция, отвечающая на вопрос «в каком моменте ставить задачу, если она просит
непик»; сам планировщик делегирует ей решение и не знает деталей окна.

Флаг ``prefer_off_peak`` лежит в JSON-колонке ``schedule_value``: своей колонки
в ``scheduled_tasks`` нет намеренно — старые базы дня от неё сломались бы, а
расписание и так читается из JSON. Сдвиг применяется ОДИН раз — при постановке:
у cron расписание считает APScheduler, и перенос каждого следующего запуска
поломал бы его триггер.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from shared.logging_utils import get_logger

from ..domain import peak_hours

__all__ = ["shift_to_off_peak"]

logger = get_logger(__name__)


def shift_to_off_peak(task: dict[str, Any],
                      moment: Optional[datetime]) -> Optional[datetime]:
    """Момент первого запуска задачи с учётом флага ``prefer_off_peak``.

    Возвращает момент как есть, если он не задан (cron: расписание знает только
    APScheduler), если задача не просит непик или если момент уже непиковый.
    Пиковый момент сдвигается на начало ближайшего непикового окна, а решение
    пишется в лог (было → стало): иначе перенос оставался бы невидимым.
    """
    if moment is None:
        return None
    if not (task.get("schedule_value") or {}).get("prefer_off_peak"):
        return moment
    if peak_hours.is_off_peak(moment):
        return moment
    shifted = peak_hours.next_off_peak(moment)
    logger.info("Планировщик: задача %s перенесена в непик: %s → %s",
                task.get("id"), moment.isoformat(), shifted.isoformat())
    return shifted
