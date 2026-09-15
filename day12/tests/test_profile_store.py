"""Тесты хранилища профилей (день 12, ``backend/profile_store.py``).

Проверяется контракт таблицы ``user_profiles``: уникальность ``user_id``,
жизненный цикл ``created_at``/``updated_at``, канонизация полей при чтении и
поведение «профиля нет» (пустой профиль без ошибки — агент тогда просто
работает без персонализации).
"""
from datetime import datetime, timezone

import pytest

from backend.profile_store import (
    ProfileExistsError, ProfileNotFoundError, ProfileStore, empty_profile,
)


@pytest.fixture
def store(session_factory):
    """Хранилище профилей на временной БД (фикстура из conftest)."""
    return ProfileStore(session_factory=session_factory)


def test_create_and_load_roundtrip(store):
    """Профиль сохраняется целиком: имя, preferences, constraints, инструкции."""
    created = store.create(
        "ivan",
        name="Иван",
        preferences={"tone": "технический", "verbosity": "кратко",
                     "format": "plain text", "language": "русский"},
        constraints={"max_response_length": 500, "forbidden_topics": ["политика"],
                     "required_disclaimers": ["Это оценка"]},
        custom_instructions="- Обращайся ко мне по имени\nВсегда давай два варианта",
    )
    assert created.exists is True
    assert created.id is not None
    assert created.personalized is True

    loaded = store.load("ivan")
    assert loaded.name == "Иван"
    assert loaded.preferences["tone"] == "технический"
    assert loaded.preferences["format"] == "plain text"
    assert loaded.constraints["max_response_length"] == 500
    assert loaded.constraints["forbidden_topics"] == ["политика"]
    # Текст инструкций хранится построчно, без маркера списка.
    assert loaded.custom_instructions == (
        "Обращайся ко мне по имени\nВсегда давай два варианта"
    )
    assert loaded.instructions == [
        "Обращайся ко мне по имени", "Всегда давай два варианта",
    ]
    assert "Иван" in loaded.summary


def test_user_id_is_unique(store):
    """Второй профиль того же пользователя — конфликт (API отвечает 409)."""
    store.create("ivan")
    with pytest.raises(ProfileExistsError):
        store.create("ivan", name="Другой")


def test_get_unknown_returns_none_and_load_returns_empty(store):
    """Нет профиля: get → None (404), load → пустой профиль без ошибки."""
    assert store.get("nobody") is None
    blank = store.load("nobody")
    assert blank.exists is False
    assert blank.personalized is False
    assert blank.prompt.text == ""
    assert store.load("nobody") == empty_profile("nobody")


def test_update_replaces_fields_and_keeps_created_at(store):
    """PUT заменяет настройки: created_at сохраняется, updated_at растёт."""
    created = store.create("ivan", name="Иван",
                           preferences={"tone": "формальный"})
    updated = store.update(
        "ivan", name="Иван Петрович",
        preferences={"tone": "дружелюбный", "verbosity": "подробно"},
        constraints={"forbidden_topics": ["политика"]},
        custom_instructions="Объясняй простыми словами",
    )
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at
    assert updated.name == "Иван Петрович"
    assert updated.preferences["tone"] == "дружелюбный"
    # Поля, не переданные в PUT, сбрасываются в «не задано» (замена, не merge).
    assert updated.preferences["language"] is None
    assert updated.constraints["forbidden_topics"] == ["политика"]


def test_update_requires_existing_profile(store):
    with pytest.raises(ProfileNotFoundError):
        store.update("nobody", name="Кто-то")


def test_delete_returns_flag(store):
    store.create("ivan")
    assert store.delete("ivan") is True
    assert store.delete("ivan") is False
    assert store.get("ivan") is None


def test_list_all_is_sorted_by_user_id(store):
    """Стабильный порядок списка: селектор в интерфейсе не «прыгает»."""
    store.create("petr", name="Пётр")
    store.create("anna", name="Анна")
    assert [item.user_id for item in store.list_all()] == ["anna", "petr"]


def test_stored_timestamps_are_utc(store):
    """Метки времени пишутся в UTC (в БД — naive, сравнение приводим к UTC)."""
    created = store.create("ivan")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((now - created.updated_at.replace(tzinfo=None)).total_seconds()) < 60


@pytest.mark.parametrize("bad_user_id", ["", "   "])
def test_blank_user_id_rejected(store, bad_user_id):
    with pytest.raises(ValueError):
        store.create(bad_user_id)


def test_invalid_preferences_rejected_before_write(store):
    """Невалидное значение не доходит до БД: в таблице не остаётся строки."""
    from backend.profiles import ProfileValueError

    with pytest.raises(ProfileValueError):
        store.create("ivan", preferences={"tone": "токсичный"})
    assert store.get("ivan") is None
