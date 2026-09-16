"""Тесты агента дня 9: сборка payload со сжатием, метрики экономии, FSM.

Это ядро дня: проверяем, что в запрос уходит конспект + последние N реплик,
что полная история остаётся в БД, что метрики экономии попадают в token_usage и
что сбой суммаризации не ломает ответ пользователю.
"""
import pytest

from backend.agent import Agent
from backend.models import AgentConfig

from support import FakeClient, create_agent, seed_dialog


def payload_text(payload) -> str:
    """Весь текст payload одним куском — для проверок «что ушло в запрос»."""
    return "\n".join(item["content"] for item in payload)


def test_full_history_goes_when_compression_disabled(make_agent):
    """Сжатие выключено: payload содержит всю историю (поведение дня 8)."""
    agent = make_agent(summary_enabled=False)
    seed_dialog(agent, turns=3)

    plan = agent.build_payloads("новый вопрос")

    assert plan.summary_used is False
    text = payload_text(plan.sent_payload)
    for index in range(3):
        assert f"Вопрос номер {index}" in text
        assert f"Ответ номер {index}" in text
    assert plan.full_context_tokens == plan.sent_context_tokens
    assert plan.saved_tokens == 0


def test_compressed_payload_keeps_only_tail(make_agent):
    """Со сжатием: старые реплики уходят из payload, последние N — остаются."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=4)
    agent.compressor.summarize(force=True)

    plan = agent.build_payloads("новый вопрос")

    assert plan.summary_used is True
    assert plan.kept_messages == 2
    text = payload_text(plan.sent_payload)
    # Конспект присутствует, старые реплики — нет, последние две — да.
    assert "Конспект предыдущей части диалога" in text
    assert "Вопрос номер 0" not in text
    assert "Вопрос номер 3" in text
    assert "Ответ номер 3" in text
    assert plan.sent_context_tokens < plan.full_context_tokens
    assert plan.saved_tokens == plan.full_context_tokens - plan.sent_context_tokens


def test_full_history_is_preserved_in_db(make_agent):
    """Сжатие не удаляет историю: в БД остаются все реплики."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=4)
    agent.compressor.summarize(force=True)

    assert agent.message_count == 8
    rows = agent.history_rows()
    assert len(rows) == 8
    assert sum(1 for row in rows if row["summarized"]) >= 4
    assert [row["content"] for row in rows if not row["summarized"]] == [
        "Вопрос номер 3 про токены и контекст",
        "Ответ номер 3 с подробностями",
    ]


