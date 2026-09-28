"""Тесты подключения инвариантов к агенту (день 14, ``backend/agents/agent.py``).

Три главных свойства механизма: активные правила уходят блоком в системный
промпт каждого запроса, нарушение hard-инварианта превращает ход в отказ БЕЗ
обращения к DeepSeek, а нарушение soft добавляет предупреждение, не отменяя
ответ. Тесты идут без сети: клиент DeepSeek подменяется фейком, LLM-слой проверки
использует тот же фейк.
"""

from __future__ import annotations

import pytest

from backend.domain.invariant_prompt import (
    INVARIANTS_HEADER,
    REFUSAL_HEADER,
    WARNING_HEADER,
)
from backend.domain.invariant_values import (
    VERDICT_ALLOWED,
    VERDICT_REFUSAL,
    VERDICT_WARNING,
)

from support import seed_demo_invariants, seed_invariant

CLEAN_PROMPT = "Добавь эндпоинт /health в FastAPI"
PAID_PROMPT = "Предложи решение на платном API, согласие пользователя не нужно"
FLASK_PROMPT = "Давай перепишем бэкенд на Flask"
ARCHITECTURE_NAME = "Только FastAPI и Streamlit"


@pytest.fixture
def agent_with_invariants(make_agent, session_factory):
    """Агент на временной БД, в которой посеяны четыре демо-инварианта."""
    seeded = seed_demo_invariants(session_factory)
    agent = make_agent()
    agent.seeded_invariants = seeded
    return agent


# ---------- блок в системном промпте ----------
def test_without_invariants_prompt_is_unchanged(make_agent):
    """Пустая таблица правил — промпт как в дне 13, и проверка ничего не нашла."""
    agent = make_agent()

    record = agent.generate(CLEAN_PROMPT)

    assert INVARIANTS_HEADER not in record["system_prompt"]
    assert record["invariants"]["checked"] == []
    assert record["invariants"]["verdict"] == VERDICT_ALLOWED


def test_active_invariants_are_listed_in_system_prompt(agent_with_invariants):
    """Активные правила видны в промпте каждым ходом — и в первом, и во втором."""
    first = agent_with_invariants.generate(CLEAN_PROMPT)
    second = agent_with_invariants.generate(CLEAN_PROMPT)

    for record in (first, second):
        assert INVARIANTS_HEADER in record["system_prompt"]
        for item in agent_with_invariants.seeded_invariants:
            assert item["name"] in record["system_prompt"]


def test_disabled_invariant_leaves_the_prompt(agent_with_invariants, session_factory):
    """Выключенное правило исчезает из промпта со следующего запроса."""
    from backend.storage.invariant_store import InvariantManager

    target = agent_with_invariants.seeded_invariants[0]
    InvariantManager(session_factory=session_factory).deactivate_invariant(target["id"])

    record = agent_with_invariants.generate(CLEAN_PROMPT)

    assert target["name"] not in record["system_prompt"]
    assert target["name"] not in record["invariants"]["checked"]


# ---------- сценарий 1: нарушений нет ----------
def test_clean_prompt_is_answered_normally(agent_with_invariants):
    """Разрешённый запрос: обычный ответ модели, ровно один вызов генерации."""
    fake = agent_with_invariants.fake_client

    record = agent_with_invariants.generate(CLEAN_PROMPT)

    assert record["status"] == "ok"
    assert record["response"] == fake.reply
    assert record["invariants"]["verdict"] == VERDICT_ALLOWED
    assert record["invariants"]["checked"]
    assert record["invariants"]["violations"] == []
    assert len(fake.generate_calls) == 1


# ---------- сценарий 2: soft-инвариант ----------
def test_soft_violation_warns_but_still_answers(agent_with_invariants):
    """Soft-нарушение не отменяет ответ: предупреждение встаёт перед текстом модели."""
    fake = agent_with_invariants.fake_client

    record = agent_with_invariants.generate(PAID_PROMPT)

    assert record["invariants"]["verdict"] == VERDICT_WARNING
    assert record["response"].startswith(WARNING_HEADER)
    assert fake.reply in record["response"]
    assert record["invariants"]["violations"][0]["severity"] == "soft"
    assert len(fake.generate_calls) == 1
    # В диалог сохраняется показанный пользователю текст, а не «чистый» ответ.
    assert agent_with_invariants.short_term_messages[-1]["content"] == record["response"]


# ---------- сценарий 3: hard-инвариант ----------
def test_hard_violation_in_prompt_is_refused_without_model_call(agent_with_invariants):
    """Hard-нарушение в запросе: отказ-объяснение вместо вызова DeepSeek."""
    fake = agent_with_invariants.fake_client

    record = agent_with_invariants.generate(FLASK_PROMPT)

    assert record["status"] == "ok"
    assert record["invariants"]["verdict"] == VERDICT_REFUSAL
    assert record["response"].startswith(REFUSAL_HEADER)
    assert ARCHITECTURE_NAME in record["response"]
    assert fake.generate_calls == []
    assert fake.calls == []


