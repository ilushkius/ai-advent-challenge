"""Тесты подключения профиля к запросам агента (день 13, ``backend/agent.py``).

Главное, что здесь проверяется: профиль — часть СИСТЕМНОГО ПРОМПТА каждого
запроса, а не отдельное сообщение и не подсказка. Тесты идут без сети: клиент
DeepSeek подменяется ``FakeClient`` из ``tests/support.py``, поэтому проверяется
реальная сборка payload и запись отчёта генерации.
"""
import pytest

from backend.agents.agent_manager import AgentManager
from backend.domain.profiles import PROFILE_HEADER

from support import FakeClient, create_agent, seed_profile


STRICT = {
    "name": "Инженер",
    "preferences": {"tone": "технический", "verbosity": "кратко",
                    "format": "plain text"},
    "constraints": {"max_response_length": 600},
}


def test_agent_loads_profile_at_init(session_factory, monkeypatch):
    """Профиль читается при инициализации агента и попадает в system-сообщение."""
    seed_profile(session_factory, "ivan", **STRICT)
    agent = create_agent(session_factory, "a1", user_id="ivan")

    messages = agent._system_message()
    assert len(messages) == 1
    assert messages[0]["role"] == "system"
    content = messages[0]["content"]
    assert content.startswith(PROFILE_HEADER)
    assert "Обращайся к пользователю по имени: Инженер." in content
    assert "технический" in content
    assert agent.profile.personalized is True


def test_profile_goes_before_agent_role_and_memory(session_factory):
    """Порядок блоков: профиль → роль агента → рабочая память."""
    seed_profile(session_factory, "ivan", preferences={"tone": "дружелюбный"})
    agent = create_agent(session_factory, "a1", user_id="ivan",
                         system_prompt="Ты — ассистент проекта.")
    agent.add_working("цель", "корпоративный портал")

    content = agent._system_message(
        memory=agent.build_memory_context("какая цель?"),
    )[0]["content"]
    assert content.index(PROFILE_HEADER) < content.index("Ты — ассистент проекта.")
    assert content.index("Ты — ассистент проекта.") < content.index("Рабочая память")


def test_agent_without_profile_has_no_personalization(session_factory):
    """Нет профиля — системное сообщение состоит только из роли агента."""
    agent = create_agent(session_factory, "a1", user_id="nobody",
                         system_prompt="Ты — ассистент.")
    assert agent.profile.exists is False
    assert agent.profile.personalized is False
    assert agent._system_message() == [
        {"role": "system", "content": "Ты — ассистент."}
    ]


def test_profile_increases_context_tokens(session_factory):
    """Персонализация реально уходит в запрос: токены контекста растут."""
    seed_profile(session_factory, "ivan",
                 name="Инженер",
                 preferences={"tone": "технический", "verbosity": "подробно",
                              "language": "русский", "format": "markdown"},
                 custom_instructions="Всегда предлагай два варианта решения")
    plain = create_agent(session_factory, "a1", user_id="nobody")
    personalized = create_agent(session_factory, "a2", user_id="ivan")

    assert personalized._context_tokens_for([]) > plain._context_tokens_for([])


def test_generate_reports_applied_profile_and_system_prompt(session_factory,
                                                            monkeypatch):
    """Ответ генерации показывает применённый профиль и итоговый промпт."""
    seed_profile(session_factory, "ivan", **STRICT,
                 custom_instructions="Всегда предлагай два варианта решения")
    agent = create_agent(session_factory, "a1", user_id="ivan")
    fake = FakeClient(reply="Ответ")
    monkeypatch.setattr(agent, "_make_client", lambda: fake)

    record = agent.generate("Как ускорить запрос?")

    assert record["status"] == "ok"
    profile = record["profile"]
    assert profile["user_id"] == "ivan"
    assert profile["personalized"] is True
    assert [item["field"] for item in profile["elements"]] == [
        "name", "preferences.tone", "preferences.format",
        "preferences.verbosity", "constraints.max_response_length",
        "custom_instructions",
    ]
    assert profile["instructions"] == ["Всегда предлагай два варианта решения"]
    # system_prompt — ровно то, что ушло в модель системным сообщением.
    assert record["system_prompt"].startswith(PROFILE_HEADER)
    assert record["system_prompt"].endswith(
        "- Всегда предлагай два варианта решения"
    )
    sent_system = fake.generate_calls[-1]["messages"][0]
    assert sent_system["role"] == "system"
    assert sent_system["content"] == record["system_prompt"]


