"""Извлечение фактов из реплик диалога (день 11): чистая функция без побочных эффектов.

Что это.
    Для стратегии `sticky_facts` нужен способ превращать реплики диалога в набор
    «ключ → значение». Здесь живёт только чистая функция `extract_facts` — без
    HTTP, БД и UI (по конвенции проекта чистая арифметика выносится отдельно и
    покрывается тестами).

    Экстрактор эвристический: он ищет в тексте явные записи вида
    `ключ: значение`, `ключ = значение` и `ключ — значение` (по строке текста).
    Это осознанный компромисс: детерминированная эвристика работает офлайн и
    предсказуемо, а LLM-экстракция фактов потребовала бы ключа API и отдельного
    вызова на каждый ход. Факты, которые пользователь записывает явно (имя,
    бюджет, срок, стек, ограничение), эвристика ловит стабильно.

    Ключи нормализуются (нижний регистр, схлопывание пробелов), чтобы «Бюджет»
    и «бюджет» обновляли один факт; значения обрезаются по краям. Множественные
    факты в одной строке разделяются символом `;`.

Как запустить.
    Только стандартная библиотека, побочных эффектов на импорте нет:

        # из папки day11
        python -m pytest -q tests/test_fact_extractor.py

    Пример:

        extract_facts("Имя: Иван; бюджет = 5000 рублей")
        # {"имя": "Иван", "бюджет": "5000 рублей"}
"""

from __future__ import annotations

import re

__all__ = ["extract_facts", "normalize_key", "merge_facts"]

# Разделители «ключ <sep> значение». Дефис/тире экранированы и не перехватывают
# знак минус внутри чисел: для «бюджет = 5000-1000» приоритет у «=».
_KEY_SEP = r"\s*(?:=|:)\s*"
_DASH_SEP = r"\s*(?:—|–|-\s)\s*"

# Ключ — непустой фрагмент без разделителя, до 80 символов; значение — остаток.
_LINE_PATTERNS = [
    re.compile(rf"^(?P<key>[^=:—–\n]{{1,80}}?){_KEY_SEP}(?P<value>.*)$"),
    re.compile(rf"^(?P<key>[^=:—–\n]{{1,80}}?){_DASH_SEP}(?P<value>.*)$"),
]

# Для разбивки строки на под-факты по точке с запятой (вне скобок).
_SPLIT_RE = re.compile(r";")


def normalize_key(key: str) -> str:
    """Нормализует ключ: нижний регистр, схлопывание внутренних пробелов."""
    return re.sub(r"\s+", " ", key.strip().lower())


def _clean_value(value: str) -> str:
    """Обрезает значение по краям и убирает висную пунктуацию-обёртку."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'“”":
        value = value[1:-1].strip()
    return value


def extract_facts(text: str) -> dict[str, str]:
    """Достаёт факты «ключ → значение» из текста.

    Возвращает словарь, где ключ нормализован, а значение обрезано. Строки без
    распознанного разделителя игнорируются. Пустой/нестрочный вход — пустой
    словарь (не ошибка): отсутствие фактов в реплике — норма.
    """
    if not text or not isinstance(text, str):
        return {}
    facts: dict[str, str] = {}
    for line in text.splitlines():
        for chunk in _SPLIT_RE.split(line):
            chunk = chunk.strip()
            if not chunk:
                continue
            for pattern in _LINE_PATTERNS:
                match = pattern.match(chunk)
                if match:
                    key = normalize_key(match.group("key"))
                    value = _clean_value(match.group("value"))
                    if key and value:
                        facts[key] = value
                    break
    return facts


def merge_facts(existing: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Сливает факты: новые значения перекрывают существующие по ключу."""
    merged = dict(existing)
    merged.update(new)
    return merged