def test_generate_records_savings_in_token_usage(make_agent):
    """После хода token_usage хранит режим сжатия и сэкономленные токены."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=4)
    agent.compressor.summarize(force=True)

    record = agent.generate("Сколько мы уже сэкономили?")

    assert record["status"] == "ok"
    metrics = record["token_metrics"]
    assert metrics["mode"] == "compressed"
    assert metrics["summary_used"] is True
    assert metrics["full_context_tokens"] > metrics["sent_context_tokens"]
    assert metrics["saved_tokens"] > 0
    assert agent.saved_tokens_from_usage() == metrics["saved_tokens"]
    assert record["context"]["compression"]["saved_percent"] > 0


def test_generate_autocompresses_after_turn(make_agent):
    """Порог набран — сжатие происходит автоматически после успешного хода."""
    agent = make_agent(keep_last_messages=2, summarize_every=4)
    seed_dialog(agent, turns=3)  # 6 непокрытых реплик, порог 2+4

    record = agent.generate("Ещё один вопрос")

    assert record["status"] == "ok"
    # После хода реплик стало 8, сжатие сработало: конспект появился.
    assert agent.compressor.history(), "конспект должен создаться автоматически"
    assert record["context"]["state"] in ("tracking", "idle")


def test_generate_survives_summary_failure(make_agent):
    """Сбой суммаризации: ответ пользователю есть, ошибка видна в compression."""
    fake = FakeClient(summary_error=RuntimeError("суммаризатор недоступен"))
    agent = make_agent(fake=fake, keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)

    record = agent.generate("Ход при упавшем суммаризаторе")

    # Генерация успешна — сеть не падала; состояние сжатия ушло в ERROR.
    assert record["status"] == "ok"
    assert record["response"] == "Ответ ассистента"
    assert record["context"]["compression"]["error"] is not None
    assert record["context"]["state"] == "error"
    assert agent.state_value() == "error"
    assert agent.compressor.history() == []


def test_emergency_trim_keeps_history_in_db(make_agent):
    """Если даже сжатый запрос не влезает — реплики пропускаются, но не удаляются."""
    agent = make_agent(summary_enabled=False)
    seed_dialog(agent, turns=3)

    # Лимит ставим на 1 токен ниже того, что уйдёт сейчас: сработает
    # предохранитель, и хотя бы одна пара реплик не попадёт в запрос.
    sent = agent.build_payloads("Короткий вопрос").sent_context_tokens
    original = agent.__class__.context_limit_tokens
    agent.__class__.context_limit_tokens = property(lambda self: sent - 1)
    try:
        record = agent.generate("Короткий вопрос")
        assert record["status"] == "ok"
        # Выброшены ровно самые старые пары, минимум — чтобы влезть в лимит.
        assert record["context"]["trimmed_messages"] == 2
        assert record["context"]["over_limit"] is True
        assert record["context"]["warning"]
        # В первом ответе нет первой пары реплик, но есть последняя.
        sent_text = payload_text(agent.fake_client.generate_calls[0]["messages"])
        assert "Вопрос номер 0" not in sent_text
        assert "Вопрос номер 2" in sent_text
        # История в БД не пострадала: все реплики + новый ход.
        assert agent.message_count == 8
    finally:
        agent.__class__.context_limit_tokens = original


def test_generate_error_when_message_alone_too_long(make_agent):
    """Сообщение длиннее лимита при пустой истории — ошибка без вызова API."""
    agent = make_agent(summary_enabled=False)
    original = agent.__class__.context_limit_tokens
    agent.__class__.context_limit_tokens = property(lambda self: 10)
    try:
        record = agent.generate("Очень длинное сообщение " * 50)
        assert record["status"] == "error"
        assert "длиннее лимита" in record["error"]
        assert agent.fake_client.generate_calls == []
        assert agent.message_count == 0
    finally:
        agent.__class__.context_limit_tokens = original


def test_compare_modes_counts_without_api(make_agent):
    """Сравнение без call_api не ходит в сеть и показывает экономию токенов."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=4)
    agent.compressor.summarize(force=True)
    before_messages = agent.message_count
    before_calls = len(agent.fake_client.generate_calls)

    result = agent.compare_modes("Вопрос для сравнения", call_api=False)

    assert result["full"]["sent_context_tokens"] > result["compressed"]["sent_context_tokens"]
    assert result["saved_tokens"] > 0
    assert result["saved_percent"] > 0
    assert len(agent.fake_client.generate_calls) == before_calls
    assert agent.message_count == before_messages


def test_compare_modes_calls_api_twice(make_agent):
    """call_api=True делает два вызова (полная и сжатая история) и не меняет историю."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=4)
    agent.compressor.summarize(force=True)
    before = agent.message_count

    result = agent.compare_modes("Сравни ответы", call_api=True)

    assert len(agent.fake_client.generate_calls) == 2
    assert result["full"]["response"] == "Ответ ассистента"
    assert result["compressed"]["response"] == "Ответ ассистента"
    assert result["full"]["total_tokens"] is not None
    assert agent.message_count == before


def test_compare_modes_reports_api_failure(make_agent):
    """Сбой API в сравнении не поднимается исключением: сторона помечена ошибкой."""
    agent = make_agent(fake=FakeClient(error=RuntimeError("502 bad gateway")),
                       keep_last_messages=2, summarize_every=2)
    seed_dialog(agent, turns=3)

    result = agent.compare_modes("Вопрос", call_api=True)

    assert result["full"]["error"] is not None
    assert result["compressed"]["error"] is not None
    assert result["warning"]
    assert agent.message_count == 6


def test_state_machine_reflects_backlog(make_agent):
    """FSM выводится из БД: сначала idle, при накоплении — summary_pending."""
    agent = make_agent(keep_last_messages=2, summarize_every=2)
    assert agent.state_value() == "idle"

    seed_dialog(agent, turns=3)
    agent.refresh_context_state()
    assert agent.state_value() == "summary_pending"

    agent.compress_now()
    agent.refresh_context_state()
    assert agent.state_value() in ("tracking", "idle")


def test_disabled_compression_forces_idle(make_agent):
    """Выключенное сжатие всегда даёт состояние idle и отсутствие конспектов."""
    agent = make_agent(summary_enabled=False)
    seed_dialog(agent, turns=5)

    agent.refresh_context_state()
    assert agent.state_value() == "idle"
    report = agent.compress_now()
    assert report["attempted"] is False
    assert agent.compressor.history() == []


def test_summary_state_reports_progress(make_agent):
    """Сводка сжатия показывает watermark, остаток порога и экономику."""
    agent = make_agent(keep_last_messages=2, summarize_every=4)
    seed_dialog(agent, turns=2)  # 4 реплики, до порога не хватает 2

    state = agent.summary_state()

    assert state["message_count"] == 4
    assert state["uncovered_messages"] == 4
    assert state["summary_count"] == 0
    assert state["next_compression_in"] == 2
    assert state["enabled"] is True
