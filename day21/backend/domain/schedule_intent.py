"""Распознавание реплик трёх инструментов планировщика (день 18).

Чистая эвристика «по тексту», как ``mcp_intent`` дня 17: по ключевым словам
реплики определяется, какой инструмент планировщика нужен, а из самой реплики
достаются его аргументы (задержка, период, адрес, текст напоминания). Результат —
``ScheduleIntent`` или ``None``; реплика ничего не делает, вызов выполняет
``MCPToolRunner`` (``backend/services``).

Почему правила, а не модель: вызов инструмента оставляет побочный эффект —
задачу в фоновом планировщике. Цена ошибки выше, чем у ответа текстом, поэтому
инструмент вызывается только по явным словам реплики, а не по решению LLM.

Таблица `SCHEDULE_INTENT_RULES` — единственный источник правды о распознавании;
порядок правил ЗАДАН ПРИОРИТЕТОМ. Правило, чей инструмент не предлагает
подключённый сервер, пропускается: обещать вызов «своего» инструмента у чужого
сервера нельзя. Так же пропускается правило, у которого в реплике не нашлось
обязательных данных (`collect_data` без адреса — не вызов, а обычный ответ).

Время читается двумя оборотами: «через 30 секунд» (задержка разового запуска) и
«каждые 10 секунд» / «за последний час» (период). Совпадение фразы — по границе
слова, как в ``mcp_intent``: «напомни», «напомнит», «напоминание» — одно правило,
а «напоминающий» — уже нет.

Модуль чистый: ``re``/``dataclasses``/``urllib.parse`` и ``schedule_spec``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

from ..core import config
from .schedule_spec import COLLECT_DATA, GENERATE_SUMMARY, SCHEDULE_REMINDER

#: Текст напоминания, когда в реплике остались одни служебные слова.
FALLBACK_REMINDER_TEXT = "напоминание"

#: Период по умолчанию, когда реплика не назвала его числом.
DEFAULT_REMINDER_DELAY = 60
DEFAULT_COLLECT_INTERVAL = 60
DEFAULT_SUMMARY_INTERVAL = 3600


@dataclass(frozen=True, slots=True)
class ScheduleIntentRule:
    """Правило распознавания: какой инструмент планировщика звать по этим словам."""

    tool: str
    phrases: tuple[str, ...]


#: Правила в порядке приоритета. Фразы — литеральные начала слов: хвост окончания
#: до трёх букв допускает шаблон, а не данные (морфология — не список исключений).
SCHEDULE_INTENT_RULES: tuple[ScheduleIntentRule, ...] = (
    ScheduleIntentRule(
        tool=GENERATE_SUMMARY,
        phrases=("сводк", "summary", "покажи сводк", "сводку за"),
    ),
    ScheduleIntentRule(
        tool=COLLECT_DATA,
        phrases=("собирай данные", "сбор данных", "собирай с ", "собирать данные",
                 "собирай информаци"),
    ),
    ScheduleIntentRule(
        tool=SCHEDULE_REMINDER,
        phrases=("напомни", "напоминание", "напомнить"),
    ),
)

#: Слова времени: секунды, минуты, часы (в любой падежной форме).
_TIME_WORD = r"(?:секунд[а-яё]*|секунд|сек|минут[а-яё]*|минут|мин|час[а-яё]*|час|ч)"

#: «N секунд» с необязательным числом: «за последний час» — тоже единица времени.
_DURATION_BODY = r"(\d+)?\s*(?<![а-яё])(" + _TIME_WORD + r")(?![а-яё])"

#: Задержка разового запуска: «через 30 секунд», «через 5 минут».
_DELAY = re.compile(r"через\s+" + _DURATION_BODY)

#: Периодический запуск: «каждые 10 секунд», «каждые 5 минут».
_INTERVAL = re.compile(r"кажд[а-яё]*\s+" + _DURATION_BODY)

#: Период сводки: «за последний час», «за последние 5 минут», «за минуту».
_PERIOD = re.compile(r"за\s+(?:последн[а-яё]*\s+)?" + _DURATION_BODY)

#: Адрес источника: первый http(s)-адрес реплики (хвостовая пунктуация снимается).
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)

#: Служебные слова напоминания, которые в текст самого напоминания не попадают.
_REMINDER_TRIGGER = re.compile(r"(?<![а-яё])(?:напомни|напомнить|напоминание)[а-яё]{0,3}"
                              r"(?![а-яё])")
_REMINDER_ME = re.compile(r"(?<![а-яё])мне(?![а-яё])")


@dataclass(frozen=True, slots=True)
class ScheduleIntent:
    """Что решила эвристика: инструмент планировщика, аргументы и сработавшая фраза."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    phrase: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Словарь намерения: аргументы копируются, чтобы отчёт не менял план."""
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "phrase": self.phrase,
        }


