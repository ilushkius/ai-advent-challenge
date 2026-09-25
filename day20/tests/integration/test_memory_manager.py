"""Юниты MemoryManager (день 11): три слоя памяти на временной SQLite.

Проверяется наблюдаемое поведение хранилища, а не реализация: краткосрочный
слой привязан к сессии, рабочая память — к задаче (upsert по ключу),
долговременная — к паре (категория, ключ), плюс правила отбора релевантных
долговременных записей. Сеть и рабочая БД не используются.
"""
from datetime import datetime, timezone

import pytest

from backend.core import config
from backend.storage.database import AgentRecord
from backend.agents.memory import (
    AVAILABLE_CATEGORIES, MemoryManager, query_keywords, render_long_term_block,
    render_working_block,
)


@pytest.fixture
def manager(session_factory):
    """MemoryManager на временной БД с одной строкой агента (нужна для FK)."""
    with session_factory() as session:
        session.add(AgentRecord(
            agent_id="mem01", name="Память", model=config.MODEL_CHAT,
            temperature=0.0, system_prompt="", max_tokens=100,
            current_session_id="sess0001", current_task_id=config.DEFAULT_TASK_ID,
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()
    return MemoryManager(session_factory=session_factory)


# ---------- краткосрочный слой ----------
def test_add_and_get_short_term_is_session_scoped(manager):
    """Реплики читаются только той сессией, в которую записаны."""
    manager.add_short_term("mem01", "sessA", "user", "первый")
    manager.add_short_term("mem01", "sessA", "assistant", "второй")
    manager.add_short_term("mem01", "sessB", "user", "чужая сессия")

    first = manager.get_short_term("mem01", "sessA")
    second = manager.get_short_term("mem01", "sessB")

    assert [row["content"] for row in first] == ["первый", "второй"]
    assert [row["role"] for row in first] == ["user", "assistant"]
    assert [row["content"] for row in second] == ["чужая сессия"]
    assert manager.count_short_term("mem01", "sessA") == 2


def test_add_short_term_rejects_blank_fields(manager):
    """Пустые session_id/role/content — ошибка, а не «тихая» запись."""
    with pytest.raises(ValueError, match="session_id"):
        manager.add_short_term("mem01", "", "user", "текст")
    with pytest.raises(ValueError, match="role"):
        manager.add_short_term("mem01", "sessA", "  ", "текст")
    with pytest.raises(ValueError, match="content"):
        manager.add_short_term("mem01", "sessA", "user", "")


def test_clear_short_term_returns_deleted_count(manager):
    """Очистка возвращает число удалённых и не трогает другие сессии."""
    for index in range(3):
        manager.add_short_term("mem01", "sessA", "user", f"реплика {index}")
    manager.add_short_term("mem01", "sessB", "user", "остаётся")

    assert manager.clear_short_term("mem01", "sessA") == 3
    assert manager.get_short_term("mem01", "sessA") == []
    assert manager.count_short_term("mem01", "sessB") == 1
    assert manager.clear_short_term("mem01", "sessA") == 0  # повтор — не ошибка


def test_short_term_limit_returns_tail_in_order(manager):
    """limit отдаёт хвост сессии, сохраняя хронологический порядок."""
    for index in range(1, 6):
        manager.add_short_term("mem01", "sessA", "user", f"c{index}")

    tail = manager.get_short_term("mem01", "sessA", limit=2)

    assert [row["content"] for row in tail] == ["c4", "c5"]
    assert len(manager.get_short_term("mem01", "sessA")) == 5


# ---------- рабочая память ----------
def test_working_upsert_updates_value(manager):
    """Повторная запись того же ключа обновляет значение, а не плодит дубли."""
    first = manager.add_working("mem01", "tz", "цель", "портал")
    first_updated = manager.get_working("mem01", "tz")[0]["updated_at"]
    second = manager.add_working("mem01", "tz", "цель", "лендинг")

    entries = manager.get_working("mem01", "tz")
    assert len(entries) == 1
    assert entries[0]["id"] == first["id"] == second["id"]
    assert entries[0]["value"] == "лендинг"
    assert entries[0]["updated_at"] >= first_updated


def test_working_is_scoped_by_task_id(manager):
    """Записи одной задачи не видны другой."""
    manager.add_working("mem01", "tz", "цель", "портал")
    manager.add_working("mem01", "other", "цель", "другое дело")

    assert [e["value"] for e in manager.get_working("mem01", "tz")] == ["портал"]
    assert [e["value"] for e in manager.get_working("mem01", "other")] == ["другое дело"]


def test_list_tasks_returns_distinct_sorted(manager):
    """Список задач — уникальные task_id агента в алфавитном порядке."""
    manager.add_working("mem01", "tz", "b", "1")
    manager.add_working("mem01", "alpha", "a", "1")
    manager.add_working("mem01", "tz", "c", "2")

    assert manager.list_tasks("mem01") == ["alpha", "tz"]


# ---------- долговременный слой ----------
def test_long_term_upsert_by_category_and_key(manager):
    """Ключ уникален внутри категории: та же пара обновляет, другая — добавляет."""
    first = manager.add_long_term("mem01", "preference", "язык", "русский", 0.5)
    second = manager.add_long_term("mem01", "preference", "язык", "русский", 0.95)
    manager.add_long_term("mem01", "knowledge", "язык", "Python")

    entries = manager.get_long_term("mem01", "preference")
    assert len(entries) == 1
    assert entries[0]["id"] == first["id"] == second["id"]
    assert entries[0]["confidence"] == 0.95
    assert len(manager.get_long_term("mem01")) == 2


def test_long_term_unknown_category_raises(manager):
    """Категория вне Enum отклоняется с перечислением допустимых."""
    with pytest.raises(ValueError, match="неизвестная категория"):
        manager.add_long_term("mem01", "unknown", "ключ", "значение")


def test_confidence_out_of_range_raises(manager):
    """Уверенность вне [0, 1] — ошибка."""
    with pytest.raises(ValueError, match="confidence"):
        manager.add_long_term("mem01", "profile", "имя", "Аня", confidence=1.5)
    with pytest.raises(ValueError, match="confidence"):
        manager.add_long_term("mem01", "profile", "имя", "Аня", confidence=-0.1)


def test_delete_long_term_returns_false_for_unknown(manager):
    """Удаление существующей записи → True, несуществующей → False."""
    entry = manager.add_long_term("mem01", "decision", "бд", "PostgreSQL")

    assert manager.delete_long_term("mem01", entry["id"]) is True
    assert manager.get_long_term("mem01") == []
    assert manager.delete_long_term("mem01", entry["id"]) is False
    assert manager.delete_long_term("mem01", 9999) is False


def test_select_long_term_prioritises_keyword_hits(manager):
    """Совпадение по ключевым словам важнее высокой уверенности."""
    manager.add_long_term("mem01", "knowledge", "стек_команды",
                          "Python 3.14 + FastAPI", 0.7)
    manager.add_long_term("mem01", "profile", "роль_пользователя",
                          "аналитик", 1.0)

    selected = manager.select_long_term("mem01", "какой у нас стек команд?")

    assert [e["key"] for e in selected][0] == "стек_команды"
    # Отбор детерминирован: тот же запрос — тот же результат.
    assert selected == manager.select_long_term("mem01", "какой у нас стек команд?")


def test_select_long_term_recognises_category_hint(manager):
    """Упоминание категории в запросе поднимает её записи выше по уверенности."""
    manager.add_long_term("mem01", "preference", "язык_интерфейса", "русский", 0.5)
    manager.add_long_term("mem01", "profile", "роль_пользователя", "аналитик", 0.9)

    selected = manager.select_long_term("mem01", "расскажи про предпочтения",
                                        limit=1)

    # Профиль увереннее (0.9 против 0.5), но запрос говорит про предпочтения.
    assert [e["category"] for e in selected] == ["preference"]


def test_select_long_term_falls_back_to_confidence(manager):
    """Без совпадений добираются самые уверенные записи (до limit)."""
    manager.add_long_term("mem01", "knowledge", "стек", "FastAPI", 0.7)
    manager.add_long_term("mem01", "decision", "бд", "PostgreSQL", 0.8)
    manager.add_long_term("mem01", "profile", "роль", "аналитик", 1.0)
    manager.add_long_term("mem01", "preference", "язык", "русский", 0.95)

    selected = manager.select_long_term("mem01", "ммм", limit=2)

    assert [e["key"] for e in selected] == ["роль", "язык"]
    assert len(manager.select_long_term("mem01", "ммм", limit=0)) == 0


# ---------- чистые помощники ----------
def test_query_keywords_drops_stopwords_and_short_words():
    """Стоп-слова, короткие слова и дубликаты в ключевые слова не попадают."""
    assert query_keywords("Что как это для и его? Стек, стек, БД") == ["стек"]
    assert query_keywords("") == []
    assert query_keywords("FastAPI роли пользователей") == [
        "fastapi", "роли", "пользователей",
    ]


def test_render_blocks_are_empty_for_no_entries():
    """Пустой слой не добавляет в системное сообщение пустой блок."""
    assert render_working_block([]) == ""
    assert render_long_term_block([]) == ""


def test_available_categories_match_enum():
    """Список категорий для API/UI совпадает с Enum долговременного слоя."""
    assert AVAILABLE_CATEGORIES == (
        "profile", "preference", "decision", "knowledge",
    )
