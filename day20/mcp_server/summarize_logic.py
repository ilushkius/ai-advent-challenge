"""Логика инструмента ``summarize`` (день 19): стиль, промпт и агрегация.

Модуль чистый: ни MCP SDK, ни HTTP, ни DeepSeek. Из него собирается всё, что можно
проверить офлайн, — нормализация стиля и длины, промпт для модели, разбор
ключевых пунктов из её ответа и АГРЕГАЦИЯ (движок ``aggregation``), которая
выручает, когда LLM недоступна: у инструмента ``summarize`` нет права падать
из-за отсутствия ключа, потому что пайплайн целиком рассчитан на работу офлайн.

Стили: ``short`` (одна строка с первыми элементами), ``detailed`` (нумерованный
список), ``bullets`` (маркированный список). Во всех случаях текст обрезается до
запрошенной длины, а ключевые пункты — это заголовки элементов.
"""
from __future__ import annotations

import re
from typing import Any

from mcp_server import config
from mcp_server.schemas import SummaryResult

#: Маркер, с которого в ответе LLM начинаются ключевые пункты.
KEY_POINTS_MARKER = "КЛЮЧЕВЫЕ ПУНКТЫ:"

#: Шаблон пункта списка: «- текст», «* текст» или «1. текст».
_POINT_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$")

#: Длина тела элемента в промпте: полные тексты постов не нужны — модель сводит
#: заголовок и начало, а лишние токены только раздувают запрос.
PROMPT_BODY_MAX = 300


class SummarizeError(RuntimeError):
    """Стиль или длина сводки не поддержаны."""


def normalize_style(style: str) -> str:
    """Стиль сводки: пустая строка — значение по умолчанию, чужой стиль — ошибка."""
    value = (style or "").strip().lower()
    if not value:
        return config.SUMMARY_STYLE_DEFAULT
    if value not in config.SUMMARY_STYLES:
        raise SummarizeError(
            f"Стиль «{style}» не поддержан. Допустимы: "
            + ", ".join(config.SUMMARY_STYLES)
        )
    return value


def clamp_max_length(max_length: int) -> int:
    """Длина сводки в границах ``SUMMARY_MAX_LENGTH_MIN``..``SUMMARY_MAX_LENGTH_MAX``."""
    try:
        value = int(max_length)
    except (TypeError, ValueError):
        value = config.SUMMARY_DEFAULT_MAX_LENGTH
    return max(config.SUMMARY_MAX_LENGTH_MIN,
               min(value, config.SUMMARY_MAX_LENGTH_MAX))


def item_title(item: dict) -> str:
    """Заголовок элемента: ``title``, иначе начало ``content``, иначе сам словарь."""
    title = str(item.get("title") or "").strip()
    if title:
        return title
    body = str(item.get("content") or "").strip()
    if body:
        return body.splitlines()[0][:config.SEARCH_TITLE_MAX]
    return str(item)[:config.SEARCH_TITLE_MAX]


def item_body(item: dict) -> str:
    """Тело элемента: ``content``, иначе остальные поля словаря строкой."""
    body = str(item.get("content") or "").strip()
    if body:
        return body
    return str({key: value for key, value in item.items() if key != "title"})[:200]


def build_prompt(items: list[dict], style: str, max_length: int) -> list[dict]:
    """Собирает сообщения для DeepSeek: системная роль-редактор и список элементов.

    Промпт требует сначала текст сводки, потом строку-маркер ``КЛЮЧЕВЫЕ ПУНКТЫ:`` и
    пункты списком — по этому маркеру ``parse_key_points`` отделяет пункты от
    текста, не угадывая формат.
    """
    style_value = normalize_style(style)
    style_label = {
        "short": "одна короткая сводка",
        "detailed": "подробная сводка",
        "bullets": "сводка списком пунктов",
    }[style_value]
    length = clamp_max_length(max_length)
    system = (
        "Ты — редактор. Сделай сводку списка элементов на русском языке. "
        f"Стиль: {style_label}. Длина: до {length} символов. Сначала текст сводки, "
        f"затем строка '{KEY_POINTS_MARKER}' и пункты списком через '- '. "
        "Не выдумывай поля, которых нет."
    )
    lines = [
        f"{index}. {item_title(item)}\n{item_body(item)[:PROMPT_BODY_MAX]}"
        for index, item in enumerate(items[:config.SUMMARY_ITEMS_MAX], start=1)
    ]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_key_points(text: str, limit: int = config.SUMMARY_KEY_POINTS_MAX) -> list[str]:
    """Ключевые пункты из ответа LLM: строки списка после маркера.

    Без маркера пунктов нет: пустой список честнее, чем список из случайных строк
    ответа (``parse_key_points("просто текст") == []``).
    """
    if not text or KEY_POINTS_MARKER not in text:
        return []
    tail = text.split(KEY_POINTS_MARKER, 1)[1]
    points: list[str] = []
    for line in tail.splitlines():
        match = _POINT_RE.match(line)
        if match:
            points.append(match.group(1).strip())
        if len(points) >= limit:
            break
    return points


def summary_text_of(text: str, max_length: int) -> str:
    """Текст сводки из ответа LLM: до маркера ключевых пунктов, обрезанный по длине."""
    head = text.split(KEY_POINTS_MARKER, 1)[0] if text else ""
    return head.strip()[:clamp_max_length(max_length)]


def aggregate_summary(items: list[dict], style: str, max_length: int) -> SummaryResult:
    """Сводка без LLM: заголовки элементов по стилю (движок ``aggregation``)."""
    style_value = normalize_style(style)
    length = clamp_max_length(max_length)
    titles = [item_title(item) for item in items]
    if style_value == "short":
        head = f"Найдено {len(items)} элементов. Первые: " + "; ".join(titles[:3])
    elif style_value == "detailed":
        head = "\n".join(
            f"{index}. {title}"
            for index, title in enumerate(titles[:config.SUMMARY_LINES_MAX], start=1)
        )
    else:
        head = "\n".join(f"- {title}" for title in titles[:config.SUMMARY_LINES_MAX])
    return SummaryResult(
        summary_text=head[:length],
        key_points=titles[:config.SUMMARY_KEY_POINTS_MAX],
        total_items=len(items),
        style_used=style_value,
        engine="aggregation",
    )


def llm_summary(text: str, items: list[dict], style: str,
                max_length: int) -> SummaryResult:
    """Сводка из ответа LLM: текст до маркера, пункты после него (движок ``llm``)."""
    return SummaryResult(
        summary_text=summary_text_of(text, max_length),
        key_points=parse_key_points(text),
        total_items=len(items),
        style_used=normalize_style(style),
        engine="llm",
    )


def items_payload(items: Any) -> list[dict]:
    """Приводит аргумент ``items`` к списку словарей (чужие значения — строками)."""
    if not isinstance(items, list):
        raise SummarizeError("Аргумент items должен быть массивом элементов")
    result: list[dict] = []
    for item in items[:config.SUMMARY_ITEMS_MAX]:
        if isinstance(item, dict):
            result.append(item)
        else:
            result.append({"title": str(item)[:config.SEARCH_TITLE_MAX]})
    return result
