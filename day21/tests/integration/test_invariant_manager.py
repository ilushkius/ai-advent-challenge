"""Хранение инвариантов (день 14): CRUD, фильтры и независимость от диалога.

Правила проверки живут в домене и проверяются отдельно (``tests/unit/test_invariant_rules.py``);
здесь — то, что инварианты лежат в SQLite отдельной таблицей: создание, правка,
включение-выключение, удаление, фильтр по категории и то, что список правил не
меняет диалог агента. Сеть не используется.
"""

from __future__ import annotations

import pytest

from backend.domain.demo_invariants import DEMO_INVARIANTS
from backend.domain.invariant_values import InvariantValueError
from backend.storage.invariant_store import (
    InvariantExistsError,
    InvariantManager,
    InvariantNotFoundError,
)

AGENT_INVARIANT = {
    "name": "Только FastAPI и Streamlit",
    "description": "Используем только FastAPI и Streamlit, никаких Flask",
    "category": "architecture",
    "severity": "hard",
}


@pytest.fixture
def manager(session_factory):
    """Хранилище инвариантов на временной БД."""
    return InvariantManager(session_factory=session_factory)


def add(manager, **overrides) -> dict:
    """Создаёт инвариант с данными по умолчанию и переопределениями."""
    payload = dict(AGENT_INVARIANT, **overrides)
    return manager.add_invariant(**payload)


# ---------- создание ----------
def test_add_returns_active_invariant_with_timestamps(manager) -> None:
    """Созданный инвариант сразу активен и читается из БД тем же id."""
    created = add(manager)

    assert created["id"] > 0
    assert created["is_active"] is True
    assert created["created_at"].tzinfo is not None
    assert created["updated_at"].tzinfo is not None
    assert manager.get_invariant(created["id"])["name"] == AGENT_INVARIANT["name"]


def test_name_is_unique(manager) -> None:
    """Одинаковых имён быть не может: по имени инвариант называют в отказе."""
    add(manager, name="Только Python", category="stack_constraints")

    with pytest.raises(InvariantExistsError):
        add(manager, name="Только Python", category="business_rules")


@pytest.mark.parametrize("category", ["flask", "", "ARCHITECTURE"])
def test_unknown_category_is_rejected_and_row_is_not_created(manager, category) -> None:
    """Неизвестная категория — ошибка домена, строка в таблицу не попадает."""
    with pytest.raises(InvariantValueError):
        add(manager, category=category)

    assert manager.get_all_invariants(active_only=False) == []


@pytest.mark.parametrize("severity", ["medium", "", "HARD"])
def test_unknown_severity_is_rejected_and_row_is_not_created(manager, severity) -> None:
    """Неизвестная важность — ошибка домена без «тихого» значения по умолчанию."""
    with pytest.raises(InvariantValueError):
        add(manager, severity=severity)

    assert manager.get_all_invariants(active_only=False) == []


def test_get_invariant_of_unknown_id_is_none(manager) -> None:
    """Неизвестный id при чтении — ``None`` (роутер превращает его в 404)."""
    assert manager.get_invariant(999) is None


# ---------- чтение списка ----------
def test_list_orders_by_name_and_skips_inactive(manager) -> None:
    """``active_only`` по умолчанию: выключенное правило в промпт не попадает."""
    add(manager, name="Я")
    add(manager, name="А")
    hidden = add(manager, name="Б")
    manager.deactivate_invariant(hidden["id"])

    assert [item["name"] for item in manager.get_all_invariants()] == ["А", "Я"]
    assert [item["name"] for item in manager.get_all_invariants(active_only=False)] == [
        "А", "Б", "Я"
    ]


def test_list_by_category_returns_active_and_inactive(manager) -> None:
    """Фильтр по категории показывает и выключенные: их можно вернуть в работу."""
    kept = add(manager, name="Архитектура")
    add(manager, name="Стек", category="stack_constraints")
    disabled = add(manager, name="Тоже архитектура")
    manager.deactivate_invariant(disabled["id"])

    names = [item["name"] for item in manager.get_invariants_by_category("architecture")]

    assert names == ["Архитектура", "Тоже архитектура"]
    assert kept["is_active"] is True


