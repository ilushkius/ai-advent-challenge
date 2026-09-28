"""Тесты хранилища журнала расходов на LLM (день 21).

Проверяется то, ради чего журнал существует: строка запроса читается обратно со
всеми полями, свежие строки идут первыми, окно периода отсекает старое (и «all» не
отсекает ничего), а агрегаты дают те числа, которые видит вкладка «Расходы» и отчёт
об оптимизации. Сеть и модель здесь не нужны: стоимость приходит в строку уже
посчитанной.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.core import config
from backend.storage.llm_usage_store import LLMUsageStore


def _store(session_factory) -> LLMUsageStore:
    """Хранилище на временной БД теста."""
    return LLMUsageStore(session_factory=session_factory)


def _ago(days: int = 0, hours: int = 0) -> datetime:
    """Момент в прошлом: им проверяются окна периода."""
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours)


def _moment(record: dict) -> datetime:
    """Метка времени строки как aware-datetime."""
    return datetime.fromisoformat(record["timestamp"])


def test_add_writes_and_reads_all_fields(session_factory):
    """Строка запроса читается обратно целиком: токены, кэш, цена, тип, агент."""
    store = _store(session_factory)
    stamp = _ago(hours=2)
    written = store.add(model="deepseek-chat", request_type="chat", prompt_tokens=120,
                        completion_tokens=40, cache_hit_tokens=100,
                        cache_miss_tokens=20, cost_estimate=0.000321,
                        agent_id="agent-1", timestamp=stamp)
    assert written["id"] == 1
    assert written["model"] == "deepseek-chat"
    assert written["request_type"] == "chat"
    assert written["cost_estimate"] == 0.000321
    records = store.recent()
    assert len(records) == 1
    assert records[0] == written
    assert _moment(records[0]) == stamp


def test_add_defaults_to_now_when_stamp_missing(session_factory):
    """Без метки времени пишется момент записи: журнал без времени бесполезен."""
    store = _store(session_factory)
    written = store.add(model="deepseek-chat", request_type="chat", prompt_tokens=5)
    assert written["agent_id"] is None
    assert written["completion_tokens"] == 0
    assert written["cache_hit_tokens"] == 0
    assert written["cost_estimate"] == 0.0
    assert abs((_moment(written) - datetime.now(timezone.utc)).total_seconds()) < 60


def test_recent_is_newest_first_and_respects_limit(session_factory):
    """Вкладка «Расходы» читает конец журнала: свежие сверху, ``limit`` работает."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(hours=3))
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(hours=2))
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(hours=1))
    stamps = [_moment(record) for record in store.recent()]
    assert stamps == sorted(stamps, reverse=True)
    assert len(store.recent(limit=2)) == 2
    assert store.recent(limit=1)[0]["id"] == 3


def test_rows_and_recent_filter_by_agent(session_factory):
    """Фильтр по агенту отсекает чужие вызовы в обоих чтениях."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", agent_id="agent-1",
              timestamp=_ago(hours=2))
    store.add(model="deepseek-chat", request_type="summarize", agent_id="agent-2",
              timestamp=_ago(hours=1))
    store.add(model="deepseek-chat", request_type="classify", timestamp=_ago(hours=1))
    assert [record["agent_id"] for record in store.recent(agent_id="agent-1")] \
        == ["agent-1"]
    assert len(store.recent()) == 3
    assert [record["request_type"] for record in store.rows(agent_id="agent-2")] \
        == ["summarize"]
    assert len(store.stats(agent_id="agent-1")["by_type"]) == 1


def test_rows_are_ordered_by_time(session_factory):
    """Строки окна идут по возрастанию времени — по ним строится график по дням."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(hours=1))
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(hours=3))
    stamps = [_moment(record) for record in store.rows()]
    assert stamps == sorted(stamps)


def test_period_window_cuts_old_rows(session_factory):
    """``day`` отсекает вчерашнюю запись, ``week`` и ``all`` — нет."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(days=3))
    store.add(model="deepseek-chat", request_type="chat", timestamp=_ago(hours=1))
    assert len(store.rows(period="day")) == 1
    assert len(store.rows(period="week")) == 2
    assert len(store.rows(period="all")) == 2
    # Период по умолчанию — из конфига, а не «day»: сводка недели информативнее.
    assert len(store.rows()) == len(store.rows(period=config.LLM_USAGE_PERIOD_DEFAULT))
    assert store.stats(period="day")["requests"] == 1
    assert store.stats(period="all")["requests"] == 2


def test_unknown_period_raises(session_factory):
    """Опечатка в периоде — ошибка с перечнем допустимых, а не пустая сводка."""
    store = _store(session_factory)
    with pytest.raises(ValueError) as error:
        store.stats(period="year")
    message = str(error.value)
    assert "year" in message
    assert all(name in message for name in config.LLM_USAGE_PERIODS)


def test_empty_store_stats_are_zeroed(session_factory):
    """Пустой журнал даёт нули: вкладка «Расходы» рисуется и до первого запроса."""
    stats = _store(session_factory).stats(period="day")
    assert stats == {
        "period": "day", "requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "cache_hit_tokens": 0, "cache_miss_tokens": 0,
        "cache_hit_percent": 0.0, "cost_estimate": 0.0, "by_model": {}, "by_type": {},
        "daily": [],
    }


def test_stats_sums_tokens_and_cost(session_factory):
    """Суммы по окну: запросы, ввод, вывод, общий объём и стоимость."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=100,
              completion_tokens=10, cache_hit_tokens=80, cache_miss_tokens=20,
              cost_estimate=0.0001)
    store.add(model="deepseek-reasoner", request_type="summarize", prompt_tokens=200,
              completion_tokens=50, cache_hit_tokens=150, cache_miss_tokens=50,
              cost_estimate=0.0002)
    stats = store.stats()
    assert stats["period"] == config.LLM_USAGE_PERIOD_DEFAULT
    assert stats["requests"] == 2
    assert stats["prompt_tokens"] == 300
    assert stats["completion_tokens"] == 60
    assert stats["total_tokens"] == 360
    assert stats["cache_hit_tokens"] == 230
    assert stats["cache_miss_tokens"] == 70
    assert stats["cost_estimate"] == 0.0003


