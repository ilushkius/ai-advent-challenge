"""Инструмент ``extract_keywords``: ключевые слова текста по частоте.

Разбор простой и предсказуемый: текст приводится к нижнему регистру, слова
вырезаются шаблоном ``TOKEN_RE``, служебные (``config.STOPWORDS``) выбрасываются,
остальные считаются. Частое слово — ключевое; при равной частоте порядок
алфавитный, поэтому при одном и том же тексте ответ всегда один и тот же (это
важно: результат едет в журнал шагов оркестрации и в отчёт прогона).
"""
from __future__ import annotations

import re
from typing import List

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.data_server import config
from mcp_servers.data_server.schemas import KeywordsResult

#: Токен текста: первый символ — буква или цифра, дальше не меньше двух знаков;
#: дефис и подчёркивание внутри слова сохраняются («iso-8601», «чанкинг-схема»).
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_-]{2,}")


def tokenize(text: str) -> List[str]:
    """Слова текста в нижнем регистре, в порядке появления."""
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def keyword_counts(text: str,
                   top_n: int = config.KEYWORDS_TOP_N) -> List[tuple[str, int]]:
    """Частоты слов без служебных: от частых к редким, при равенстве — по алфавиту."""
    counts: dict[str, int] = {}
    for token in tokenize(text):
        if token in config.STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:max(0, int(top_n))]


def clamp_limit(limit) -> int:
    """Сколько слов вернуть: в границах ``KEYWORDS_MIN``..``KEYWORDS_MAX``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = config.KEYWORDS_DEFAULT
    return max(config.KEYWORDS_MIN, min(value, config.KEYWORDS_MAX))


def extract_keywords(text: str, limit: int = config.KEYWORDS_DEFAULT) -> KeywordsResult:
    """Возвращает ключевые слова текста по частоте употребления.

    Параметры: text — текст для разбора (заголовки и тела найденных элементов,
    склеенные в одну строку); limit — сколько слов вернуть (от 1 до 20, по
    умолчанию 7).

    Возвращает объект с полями keywords (слова в нижнем регистре: сначала самые
    частые, при равной частоте — по алфавиту), count (сколько слов вернулось),
    joined (те же слова одной строкой через запятую) и engine (``frequency``).
    Пример: extract_keywords(text="RAG — поиск, RAG — генерация", limit=5).

    Если текст пуст или состоит из пробелов, инструмент сообщает об ошибке: без
    текста выделять нечего.
    """
    if not (text or "").strip():
        raise ToolError("Нет текста для выделения ключевых слов")
    words = [word for word, _ in keyword_counts(text)[:clamp_limit(limit)]]
    return KeywordsResult(
        keywords=words,
        count=len(words),
        joined=", ".join(words),
        engine="frequency",
    )