def test_generate_reports_profile_even_when_api_fails(session_factory,
                                                     monkeypatch):
    """При сбое запроса отчёт о профиле уже есть (он считается до вызова)."""
    seed_profile(session_factory, "ivan", name="Инженер",
                 preferences={"tone": "технический"})
    agent = create_agent(session_factory, "a1", user_id="ivan")
    monkeypatch.setattr(
        agent, "_make_client",
        lambda: FakeClient(error=RuntimeError("сеть недоступна")),
    )

    record = agent.generate("Привет")

    assert record["status"] == "error"
    assert record["response"] is None
    assert record["profile"]["personalized"] is True
    assert record["system_prompt"].startswith(PROFILE_HEADER)
    # История не изменилась: неудачный ход не пишет реплики в БД.
    assert agent.short_term_messages == []


def test_generate_without_api_key_reports_profile(session_factory, monkeypatch):
    """Нет ключа — ошибка вызывается до сети, но профиль в отчёте виден."""
    from backend.core import config
    monkeypatch.setattr(config, "read_key_from_env_file", lambda *a, **k: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    seed_profile(session_factory, "ivan", preferences={"verbosity": "кратко"})
    agent = create_agent(session_factory, "a1", user_id="ivan")

    record = agent.generate("Привет")

    assert record["status"] == "error"
    assert "Ключ API не задан" in record["error"]
    assert record["profile"]["personalized"] is True
    assert "кратко" in record["system_prompt"]


def test_profile_change_applies_to_live_agent(session_factory):
    """Профиль можно менять на лету: следующий запрос уходит уже с новым."""
    seed_profile(session_factory, "ivan", preferences={"tone": "технический"})
    agent = create_agent(session_factory, "a1", user_id="ivan")
    before = agent._system_message()[0]["content"]
    assert "технический" in before

    agent.reload_profile()
    agent.profile_store.update(
        "ivan", preferences={"tone": "дружелюбный", "verbosity": "подробно"},
    )
    agent.reload_profile()
    after = agent._system_message()[0]["content"]
    assert "дружелюбный" in after
    assert "технический" not in after


def test_switching_user_id_switches_profile(session_factory):
    """Смена user_id в конфигурации меняет профиль без пересоздания агента."""
    seed_profile(session_factory, "ivan", preferences={"tone": "технический"})
    seed_profile(session_factory, "anna", preferences={"tone": "дружелюбный"})
    agent = create_agent(session_factory, "a1", user_id="ivan")
    assert "технический" in agent._system_message()[0]["content"]

    config = agent.config.model_copy(update={"user_id": "anna"})
    agent.apply_config(config)

    assert agent.user_id == "anna"
    assert "дружелюбный" in agent._system_message()[0]["content"]


def test_manager_update_applies_profile_to_user_agents(session_factory):
    """Обновление профиля через менеджер доходит до живых агентов сразу."""
    manager = AgentManager(session_factory=session_factory)
    manager.create_user_profile("ivan", {"preferences": {"tone": "технический"}})
    agent_id = manager.create_agent(_config(user_id="ivan"))
    agent = manager.require_agent(agent_id)
    assert "технический" in agent._system_message()[0]["content"]

    result = manager.update_user_profile(
        "ivan", {"preferences": {"tone": "дружелюбный"}},
    )

    assert result["applied_to_agents"] == 1
    assert "дружелюбный" in agent._system_message()[0]["content"]


def test_manager_delete_profile_removes_personalization(session_factory):
    """Удаление профиля выключает персонализацию, но не ломает агента."""
    manager = AgentManager(session_factory=session_factory)
    manager.create_user_profile("ivan", {"preferences": {"tone": "технический"}})
    agent_id = manager.create_agent(_config(user_id="ivan"))
    agent = manager.require_agent(agent_id)

    assert manager.delete_user_profile("ivan") is True

    assert agent.profile.exists is False
    assert agent._system_message() == []
    assert manager.get_user_profile("ivan") is None
    assert manager.delete_user_profile("ivan") is False


def test_manager_new_agent_picks_up_existing_profile(session_factory):
    """Профиль, созданный до агента, подключается при его создании."""
    manager = AgentManager(session_factory=session_factory)
    manager.create_user_profile("ivan", {
        "name": "Иван", "custom_instructions": "Обращайся ко мне по имени",
    })
    agent_id = manager.create_agent(_config(user_id="ivan"))
    state = manager.get_agent_profile(agent_id)

    assert state["personalized"] is True
    assert state["system_prompt"].startswith(PROFILE_HEADER)
    assert "Обращайся ко мне по имени" in state["system_prompt"]


def test_agent_config_rejects_blank_user_id():
    """Пустой user_id — ошибка конфигурации, а не «профиль по умолчанию»."""
    from backend.schemas import AgentConfig

    with pytest.raises(ValueError):
        AgentConfig(name="Агент", user_id="   ")


def _config(**overrides):
    """Конфигурация агента для тестов менеджера (имя всегда задано)."""
    from backend.schemas import AgentConfig

    payload = {"name": "Агент профиля"}
    payload.update(overrides)
    return AgentConfig(**payload)
