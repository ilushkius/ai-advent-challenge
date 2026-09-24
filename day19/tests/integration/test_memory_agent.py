"""Поведение Agent с тремя слоями памяти (день 11).

Проверяется то, что наблюдает потребитель: состав системного сообщения
(блоки рабочей и долговременной памяти), отчёт ``record["memory"]`` с токенами
по слоям, жизненный цикл сессии (``new_session``), смена задачи
(``set_task``), восстановление активных сессии/задачи из БД. Сеть не
используется: клиент DeepSeek подменён ``FakeClient``.
"""
import pytest

from backend.core import config
from backend.agents.agent import AgentError
from backend.agents.agent_manager import AgentManager
from backend.storage.database import AgentRecord

from support import create_agent, seed_dialog


def _system_text(agent, prompt: str) -> str:
    """Текст системного сообщения, которое уйдёт в модель на этот промпт."""
    ctx = agent.prepare_context(prompt)
    system = [m for m in ctx["payload"] if m["role"] == "system"]
    assert system, "системное сообщение обязательно: в нём блоки памяти"
    return system[0]["content"]


def test_system_message_contains_working_and_long_term_blocks(make_agent):
    """Рабочая и долговременная память попадают в системное сообщение."""
    agent = make_agent(task_id="tz-portal")
    agent.add_working("ограничение", "только on-premise")
    agent.add_long_term("preference", "язык_интерфейса", "русский", 0.95)

    text = _system_text(agent, "какой у нас язык интерфейса?")

    assert "Рабочая память" in text
    assert "- ограничение: только on-premise" in text
    assert "Долговременная память" in text
    assert "- [preference] язык_интерфейса: русский (уверенность 0.95)" in text


def test_generate_reports_memory_layers_with_tokens(make_agent):
    """Ответ генерации содержит разбивку токенов по трём слоям."""
    agent = make_agent(task_id="tz-portal")
    agent.add_working("цель", "портал для ТЗ")
    agent.add_long_term("knowledge", "стек_команды", "Python 3.14 + FastAPI", 0.7)
    seed_dialog(agent, turns=2)

    record = agent.generate("какой у нас стек команд?")

    assert record["status"] == "ok"
    memory = record["memory"]
    assert memory["session_id"] == agent.session_id
    assert memory["task_id"] == "tz-portal"
    assert [layer["layer"] for layer in memory["layers"]] == [
        "short_term", "working", "long_term",
    ]
    assert memory["total_tokens"] == (
        memory["short_term_tokens"] + memory["working_tokens"]
        + memory["long_term_tokens"]
    )
    assert memory["short_term_tokens"] > 0
    assert memory["working_tokens"] > 0
    assert memory["long_term_tokens"] > 0
    assert [layer["used"] for layer in memory["layers"]] == [True, True, True]
    # Метрики хода несут те же числа по слоям, что и отчёт.
    metrics = record["token_metrics"]
    assert metrics["short_term_tokens"] == memory["short_term_tokens"]
    assert metrics["working_tokens"] == memory["working_tokens"]
    assert metrics["long_term_tokens"] == memory["long_term_tokens"]


def test_empty_layers_are_reported_as_unused(make_agent):
    """Пустые слои честно помечены used=False и дают 0 токенов."""
    agent = make_agent()
    seed_dialog(agent, turns=1)

    memory = agent.generate("вопрос без памяти")["memory"]

    layers = {layer["layer"]: layer for layer in memory["layers"]}
    assert layers["short_term"]["used"] is True
    assert layers["working"]["used"] is False
    assert layers["long_term"]["used"] is False
    assert memory["total_tokens"] == memory["short_term_tokens"]
    assert layers["long_term"]["details"] == (
        "ключевые слова: вопрос, без, памяти"
    )


def test_short_term_holds_only_current_session(make_agent):
    """Реплики другой сессии не видны агенту и не влияют на его счётчик."""
    agent = make_agent()
    seed_dialog(agent, turns=2)  # 4 реплики текущей сессии
    other = agent.memory.add_short_term(
        agent.agent_id, "othersession", "user", "реплика чужой сессии"
    )

    assert agent.message_count == 4
    assert other["id"] not in [row["id"] for row in agent.short_term_rows()]
    assert [row["content"] for row in agent.short_term_rows("othersession")] == [
        "реплика чужой сессии"
    ]


def test_new_session_clears_short_term_and_keeps_working_and_long_term(make_agent):
    """Новая сессия обнуляет диалог, сохраняя рабочую и долговременную память."""
    agent = make_agent(task_id="tz-portal")
    seed_dialog(agent, turns=2)
    agent.add_working("ограничение", "только on-premise")
    agent.add_long_term("preference", "язык_интерфейса", "русский", 0.95)
    agent.compressor.summarize(force=True)  # конспект производен от старого диалога
    before = agent.memory_state()

    result = agent.new_session()
    after = agent.memory_state()

    assert before["short_term"]["count"] == 4
    assert result["deleted_messages"] == 4
    assert result["previous_session_id"] == before["session_id"]
    assert result["session_id"] != before["session_id"]
    assert after["short_term"]["count"] == 0
    assert agent.short_term_messages == []
    assert agent.compressor.history() == []  # конспект старого диалога удалён
    assert after["working"] == before["working"]
    assert after["long_term"] == before["long_term"]
    assert after["task_id"] == "tz-portal"
    assert [e["value"] for e in agent.working_rows()] == ["только on-premise"]


