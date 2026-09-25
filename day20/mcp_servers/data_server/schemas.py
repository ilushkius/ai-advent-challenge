"""Структуры ответов инструментов сервера обработки данных (``TypedDict``).

Аннотация возврата инструмента — источник ``outputSchema`` в каталоге
``tools/list``: MCP SDK разбирает её и публикует клиенту, а ``structuredContent``
ответа становится самим словарём. Поэтому поля описаны здесь один раз, а тела
инструментов только собирают такой словарь — никаких склеенных руками строк.

Поля плоские и без вложенных объектов: результат едет в модель и в таблицу шагов
оркестрации, где длинные вложенности только мешают читать журнал.
"""
from typing import Any, Dict, List, TypedDict


class SummaryResult(TypedDict):
    """Сводка списка элементов: текст, ключевые пункты, объём и способ сборки."""

    summary_text: str
    key_points: List[str]
    total_items: int
    style_used: str
    engine: str               # "llm" | "aggregation"


class KeywordsResult(TypedDict):
    """Ключевые слова текста: список, их число и та же строка через запятую."""

    keywords: List[str]
    count: int
    joined: str
    engine: str               # "frequency"


class FilterResult(TypedDict):
    """Отбор по дате: оставленные записи, счётчики и границы отбора."""

    items: List[Dict[str, Any]]
    count: int
    skipped: int              # записи без разобранной даты
    field: str
    since: str
    until: str


class AggregateGroup(TypedDict):
    """Одна группа агрегации: ключ группировки и значение метрики."""

    key: str
    value: float


class AggregateResult(TypedDict):
    """Группировка записей: группы, их число, метрика и поле группировки."""

    groups: List[AggregateGroup]
    count: int
    metric: str
    group_by: str
