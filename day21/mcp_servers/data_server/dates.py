"""Инструмент ``filter_by_date``: отбор записей по дате в поле.

Даты приходят строками из разных источников, поэтому разбор терпимый: сначала
``datetime.fromisoformat`` (с допуском завершающего ``Z`` — так отдаёт время
sqlite и веб), затем шаблоны ``config.DATE_FORMATS`` (ISO, ``ДД.ММ.ГГГГ`` и время
без зоны). Запись без разобранной даты — НЕ ошибка инструмента: она попадает в
счётчик ``skipped``, потому что в ленте источников всегда есть записи без даты, и
падать из-за них значило бы терять остальные.

Границы отбора включительные; пустая граница означает «без ограничения с этой
стороны». Моменты со смещением приводятся к UTC, «наивные» считаются UTC — иначе
сравнение давало бы TypeError на смешанных данных.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.data_server import config
from mcp_servers.data_server.schemas import FilterResult


def parse_moment(value: Any) -> datetime | None:
    """Момент времени из значения поля: ISO-8601, форматы дня или ``None``."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    for template in config.DATE_FORMATS:
        try:
            return datetime.strptime(text, template)
        except ValueError:
            continue
    return None


def parse_bound(value: Any) -> datetime | None:
    """Граница отбора: пустая — без ограничения, неразобранная — ошибка инструмента."""
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    moment = parse_moment(text)
    if moment is None:
        raise ToolError(
            f"Граница «{text}» не разобрана: нужен ISO-8601 или ДД.ММ.ГГГГ"
        )
    return moment


def clamp_limit(limit) -> int:
    """Сколько записей вернуть: в границах 1..``ITEMS_MAX``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = config.FILTER_LIMIT_DEFAULT
    return max(1, min(value, config.ITEMS_MAX))


def comparable(moment: datetime) -> datetime:
    """Момент в одной шкале: со смещением — переведён в UTC, наивный — как есть."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def filter_by_date(items: List[Dict[str, Any]],
                   field: str = config.FILTER_DEFAULT_FIELD,
                   since: str = "", until: str = "",
                   limit: int = config.FILTER_LIMIT_DEFAULT) -> FilterResult:
    """Отбирает записи, дата которых попадает в границы.

    Параметры: items — список записей (словарей); field — имя поля с датой (по
    умолчанию ``created_at``); since — нижняя граница включительно (пустая строка
    — без ограничения); until — верхняя граница включительно (пустая строка — без
    ограничения); limit — сколько записей вернуть (1..200, по умолчанию 20).
    Границы принимаются в ISO-8601 (``2026-01-02``, ``2026-01-02T03:04:05``) или
    как ``ДД.ММ.ГГГГ`` (``02.01.2026``). Пример: filter_by_date(items=items,
    field="created_at", since="2026-01-01", until="31.01.2026", limit=10).

    Возвращает объект с полями items (оставленные записи в исходном порядке),
    count (их число), skipped (сколько записей пропущено из-за отсутствующей или
    неразобранной даты), field, since и until (границы как переданы). Пропущенные
    записи — не ошибка; ошибкой инструмент отвечает только на неразобранную
    непустую границу.
    """
    since_moment = parse_bound(since)
    until_moment = parse_bound(until)
    since_key = None if since_moment is None else comparable(since_moment)
    until_key = None if until_moment is None else comparable(until_moment)

    kept: List[Dict[str, Any]] = []
    skipped = 0
    for item in items or []:
        moment = parse_moment(item.get(field)) if isinstance(item, dict) else None
        if moment is None:
            skipped += 1
            continue
        key = comparable(moment)
        if since_key is not None and key < since_key:
            continue
        if until_key is not None and key > until_key:
            continue
        kept.append(item)

    selected = kept[:clamp_limit(limit)]
    return FilterResult(
        items=selected,
        count=len(selected),
        skipped=skipped,
        field=field,
        since="" if since is None else str(since).strip(),
        until="" if until is None else str(until).strip(),
    )
