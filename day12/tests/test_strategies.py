"""Тесты стратегий управления контекстом (день 11): prepare_context, факты, ветки.

Проверяется логика сборки контекста по стратегиям на уровне класса Agent и
методы AgentManager (смена стратегии, ветки, факты). Всё офлайн: фейковый клиент
DeepSeek и временная SQLite-БД (фикстуры tests/conftest.py).
"""
from backend.agent_manager import AgentManager
from backend.models import AgentConfig
from backend.strategies import Strategy, AVAILABLE_STRATEGIES, strategy_from_value

from support import seed_dialog


# ---------- перечисление стратегий ----------
def test_strategy_enum_values():
    assert AVAILABLE_STRATEGIES == [
        "sliding_window", "sticky_facts", "branching", "summary",
    ]
    assert strategy_from_value("sliding_window") is Strategy.SLIDING_WINDOW
    assert strategy_from_value("summary") is Strategy.SUMMARY


def test_strategy_from_value_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        strategy_from_value("magic_strategy")


# ---------- sliding window ----------
def test_prepare_context_sliding_window(make_agent):
    agent = make_agent(strategy="sliding_window", window_size=2)
    seed_dialog(agent, 5)  # 10 реплик

    ctx = agent.prepare_context("новый вопрос")

    assert ctx["mode"] == "sliding_window"
    assert ctx["kept_messages"] == 2
    assert ctx["summary_used"] is False
    # payload = (без system-промпта) последние 2 реплики + новый промпт.
    assert len(ctx["payload"]) == 3
    assert ctx["payload"][0]["content"] == "Вопрос номер 4 про токены и контекст"
    assert ctx["payload"][1]["content"] == "Ответ номер 4 с подробностями"
    assert ctx["payload"][-1] == {"role": "user", "content": "новый вопрос"}


def test_sliding_window_drops_old_messages_from_payload(make_agent):
    agent = make_agent(strategy="sliding_window", window_size=2)
    seed_dialog(agent, 5)

    ctx = agent.prepare_context("новый вопрос")

    text = "\n".join(m["content"] for m in ctx["payload"])
    assert "Вопрос номер 0" not in text  # старые реплики не уходят
    assert "Вопрос номер 4" in text


# ---------- sticky facts ----------
def test_prepare_context_sticky_facts_injects_facts_block(make_agent):
    agent = make_agent(strategy="sticky_facts", window_size=2)
    seed_dialog(agent, 3)

    ctx = agent.prepare_context("Бюджет: 5000 долларов")

    assert ctx["mode"] == "sticky_facts"
    assert ctx["new_facts"] == {"бюджет": "5000 долларов"}
    system_content = ctx["payload"][0]["content"]
    assert "Известные факты диалога" in system_content
    assert "бюджет: 5000 долларов" in system_content


def test_sticky_facts_merged_with_existing_and_persisted(make_agent):
    agent = make_agent(strategy="sticky_facts", window_size=4)
    seed_dialog(agent, 2)

    record = agent.generate("Имя: Иван; Бюджет: 5000")
    assert record["status"] == "ok"

    facts = {f["key"]: f["value"] for f in agent.list_facts()}
    assert facts["имя"] == "Иван"
    assert facts["бюджет"] == "5000"

    # Новое значение того же ключа перекрывает старое, а не плодит дубль.
    agent.generate("Бюджет: 7000")
    facts = {f["key"]: f["value"] for f in agent.list_facts()}
    assert facts["бюджет"] == "7000"
    assert list(facts).count("бюджет") == 1


# ---------- branching ----------
def test_branching_sends_full_active_history(make_agent):
    agent = make_agent(strategy="branching")
    seed_dialog(agent, 3)  # 6 реплик

    ctx = agent.prepare_context("новый вопрос")
    assert ctx["mode"] == "branching"
    # вся история (6) + новый промпт
    assert len(ctx["payload"]) == 7
    assert ctx["kept_messages"] == 6


def test_branching_snapshot_fork_and_switch(make_agent):
    agent = make_agent(strategy="branching")
    seed_dialog(agent, 2)  # 4 реплики

    record = agent.generate("вопрос про ТЗ")
    assert record["status"] == "ok"
    assert agent.active_branch_id is not None

    branches = agent.list_branches()
    assert len(branches) == 1
    root = branches[0]
    assert root["is_active"] is True
    assert root["message_count"] == 6  # 4 + user + assistant

    # Форк от текущего состояния: родитель — корень, история не меняется.
    fork = agent.create_branch(None)
    assert fork["parent_id"] == root["id"]
    assert fork["is_active"] is True
    assert agent.message_count == 6

    # Рост на форке обновляет снимок форка, корень остаётся замороженным.
    agent.generate("ещё вопрос")
    branches = agent.list_branches()
    by_id = {b["id"]: b for b in branches}
    assert by_id[fork["id"]]["message_count"] == 8
    assert by_id[root["id"]]["message_count"] == 6

    # Переключение на корень возвращает его снимок.
    switched = agent.switch_branch(root["id"])
    assert switched["is_active"] is True
    assert agent.active_branch_id == root["id"]
    assert agent.message_count == 6


def test_create_branch_from_missing_checkpoint_raises(make_agent):
    import pytest
    from backend.agent import AgentError
    agent = make_agent(strategy="branching")
    with pytest.raises(AgentError):
        agent.create_branch(checkpoint_id=999)


# ---------- AgentManager: стратегии и ветки ----------
def test_manager_set_strategy_and_get_state(session_factory):
    manager = AgentManager(session_factory=session_factory)
    agent_id = manager.create_agent(AgentConfig(name="Тест", strategy="summary"))

    assert manager.get_strategy_state(agent_id)["strategy"] == "summary"
    assert manager.get_available_strategies() == AVAILABLE_STRATEGIES

    manager.set_strategy(agent_id, "sliding_window", window_size=5)
    state = manager.get_strategy_state(agent_id)
    assert state["strategy"] == "sliding_window"
    assert state["window_size"] == 5
    assert state["available"] == AVAILABLE_STRATEGIES


def test_manager_branches_roundtrip(session_factory):
    manager = AgentManager(session_factory=session_factory)
    agent_id = manager.create_agent(AgentConfig(name="Ветка", strategy="branching"))

    # Ещё нет веток.
    assert manager.list_branches(agent_id)["branches"] == []

    branch = manager.create_branch(agent_id, None)
    assert branch["is_active"] is True
    tree = manager.list_branches(agent_id)
    assert tree["active_branch_id"] == branch["id"]
    assert [b["id"] for b in tree["branches"]] == [branch["id"]]