def test_cache_hit_percent_counts_share_of_prompt(session_factory):
    """Доля кэша — проценты размеченного ввода, округлённые до 0.1."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=120,
              cache_hit_tokens=100, cache_miss_tokens=20)
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=380,
              cache_hit_tokens=300, cache_miss_tokens=80)
    assert store.stats()["cache_hit_percent"] == 80.0
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=2,
              cache_hit_tokens=2)
    assert store.stats()["cache_hit_percent"] == 80.1


def test_cache_hit_percent_zero_without_input(session_factory):
    """Нет ввода — нет процента: деление на ноль даёт 0.0, а не исключение."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat")
    assert store.stats()["cache_hit_percent"] == 0.0


def test_cache_hit_percent_falls_back_to_prompt(session_factory):
    """Старые строки без разметки кэша считают знаменателем ``prompt_tokens``.

    У таких записей оба кэш-поля нули, и без подстановки ввода доля считалась бы по
    пустому знаменателю — «неизвестно» вместо честных нуля процентов попаданий.
    """
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=100)
    stats = store.stats()
    assert stats["prompt_tokens"] == 100
    assert stats["cache_hit_percent"] == 0.0


def test_by_model_and_by_type_group_buckets(session_factory):
    """Разрезы по модели и типу запроса: те же корзины, ключи отсортированы."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=100,
              completion_tokens=10, cache_hit_tokens=60, cache_miss_tokens=40,
              cost_estimate=0.0001)
    store.add(model="deepseek-reasoner", request_type="chat", prompt_tokens=200,
              completion_tokens=20, cache_hit_tokens=100, cache_miss_tokens=100,
              cost_estimate=0.0002)
    store.add(model="deepseek-chat", request_type="summarize", prompt_tokens=300,
              completion_tokens=30, cost_estimate=0.0003)
    stats = store.stats()
    assert list(stats["by_model"]) == ["deepseek-chat", "deepseek-reasoner"]
    assert stats["by_model"]["deepseek-chat"] == {
        "requests": 2, "prompt_tokens": 400, "completion_tokens": 40,
        "cost_estimate": 0.0004, "cache_hit_tokens": 60, "cache_miss_tokens": 40,
    }
    assert list(stats["by_type"]) == ["chat", "summarize"]
    assert stats["by_type"]["chat"]["requests"] == 2
    assert stats["by_type"]["chat"]["cache_hit_tokens"] == 160
    assert stats["by_type"]["summarize"]["completion_tokens"] == 30


def test_daily_groups_rows_by_date(session_factory):
    """Графику «расход по дням» нужны строки по возрастанию даты с суммами дня."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=100,
              completion_tokens=10, cache_hit_tokens=60, cache_miss_tokens=40,
              cost_estimate=0.0001,
              timestamp=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc))
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=200,
              completion_tokens=20, cache_hit_tokens=100, cache_miss_tokens=100,
              cost_estimate=0.0002,
              timestamp=datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc))
    store.add(model="deepseek-chat", request_type="chat", prompt_tokens=50,
              completion_tokens=5, cost_estimate=0.0004,
              timestamp=datetime(2026, 9, 24, 8, 15, tzinfo=timezone.utc))
    days = store.stats(period="all")["daily"]
    assert [day["date"] for day in days] == ["2026-09-20", "2026-09-24"]
    assert days[0] == {"date": "2026-09-20", "requests": 1, "total_tokens": 110,
                       "cache_hit_tokens": 60, "cache_miss_tokens": 40,
                       "cost_estimate": 0.0001}
    assert days[1]["requests"] == 2
    assert days[1]["total_tokens"] == 275
    assert days[1]["cost_estimate"] == 0.0006


def test_agents_lists_journal_agents_once(session_factory):
    """Список агентов для фильтра: без повторов, по алфавиту и без служебных вызовов."""
    store = _store(session_factory)
    store.add(model="deepseek-chat", request_type="chat", agent_id="agent-2")
    store.add(model="deepseek-chat", request_type="chat", agent_id="agent-1")
    store.add(model="deepseek-chat", request_type="chat", agent_id="agent-2")
    store.add(model="deepseek-chat", request_type="indexing")
    assert store.agents() == ["agent-1", "agent-2"]
    assert _store(session_factory).add(model="deepseek-chat",
                                       request_type="chat")["agent_id"] is None
    assert store.agents() == ["agent-1", "agent-2"]