def test_new_session_keeps_dialog_of_new_session_working(make_agent):
    """После новой сессии агент продолжает вести диалог (уже в новой сессии)."""
    agent = make_agent()
    seed_dialog(agent, turns=1)
    agent.new_session()

    agent.save_message("user", "вопрос в новой сессии")

    assert agent.message_count == 1
    assert agent.history_rows()[0]["content"] == "вопрос в новой сессии"


def test_set_task_switches_working_scope_without_touching_dialog(make_agent):
    """Смена задачи меняет набор записей рабочей памяти, диалог остаётся."""
    agent = make_agent(task_id="task-a")
    seed_dialog(agent, turns=2)
    agent.add_working("цель", "портал")

    first = agent.set_task("task-b")

    assert first["task_id"] == "task-b"
    assert first["entries"] == 0
    assert agent.working_rows() == []
    agent.add_working("цель", "лендинг")

    back = agent.set_task("task-a")

    assert back["entries"] == 1
    assert [e["value"] for e in agent.working_rows()] == ["портал"]
    assert agent.message_count == 4  # диалог не тронут

    with pytest.raises(AgentError, match="task_id не может быть пустым"):
        agent.set_task("   ")
    with pytest.raises(AgentError, match="длиннее"):
        agent.set_task("x" * (config.TASK_ID_MAX + 1))


def test_clear_history_removes_dialog_and_metrics_but_keeps_layers(make_agent):
    """«Очистить историю» не трогает рабочую и долговременную память."""
    agent = make_agent(task_id="tz-portal")
    seed_dialog(agent, turns=1)
    agent.generate("вопрос")
    agent.add_working("цель", "портал")
    agent.add_long_term("decision", "бд", "PostgreSQL", 0.8)
    assert agent.memory_state()["working"]["count"] == 1

    deleted = agent.clear_history()

    assert deleted == 4  # 2 реплики seed + пара от generate
    assert agent.message_count == 0
    assert agent.compressor.history() == []
    assert agent.saved_tokens_from_usage() == 0  # метрики сброшены
    assert agent.memory_state()["working"]["count"] == 1
    assert agent.memory_state()["long_term"]["count"] == 1


def test_agent_restores_session_and_task_from_db(session_factory):
    """Активные сессия и задача читаются из строки agents при рестарте."""
    seed = create_agent(session_factory, "restore01", session_id="sess0042",
                        task_id="tz-portal")
    seed.add_working("цель", "портал")
    seed.add_long_term("profile", "роль_пользователя", "аналитик", 0.9)
    seed.save_message("user", "реплика сессии")

    manager = AgentManager(session_factory=session_factory)
    manager.restore_from_db()
    restored = manager.get_agent("restore01")

    assert restored.session_id == "sess0042"
    assert restored.task_id == "tz-portal"
    assert restored.message_count == 1
    assert [e["value"] for e in restored.working_rows()] == ["портал"]
    assert [e["key"] for e in restored.long_term_rows()] == ["роль_пользователя"]


def test_restore_generates_session_for_legacy_row(session_factory):
    """Пустой current_session_id в БД чинится на старте (строка из старого файла)."""
    create_agent(session_factory, "legacy01")
    with session_factory() as session:
        row = session.query(AgentRecord).filter(
            AgentRecord.agent_id == "legacy01"
        ).one()
        row.current_session_id = ""
        row.current_task_id = ""
        session.commit()

    manager = AgentManager(session_factory=session_factory)
    manager.restore_from_db()
    restored = manager.get_agent("legacy01")

    assert len(restored.session_id) == config.SESSION_ID_LENGTH
    assert restored.task_id == config.DEFAULT_TASK_ID
    with session_factory() as session:
        stored = session.query(AgentRecord).filter(
            AgentRecord.agent_id == "legacy01"
        ).one()
        assert stored.current_session_id == restored.session_id


def test_long_term_survives_agent_recreation(session_factory):
    """Долговременная память читается новым объектом Agent на той же БД."""
    seed = create_agent(session_factory, "keep01", session_id="sess0001")
    seed.add_long_term("knowledge", "стек_команды", "Python 3.14 + FastAPI", 0.7)

    restored = create_agent(session_factory, "keep01", ensure_record=False,
                            session_id="sess0001")

    assert [e["value"] for e in restored.long_term_rows()] == [
        "Python 3.14 + FastAPI"
    ]
