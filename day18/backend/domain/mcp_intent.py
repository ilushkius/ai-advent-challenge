"""Распознавание запроса к MCP-инструменту по реплике пользователя (день 17).

Чистая эвристика «по тексту»: по ключевым словам реплики определяется, какой
инструмент нужен и с каким номером его звать. Результат — ``MCPToolCallPlan``
(инструмент, аргументы и сработавшая фраза) или ``None``; сама реплика ничего не
делает, вызов выполняет ``MCPToolRunner`` (``backend/services``).

Как читается таблица.
    ``INTENT_RULES`` — единственный источник правды о распознавании, и порядок
    правил ЗАДАН ПРИОРИТЕТОМ: более специфичное правило идёт раньше. Поэтому
    «посты пользователя 2» становится ``list_user_posts``, а не ``get_user``,
    хотя слова «пользователя» достаточно для второго правила.

    Совпадение фразы — по границе слова: слева ``(?<![а-яёa-z])`` исключает
    «непользователь», справа допускается до трёх букв окончания, поэтому
    «пользователя», «пользователю», «пользователей» — одно и то же правило, а
    «пользовательский» — уже нет.

Номер аргумента.
    Берётся первое число в реплике: «пост 3» → ``{"post_id": 3}». Номера нет —
    аргументы пусты, и решает уже допуск вызова (``admission_reason``): он скажет,
    что обязательный аргумент не указан, и подскажет формат ``POST /mcp/call``.

Как запустить.
    Модуль чистый: ``enum`` не нужен даже — только ``re`` и ``dataclasses``.
    Проверяется тестами:

        # из папки day18
        uv run pytest -q tests/unit/test_mcp_intent.py
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .schedule_intent import classify_schedule_intent

#: Слова про инструмент в реплике: имя инструмента передаётся строкой, потому что
#: каталог сервера — данные, а не константа дня.
TOOL_GET_USER = "get_user"
TOOL_GET_POST = "get_post"
TOOL_LIST_USER_POSTS = "list_user_posts"


@dataclass(frozen=True, slots=True)
class ToolIntentRule:
    """Правило распознавания: какой инструмент и каким аргументом его звать."""

    tool: str
    phrases: tuple[str, ...]
    argument: str


#: Таблица правил в порядке приоритета. Фразы — литеральные начала слов: хвост
#: окончания до трёх букв допускает шаблон, а не данные (морфология — не список
#: исключений). Пары «посты … пользователя» перечислены обе: с предлогом «у» и
#: без него.
INTENT_RULES: tuple[ToolIntentRule, ...] = (
    ToolIntentRule(
        tool=TOOL_LIST_USER_POSTS,
        phrases=(
            "посты пользовател", "посты у пользовател",
            "постов пользовател", "постов у пользовател",
            "публикации пользовател", "публикации у пользовател",
        ),
        argument="user_id",
    ),
    ToolIntentRule(
        tool=TOOL_GET_USER,
        phrases=("пользовател", "юзер"),
        argument="user_id",
    ),
    ToolIntentRule(
        tool=TOOL_GET_POST,
        phrases=("пост", "публикаци", "статья", "запись"),
        argument="post_id",
    ),
)

#: Шаблон фразы: граница слова слева, до трёх букв окончания справа.
def _pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![а-яёa-z])" + re.escape(phrase) + r"[а-яё]{0,3}(?![а-яёa-z])")


_PATTERNS: tuple[tuple[ToolIntentRule, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule, tuple(_pattern(phrase) for phrase in rule.phrases))
    for rule in INTENT_RULES
)

#: Первое число в тексте — номер аргумента («пост 3» → 3).
_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class MCPToolCallPlan:
    """Что решила эвристика: инструмент, аргументы и сработавшая фраза.

    ``phrase`` нужен интерфейсу и логу: по нему видно, из-за какого слова был
    выбран инструмент, а не только «модель что-то вызвала».
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    phrase: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Словарь плана: аргументы копируются, чтобы правка отчёта не меняла план."""
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "phrase": self.phrase,
        }


def classify_tool_call(text: str,
                       available_tools: Sequence[str]) -> Optional[MCPToolCallPlan]:
    """План вызова по реплике: инструмент дня, который есть в каталоге сервера.

    ``available_tools`` — имена инструментов подключённого сервера. Правило, чей
    инструмент сервер не предлагает, пропускается: обещать в интерфейсе вызов
    «своего» инструмента у чужого сервера нельзя.

    Сначала реплику смотрит распознавание инструментов ПЛАНИРОВЩИКА дня 18
    (``classify_schedule_intent``): у трёх его инструментов свои аргументы
    (задержка, период, адрес), и их разбирает отдельный модуль. Найденное
    намерение возвращается тем же планом — вызывающему коду разницы нет.
    """
    intent = classify_schedule_intent(text, available_tools)
    if intent is not None:
        return MCPToolCallPlan(tool=intent.tool, arguments=intent.arguments,
                               phrase=intent.phrase)
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    for rule, patterns in _PATTERNS:
        if rule.tool not in available_tools:
            continue
        for phrase, pattern in zip(rule.phrases, patterns):
            if not pattern.search(lowered):
                continue
            found = _NUMBER.search(lowered)
            arguments = {rule.argument: int(found.group())} if found else {}
            return MCPToolCallPlan(tool=rule.tool, arguments=arguments, phrase=phrase)
    return None