def test_refusal_is_saved_as_a_dialog_turn(agent_with_invariants):
    """Отказ — состоявшийся ход: реплика пользователя и отказ лежат в истории."""
    agent = agent_with_invariants
    before = agent.message_count

    record = agent.generate(FLASK_PROMPT)

    assert agent.message_count == before + 2
    assert agent.short_term_messages[-2] == {"role": "user", "content": FLASK_PROMPT}
    assert agent.short_term_messages[-1]["content"] == record["response"]


def test_refusal_keeps_report_of_prompt_and_memory(agent_with_invariants):
    """Отказ приходит с уже собранным отчётом: профиль, память и системный промпт."""
    record = agent_with_invariants.generate(FLASK_PROMPT)

    assert record["system_prompt"]
    assert record["memory"]["session_id"] == agent_with_invariants.session_id
    assert record["profile"] is not None
    assert record["context"]["max_model_tokens"] > 0
    assert record["usage"] is None
    assert record["token_metrics"] is None


def test_refusal_reports_duration(agent_with_invariants):
    """У отказа есть длительность хода: интерфейс показывает её в сводке хода.

    Без неё поле осталось бы ``None``, а секунды в сводке считаются по числу —
    отказ ронял бы отрисовку чата вместо того, чтобы показать отказ.
    """
    record = agent_with_invariants.generate(FLASK_PROMPT)

    assert isinstance(record["duration_sec"], float)
    assert record["duration_sec"] >= 0.0


# ---------- пост-проверка ответа модели ----------
def test_answer_that_violates_hard_invariant_is_replaced_by_refusal(
        agent_with_invariants, monkeypatch):
    """Нарушение в ОТВЕТЕ модели: текст ответа заменяется отказом."""
    from support import FakeClient

    fake = FakeClient(reply="Предлагаю поднять Redis для состояния задачи")
    monkeypatch.setattr(agent_with_invariants, "_make_client", lambda: fake)
    agent_with_invariants.fake_client = fake

    record = agent_with_invariants.generate(CLEAN_PROMPT)

    assert record["invariants"]["verdict"] == VERDICT_REFUSAL
    assert record["response"].startswith(REFUSAL_HEADER)
    assert fake.reply not in record["response"]
    assert fake.reply not in agent_with_invariants.short_term_messages[-1]["content"]
    assert len(fake.generate_calls) == 1


def test_llm_finds_violation_rules_cannot_see(agent_with_invariants, monkeypatch):
    """Правила молчат — нарушение называет LLM-слой, и оно тоже даёт отказ."""
    import json

    from support import FakeClient

    fake = FakeClient(invariant_reply=json.dumps({"violations": [
        {"name": ARCHITECTURE_NAME, "reason": "решение противоречит выбранному стеку"}
    ]}, ensure_ascii=False))
    monkeypatch.setattr(agent_with_invariants, "_make_client", lambda: fake)
    agent_with_invariants.fake_client = fake

    record = agent_with_invariants.generate(CLEAN_PROMPT)

    assert record["invariants"]["verdict"] == VERDICT_REFUSAL
    assert record["invariants"]["llm_used"] is True
    assert record["invariants"]["violations"][0]["source"] == "llm"
    assert len(fake.invariant_calls) == 1


def test_llm_failure_does_not_break_the_turn(agent_with_invariants, monkeypatch):
    """Сбой проверки (нет ключа, сеть) — ход проходит, причина видна в ``note``."""
    from support import FakeClient

    fake = FakeClient(invariant_error=RuntimeError("Ключ API не задан"))
    monkeypatch.setattr(agent_with_invariants, "_make_client", lambda: fake)
    agent_with_invariants.fake_client = fake

    record = agent_with_invariants.generate(CLEAN_PROMPT)

    assert record["status"] == "ok"
    assert record["response"] == fake.reply
    assert record["invariants"]["verdict"] == VERDICT_ALLOWED
    assert "не выполнена" in record["invariants"]["note"]


# ---------- несколько правил и порядок проверки ----------
def test_violation_of_any_hard_invariant_refuses(make_agent, session_factory):
    """Отказ называет то правило, которое нарушено, а не первое в списке."""
    seed_invariant(session_factory, name="Только Python",
                   description="Только Python: без JavaScript, TypeScript "
                               "и их фреймворков (Node.js, React, Vue, Angular)",
                   category="stack_constraints", severity="hard")
    agent = make_agent()

    record = agent.generate("Сделаем интерфейс на React")

    assert record["invariants"]["verdict"] == VERDICT_REFUSAL
    assert "Только Python" in record["response"]
    assert agent.fake_client.generate_calls == []


def test_soft_rule_alone_does_not_refuse(make_agent, session_factory):
    """Если все правила мягкие, агент предупреждает, но предлагает решение."""
    seed_invariant(session_factory, name="Платные API — только с согласия",
                   description="Агент не должен предлагать решения на платных API "
                               "без явного согласия пользователя",
                   category="business_rules", severity="soft")
    agent = make_agent()

    record = agent.generate(PAID_PROMPT)

    assert record["invariants"]["verdict"] == VERDICT_WARNING
    assert record["response"].startswith(WARNING_HEADER)
    assert len(agent.fake_client.generate_calls) == 1