def _pattern(phrase: str) -> re.Pattern[str]:
    """Шаблон фразы: граница слова слева, до трёх букв окончания справа."""
    return re.compile(r"(?<![а-яёa-z])" + re.escape(phrase) + r"[а-яё]{0,3}(?![а-яёa-z])")


_PATTERNS: tuple[tuple[ScheduleIntentRule, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule, tuple(_pattern(phrase) for phrase in rule.phrases))
    for rule in SCHEDULE_INTENT_RULES
)


def _unit_seconds(word: str) -> int:
    """Сколько секунд в названной единице времени."""
    name = (word or "").lower()
    if name.startswith("сек"):
        return 1
    if name.startswith("мин"):
        return 60
    return 3600


def _seconds_from(match: Optional[re.Match[str]],
                  default: int = 1) -> Optional[int]:
    """Секунды из найденного оборота (``None`` — оборота в тексте нет)."""
    if match is None:
        return None
    count = int(match.group(1) or default)
    return count * _unit_seconds(match.group(2))


def parse_delay_seconds(text: str) -> Optional[int]:
    """Задержка разового запуска: «через 30 секунд» → 30, «через 5 минут» → 300."""
    lowered = (text or "").lower()
    return _seconds_from(_DELAY.search(lowered))


def parse_interval_seconds(text: str) -> Optional[int]:
    """Период: «каждые 10 секунд» → 10, «каждые 5 минут» → 300."""
    lowered = (text or "").lower()
    return _seconds_from(_INTERVAL.search(lowered))


def parse_period_seconds(text: str) -> Optional[int]:
    """Период сводки: «за последний час» → 3600, «за последние 5 минут» → 300."""
    lowered = (text or "").lower()
    return _seconds_from(_PERIOD.search(lowered))


def extract_url(text: str) -> Optional[str]:
    """Первый http(s)-адрес реплики (``None`` — адреса нет)."""
    match = _URL.search(text or "")
    if match is None:
        return None
    return match.group().rstrip(".,;:!?")


def classify_schedule_intent(text: str,
                             available_tools: Sequence[str]) -> Optional[ScheduleIntent]:
    """Намерение планировщика по реплике: инструмент дня, который есть в каталоге."""
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    for rule, patterns in _PATTERNS:
        if rule.tool not in available_tools:
            continue
        for phrase, pattern in zip(rule.phrases, patterns):
            if not pattern.search(lowered):
                continue
            arguments = _arguments_for(rule.tool, text)
            if arguments is None:
                continue
            return ScheduleIntent(tool=rule.tool, arguments=arguments, phrase=phrase)
    return None


def _arguments_for(tool: str, text: str) -> Optional[dict[str, Any]]:
    """Аргументы инструмента из реплики (``None`` — обязательных данных нет)."""
    if tool == COLLECT_DATA:
        url = extract_url(text)
        if url is None:
            return None
        interval = parse_interval_seconds(text) or DEFAULT_COLLECT_INTERVAL
        return {"source_url": url, "interval_seconds": interval, "name": url_name(url)}
    if tool == GENERATE_SUMMARY:
        interval = (parse_interval_seconds(text) or parse_period_seconds(text)
                    or DEFAULT_SUMMARY_INTERVAL)
        return {"name": "данные", "interval_seconds": interval}
    if tool == SCHEDULE_REMINDER:
        delay = parse_delay_seconds(text) or DEFAULT_REMINDER_DELAY
        return {"text": reminder_text(text), "delay_seconds": delay}
    return None


def reminder_text(text: str) -> str:
    """Текст напоминания: реплика без служебных слов и оборота времени.

    «напомни мне через 5 минут проверить почту» → «проверить почту». Если после
    чистки не осталось ничего (реплика была одной командой без содержания),
    возвращается слово-заглушка: пустой текст напоминания бессмыслен.
    """
    lowered = (text or "").lower()
    cleaned = _DELAY.sub(" ", lowered)
    cleaned = _REMINDER_TRIGGER.sub(" ", cleaned)
    cleaned = _REMINDER_ME.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t,.:;!?—-")
    return (cleaned[:config.REMINDER_TEXT_MAX] or FALLBACK_REMINDER_TEXT)


def url_name(url: str) -> str:
    """Имя сбора по адресу: последний сегмент пути (``/posts`` → ``posts``).

    Без сегмента пути берётся хост: у адреса ``https://example.com`` другого имени
    нет, а пустое имя сломало бы запись в ``collected_data``.
    """
    parsed = urlparse(url)
    segments = [item for item in (parsed.path or "").split("/") if item]
    name = segments[-1] if segments else (parsed.netloc or "данные")
    if "." in name:
        name = name.split(".")[0] or parsed.netloc or "данные"
    return name[:config.SCHEDULE_NAME_MAX]