def test_list_by_unknown_category_raises(manager) -> None:
    """Опечатка в категории — ошибка, а не пустой список «таких правил нет»."""
    with pytest.raises(InvariantValueError):
        manager.get_invariants_by_category("flask")


# ---------- правка ----------
def test_update_changes_fields_and_timestamp(manager) -> None:
    """Правка меняет переданные поля и двигает ``updated_at``."""
    created = add(manager)

    updated = manager.update_invariant(created["id"], {
        "description": "Используем только FastAPI и Streamlit",
        "severity": "soft",
    })

    assert updated["description"] == "Используем только FastAPI и Streamlit"
    assert updated["severity"] == "soft"
    assert updated["updated_at"] >= created["updated_at"]
    assert updated["category"] == created["category"]


def test_update_with_empty_data_keeps_state(manager) -> None:
    """Пустое тело PUT (или только чужие ключи) ничего не меняет."""
    created = add(manager)

    same = manager.update_invariant(created["id"], {})

    assert same == created


def test_update_to_taken_name_raises(manager) -> None:
    """Переименование в занятое имя — 409, а не тихое переименование чужого правила."""
    add(manager, name="Первое")
    second = add(manager, name="Второе")

    with pytest.raises(InvariantExistsError):
        manager.update_invariant(second["id"], {"name": "Первое"})

    assert manager.get_invariant(second["id"])["name"] == "Второе"


def test_update_own_name_is_allowed(manager) -> None:
    """Правка других полей без смены имени не упирается в проверку уникальности."""
    created = add(manager)

    updated = manager.update_invariant(created["id"], {
        "name": created["name"], "description": "Другое описание",
    })

    assert updated["description"] == "Другое описание"


@pytest.mark.parametrize(
    "data",
    [{"category": "flask"}, {"severity": "medium"}],
)
def test_update_with_unknown_value_raises(manager, data) -> None:
    """Невалидные категория/важность отклоняются до записи."""
    created = add(manager)

    with pytest.raises(InvariantValueError):
        manager.update_invariant(created["id"], data)


def test_update_of_unknown_id_raises(manager) -> None:
    """Правка несуществующего инварианта — ``InvariantNotFoundError`` (404)."""
    with pytest.raises(InvariantNotFoundError):
        manager.update_invariant(999, {"description": "нет такого"})


# ---------- включение и выключение ----------
def test_deactivate_and_activate_toggle_flag(manager) -> None:
    """Выключение убирает правило из промпта, включение возвращает его."""
    created = add(manager)

    disabled = manager.deactivate_invariant(created["id"])
    assert disabled["is_active"] is False
    assert manager.get_all_invariants() == []

    enabled = manager.activate_invariant(created["id"])
    assert enabled["is_active"] is True
    assert [item["id"] for item in manager.get_all_invariants()] == [created["id"]]


@pytest.mark.parametrize("operation", ["deactivate_invariant", "activate_invariant"])
def test_toggle_of_unknown_id_raises(manager, operation) -> None:
    """Включение/выключение несуществующего инварианта — 404, а не ``None``."""
    with pytest.raises(InvariantNotFoundError):
        getattr(manager, operation)(999)


# ---------- удаление ----------
def test_delete_removes_row_and_is_not_repeatable(manager) -> None:
    """Первое удаление — ``True``, повторное — ``False`` (роутер отвечает 404)."""
    created = add(manager)

    assert manager.delete_invariant(created["id"]) is True
    assert manager.get_invariant(created["id"]) is None
    assert manager.delete_invariant(created["id"]) is False


# ---------- инварианты живут отдельно от диалога ----------
def test_invariants_do_not_touch_agent_dialog(manager, make_agent) -> None:
    """Правила проекта хранятся в своей таблице: диалог агента от них не меняется."""
    agent = make_agent()
    agent.save_message("user", "привет")
    agent.save_message("assistant", "здравствуйте")
    before = len(agent.short_term_messages)

    for item in DEMO_INVARIANTS:
        manager.add_invariant(**item)

    assert len(agent.short_term_messages) == before
    assert len(manager.get_all_invariants()) == len(DEMO_INVARIANTS)
