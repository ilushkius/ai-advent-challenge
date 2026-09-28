"""Чтение внешнего источника данных (день 18).

Единственное место, где фон ходит в сеть: инструмент ``collect_data`` (и первый
сбор при регистрации, и каждый тик) вызывает ``fetch_json``. Транспорт вынесен
отдельным модулем, потому что ошибок у него много, а текст у них один —
пригодный и для модели, и для человека: «источник недоступен», «ответил ошибкой
HTTP 500», «вернул не JSON», «ответ больше N байт».

Ограничение размера ответа — защита от гигантского JSON: одна запись таблицы
``collected_data`` не должна съесть память процесса и раздуть БД, поэтому тело
свыше ``COLLECT_MAX_BYTES`` не сохраняется, а отказ приходит понятным текстом.

Функция не «ходит» сама по себе в тестах и в скрипте прогона: она принимается
аргументом (``fetch=fetch_json``), поэтому стенд отчёта подменяет её
детерминированным ответом, а интеграционные тесты — фейком без сети.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from ..core import config

__all__ = ["SourceFetchError", "fetch_json"]


class SourceFetchError(RuntimeError):
    """Источник не отдал данные: текст причины виден пользователю и модели."""


def fetch_json(url: str, timeout: Optional[float] = None,
               max_bytes: Optional[int] = None) -> Any:
    """Читает JSON по адресу или бросает ``SourceFetchError`` с причиной.

    Не-2xx — отказ (перенаправления при этом разворачиваются: адрес может быть
    короткой ссылкой). Тело больше ``max_bytes`` не разбирается: это не «данные
    другого вида», а отказ от сохранения.
    """
    pause = config.COLLECT_TIMEOUT if timeout is None else float(timeout)
    limit = config.COLLECT_MAX_BYTES if max_bytes is None else int(max_bytes)
    try:
        response = httpx.get(url, timeout=pause, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SourceFetchError(f"Источник {url} недоступен: {exc}") from exc
    if response.status_code >= 400:
        raise SourceFetchError(
            f"Источник {url} ответил ошибкой HTTP {response.status_code}"
        )
    body = response.content or b""
    if len(body) > limit:
        raise SourceFetchError(
            f"Источник {url} вернул {len(body)} байт — это больше предела "
            f"{limit}, ответ не сохранён"
        )
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceFetchError(f"Источник {url} вернул не JSON: {exc}") from exc
