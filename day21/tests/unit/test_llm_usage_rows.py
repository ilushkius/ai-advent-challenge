"""Проекция ORM-строки журнала расходов в словарь (день 21).

Словарь — контракт между хранилищем, вкладкой «Расходы» и отчётом об оптимизации:
ключи перечислены тестом поимённо, потому что лишнее или потерянное поле ломает
интерфейс молча (потребители читают словарь по ключам, а не по схеме).

Строка ORM создаётся здесь без сессии: проекция обязана работать и на объекте,
который ещё не записан (сервис показывает строку сразу после `add`), поэтому
незаполненные колонки проверяются как есть — нулями.
"""
from datetime import datetime, timezone

from backend.models.llm_usage import LLMUsage
from backend.storage.llm_usage_rows import llm_usage_dict

#: Полный набор ключей проекции (порядок — как в словаре хранилища).
EXPECTED_KEYS = [
    "id", "agent_id", "timestamp", "model", "prompt_tokens", "completion_tokens",
    "cache_hit_tokens", "cache_miss_tokens", "cost_estimate", "request_type",
    "created_at",
]


def _row(**overrides) -> LLMUsage:
    """Строка журнала со всеми заполненными полями (аргументы — точечные правки)."""
    values = {
        "id": 7,
        "agent_id": "agent-1",
        "timestamp": datetime(2026, 9, 27, 10, 30, tzinfo=timezone.utc),
        "model": "deepseek-chat",
        "prompt_tokens": 120,
        "completion_tokens": 40,
        "cache_hit_tokens": 100,
        "cache_miss_tokens": 20,
        "cost_estimate": 0.000321,
        "request_type": "chat",
        "created_at": datetime(2026, 9, 27, 10, 31, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return LLMUsage(**values)


def test_dict_has_exact_keys():
    """Проекция отдаёт ровно те ключи, на которые опираются интерфейс и отчёт."""
    assert list(llm_usage_dict(_row())) == EXPECTED_KEYS


def test_dict_carries_all_values():
    """Токены, кэш, цена и тип запроса переносятся без изменений."""
    record = llm_usage_dict(_row())
    assert record["id"] == 7
    assert record["agent_id"] == "agent-1"
    assert record["model"] == "deepseek-chat"
    assert record["prompt_tokens"] == 120
    assert record["completion_tokens"] == 40
    assert record["cache_hit_tokens"] == 100
    assert record["cache_miss_tokens"] == 20
    assert record["cost_estimate"] == 0.000321
    assert record["request_type"] == "chat"


def test_timestamps_are_iso_utc():
    """Обе метки времени — ISO-8601 в UTC: по ним фильтруется окно периода."""
    record = llm_usage_dict(_row())
    moment = datetime.fromisoformat(record["timestamp"])
    created = datetime.fromisoformat(record["created_at"])
    assert moment == datetime(2026, 9, 27, 10, 30, tzinfo=timezone.utc)
    assert moment.utcoffset() == timezone.utc.utcoffset(None)
    assert created.utcoffset() == timezone.utc.utcoffset(None)


def test_naive_stamp_is_read_as_utc():
    """Наивная метка из SQLite считается UTC, а не локальным временем.

    SQLite не хранит часовой пояс: без этого правила одна и та же строка читалась бы
    с разным сдвигом в зависимости от машины, и окно `day` на границе суток
    отсекало бы не те записи.
    """
    record = llm_usage_dict(_row(timestamp=datetime(2026, 9, 27, 10, 30)))
    assert record["timestamp"].endswith("+00:00")
    assert record["timestamp"].startswith("2026-09-27T10:30")


def test_unset_columns_are_zeroed():
    """Незаполненные колонки отдаются нулями, а не ``None``: статистика их суммирует."""
    record = llm_usage_dict(_row(id=None, agent_id=None, timestamp=None,
                                prompt_tokens=None, completion_tokens=None,
                                cache_hit_tokens=None, cache_miss_tokens=None,
                                cost_estimate=None, created_at=None))
    assert record["id"] is None
    assert record["agent_id"] is None
    assert record["timestamp"] is None
    assert record["created_at"] is None
    assert record["prompt_tokens"] == 0
    assert record["completion_tokens"] == 0
    assert record["cache_hit_tokens"] == 0
    assert record["cache_miss_tokens"] == 0
    assert record["cost_estimate"] == 0.0


def test_defaults_of_fresh_row_are_zeroed():
    """Только что созданная (не записанная) строка: числа — нули, строки — ``None``."""
    record = llm_usage_dict(LLMUsage(model="deepseek-chat", request_type="chat"))
    assert record["model"] == "deepseek-chat"
    assert record["request_type"] == "chat"
    assert record["agent_id"] is None
    assert record["prompt_tokens"] == 0
    assert record["completion_tokens"] == 0
    assert record["cache_hit_tokens"] == 0
    assert record["cache_miss_tokens"] == 0
    assert record["cost_estimate"] == 0.0


def test_projection_is_a_copy():
    """Правка словаря не меняет строку ORM, а два вызова дают разные словари.

    Словарь уходит в интерфейс и в отчёт, где его дописывают (подписи, проценты);
    общая ссылка означала бы, что оформление портит данные журнала.
    """
    row = _row()
    first = llm_usage_dict(row)
    second = llm_usage_dict(row)
    assert first == second and first is not second
    first["model"] = "подменённая"
    first["prompt_tokens"] = 0
    assert row.model == "deepseek-chat"
    assert row.prompt_tokens == 120
