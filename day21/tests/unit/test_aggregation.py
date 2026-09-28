"""Агрегация накопленных записей в сводку (день 18).

Проверяются правила сводки, а не её форматирование: какие поля становятся
числовыми (и почему ``bool`` в них не попадает), как считаются уникальные значения,
что попадает в метрики при пустом периоде и как работает ограничение числа полей.
Текст сводки проверяется по фактам — имя, период, число записей, — а не по буквам.
"""
from datetime import datetime, timedelta, timezone

from backend.core import config
from backend.domain.aggregation import (
    EMPTY_PERIOD_TEXT,
    aggregate_records,
    flatten_payload,
)

START = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=20)


def _rows(payload, name="posts", count=1):
    """Строки ``collected_data``: одна запись на элемент (имя — имя сбора)."""
    return [{"name": name, "payload": payload, "collected_at": START}
            for _ in range(count)]


def test_numeric_fields_get_avg_min_max():
    """Числовые поля получают count, среднее, минимум и максимум."""
    rows = _rows([{"id": 1, "userId": 10}, {"id": 3, "userId": 20}])
    result = aggregate_records(rows, START, END, name="posts")
    assert result.total_records == 1
    numeric = result.key_metrics["numeric"]
    assert numeric["id"] == {"count": 2, "avg": 2.0, "min": 1, "max": 3}
    assert numeric["userId"]["max"] == 20


def test_nested_payload_flattens_by_key_name():
    """Вложенные объекты раскладываются по именам ключей, без индексов."""
    values: dict = {}
    flatten_payload("posts", [{"id": 1, "nested": {"score": 5}}, {"id": 2, "nested": {"score": 7}}],
                    values)
    assert values["id"] == [1, 2]
    assert values["score"] == [5, 7]
    assert "0" not in values and "nested" not in values


def test_boolean_is_not_a_numeric_field():
    """``bool`` — подкласс ``int``, но числовым полем не считается."""
    rows = _rows([{"ok": True}, {"ok": False}])
    result = aggregate_records(rows, START, END, name="posts")
    assert "ok" not in result.key_metrics["numeric"]
    assert result.key_metrics["categorical"]["ok"]["unique"] == 2


def test_categorical_fields_count_unique_and_samples():
    """Строковые поля дают число уникальных значений и примеры."""
    rows = _rows([{"title": "a"}, {"title": "b"}, {"title": "a"}])
    result = aggregate_records(rows, START, END, name="posts")
    categorical = result.key_metrics["categorical"]["title"]
    assert categorical["unique"] == 2
    assert categorical["samples"] == ["a", "b"]


def test_sources_and_payload_types_counted():
    """Метрики видно по источникам: сколько записей пришло от каждого имени сбора."""
    rows = _rows([{"id": 1}], name="posts") + _rows([{"id": 2}], name="users")
    result = aggregate_records(rows, START, END, name="posts")
    assert result.key_metrics["sources"] == {"posts": 1, "users": 1}
    assert result.key_metrics["payload_types"]["list"] == 2
    assert result.key_metrics["period_seconds"] == 20


def test_empty_period_still_produces_a_summary():
    """Пустой период — не ошибка: сводка сохранена и прямо говорит, что данных нет."""
    result = aggregate_records([], START, END, name="posts")
    assert result.total_records == 0
    assert result.key_metrics["numeric"] == {}
    assert result.key_metrics["sources"] == {}
    assert EMPTY_PERIOD_TEXT in result.summary_text
    assert "Записей собрано: 0" in result.summary_text


def test_summary_text_names_period_and_counts():
    """Текст сводки называет сбор, период, число записей и метрики полей."""
    rows = _rows([{"id": 1, "title": "a"}, {"id": 3, "title": "b"}])
    result = aggregate_records(rows, START, END, name="posts")
    text = result.summary_text
    assert "posts" in text
    assert "2026-09-23 10:00:00" in text and "10:00:20" in text
    assert "Записей собрано: 1" in text
    assert "id — 2 значений, среднее 2.0, мин 1, макс 3" in text
    assert "title — 2 уникальных" in text


def test_field_count_is_limited():
    """Число полей в метриках ограничено: сводка не растёт вместе с payload."""
    payload = {f"field_{index}": index for index in range(50)}
    result = aggregate_records(_rows([payload]), START, END, name="posts", max_fields=3)
    assert len(result.key_metrics["numeric"]) == 3


def test_samples_are_limited_and_clipped():
    """Примеры значений ограничены по числу и по длине."""
    rows = _rows([{"title": "x" * 200}] + [{"title": f"t{index}"} for index in range(10)])
    result = aggregate_records(rows, START, END, name="posts", samples=2)
    samples = result.key_metrics["categorical"]["title"]["samples"]
    assert len(samples) == 2
    assert all(len(item) <= 41 for item in samples)


def test_default_limits_come_from_config():
    """Без явных границ агрегация берёт их из config дня."""
    payload = {f"f{index:03d}": index for index in range(config.AGGREGATION_MAX_FIELDS + 5)}
    result = aggregate_records(_rows([payload]), START, END, name="posts")
    assert len(result.key_metrics["numeric"]) == config.AGGREGATION_MAX_FIELDS
