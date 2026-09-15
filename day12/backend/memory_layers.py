"""Данные и чистые помощники трёх слоёв памяти агента (день 11).

Модуль не знает ни про LLM, ни про транспорт — здесь только данные и чистые
функции, которые тестируются без БД:

- ``MemoryCategory`` — ``Enum`` категорий долговременного слоя (значение —
  строка, попадающая в БД/API/UI без маппинга) и ``AVAILABLE_CATEGORIES``;
- ``CATEGORY_HINTS`` / ``STOPWORDS`` — подстроки категорий и стоп-слова отбора;
- ``WORKING_HEADER`` / ``LONG_TERM_HEADER`` — заголовки блоков памяти;
- ``query_keywords`` / ``render_working_block`` / ``render_long_term_block`` —
  отбор релевантных записей и текстовая форма блоков для системного сообщения;
- ``_short_term_dict`` / ``_working_dict`` / ``_long_term_dict`` — ORM-строка →
  словарь для API/UI.

Хранилищем слоёв заведует ``MemoryManager`` (``backend/memory.py``): он
импортирует эти имена отсюда и реэкспортирует их для остальных модулей дня.
"""
import re
from enum import Enum
from typing import List

from .database import LongTermMemory, ShortTermMessage, WorkingMemory


class MemoryCategory(str, Enum):
    """Категории долговременной памяти (значение — строка для БД/API/UI)."""

    PROFILE = "profile"        # профиль пользователя
    PREFERENCE = "preference"  # устойчивые предпочтения
    DECISION = "decision"      # важные решения
    KNOWLEDGE = "knowledge"    # знания


AVAILABLE_CATEGORIES = tuple(item.value for item in MemoryCategory)

# Подстроки, по которым запрос «узнаёт» категорию долговременной памяти
# («расскажи про мой профиль» → записи категории profile).
CATEGORY_HINTS = {
    MemoryCategory.PROFILE.value: ("профил",),
    MemoryCategory.PREFERENCE.value: ("предпочт",),
    MemoryCategory.DECISION.value: ("решен", "решили"),
    MemoryCategory.KNOWLEDGE.value: ("знан",),
}

# Стоп-слова для отбора релевантных записей долговременной памяти.
STOPWORDS = frozenset({
    "что", "как", "для", "это", "все", "при", "или", "его", "ещё", "еще",
    "the", "and", "for", "with", "that", "this",
})

WORKING_HEADER = (
    "Рабочая память (данные текущей задачи, используй как опорные; при "
    "противоречии важнее свежая реплика):"
)
LONG_TERM_HEADER = (
    "Долговременная память (профиль, предпочтения, решения, знания — "
    "устойчивые данные о пользователе):"
)


def query_keywords(text: str) -> List[str]:
    """Ключевые слова запроса: нижний регистр, слова длиной >= 3 без стоп-слов.

    Чистая функция: одинаковый вход всегда даёт одинаковый результат, порядок
    слов сохраняется, дубликаты убираются.
    """
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower())
    result: List[str] = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in result:
            continue
        result.append(word)
    return result


def render_working_block(entries: List[dict]) -> str:
    """Текст блока рабочей памяти для системного сообщения.

    Пустой список → пустая строка (блок в системное сообщение не добавляется).
    Записи печатаются по алфавиту ключей: текст детерминирован.
    """
    if not entries:
        return ""
    lines = [WORKING_HEADER]
    for entry in sorted(entries, key=lambda item: item["key"]):
        lines.append(f"- {entry['key']}: {entry['value']}")
    return "\n".join(lines)


def render_long_term_block(entries: List[dict]) -> str:
    """Текст блока долговременной памяти (с категорией и уверенностью).

    Пустой список → пустая строка. Сортировка по (category, key) — текст
    детерминирован. ``confidence`` печатается без хвостовых нулей (``:g``).
    """
    if not entries:
        return ""
    lines = [LONG_TERM_HEADER]
    ordered = sorted(entries, key=lambda item: (item["category"], item["key"]))
    for entry in ordered:
        confidence = float(entry.get("confidence", 1.0))
        lines.append(
            f"- [{entry['category']}] {entry['key']}: {entry['value']} "
            f"(уверенность {confidence:g})"
        )
    return "\n".join(lines)


def _short_term_dict(row: ShortTermMessage) -> dict:
    """ORM-строка краткосрочного слоя → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at,
    }


def _working_dict(row: WorkingMemory) -> dict:
    """ORM-строка рабочей памяти → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "task_id": row.task_id,
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at,
    }


def _long_term_dict(row: LongTermMemory) -> dict:
    """ORM-строка долговременной памяти → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "category": row.category,
        "key": row.key,
        "value": row.value,
        "confidence": row.confidence,
        "updated_at": row.updated_at,
    }
