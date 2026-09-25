"""Шаг пайплайна в агенте (день 19): реплика → прогон → данные в промпте.

Проверяется то, ради чего день делался: агент по реплике САМ запускает
декларативный пайплайн (несколько инструментов подряд), а модель получает блок
«## Результат пайплайна» в этом же запросе — иначе она отвечает «данных нет», хотя
прогон уже прошёл. Отдельно проверяются два «нет»: обычная реплика пайплайн не
запускает, а отказ по hard-инварианту оставляет отчёт пайплайна пустым (прогон —
действие с побочными эффектами, и до проверки правил он не доходит).
"""

import pytest

from backend.services.mcp_registry import MCPRegistry
from backend.services.mcp_tool_runner import MCPToolRunner
from backend.services.pipeline import Pipeline
from backend.services.pipeline_service import PipelineService
from backend.storage.pipeline_store import PipelineStore

from pipeline_fakes import make_pipeline_factory
from support import FakeClient, create_agent

RAG_QUESTION = "найди статьи про RAG, сделай сводку и сохрани в файл"
#: Реплика и с пайплайном, и с нарушением hard-инварианта «Только FastAPI и Streamlit».
FLASK_QUESTION = "найди статьи про Flask, сделай сводку и сохрани в файл"
PLAIN_QUESTION = "Сколько будет 2+2?"
ARCHITECTURE_INVARIANT = (
    "Только FastAPI и Streamlit",
    "Бэкенд и интерфейс пишутся только на FastAPI и Streamlit: Flask не используется",
    "architecture",
    "hard",
)

BLOCK_HEADER = "## Результат пайплайна"


def _registry(**client_kwargs) -> MCPRegistry:
    """Реестр с подключённым фейковым сервером композиции (три инструмента дня 19)."""
    registry = MCPRegistry(client_factory=make_pipeline_factory(**client_kwargs))
    registry.connect("uv run python mcp_server/server.py")
    return registry


def _service(session_factory, registry) -> PipelineService:
    """Служба пайплайнов на фейковом реестре и временном журнале.

    Реестр подставляется в прогон явно: без него ``Pipeline`` взял бы реестр
    ПРОЦЕССА, и шаги уходили бы в настоящее соединение (в тестах его нет).
    """
    store = PipelineStore(session_factory=session_factory)
    pipeline = Pipeline(runner=MCPToolRunner(registry), store=store)
    return PipelineService(pipeline=pipeline, store=store)


def _agent(session_factory, monkeypatch, registry, service):
    """Агент с фейковым реестром MCP, службой пайплайна и подменённым DeepSeek."""
    agent = create_agent(session_factory, "pipe01", mcp_registry=registry,
                         pipeline_service=service)
    fake_client = FakeClient(reply="Ответ агента по данным пайплайна")
    monkeypatch.setattr(agent, "_make_client", lambda: fake_client)
    agent.fake_client = fake_client
    agent.refresh_context_state()
    return agent


def test_rag_utterance_runs_the_pipeline(session_factory, monkeypatch, pipeline_store):
    """Реплика про RAG: прогон выполнен, три шага в отчёте, блок ушёл в промпт."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(RAG_QUESTION)
    finally:
        registry.close()

    assert record["status"] == "ok"
    report = record["pipeline"]
    assert report["detected"] is True
    assert report["status"] == "completed"
    assert report["used_in_prompt"] is True and report["added_tokens"] > 0
    assert [step["tool_name"] for step in report["steps"]] == [
        "search", "summarize", "save_to_file"]
    assert BLOCK_HEADER in record["system_prompt"]
    assert pipeline_store.run(report["run_id"])["status"] == "completed"


def test_pipeline_block_reaches_the_model(session_factory, monkeypatch, pipeline_store):
    """Блок промпта уходит модели в этом же запросе, а не висит только в отчёте."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(RAG_QUESTION)
    finally:
        registry.close()

    sent = agent.fake_client.generate_calls[-1]["messages"]
    system = next(item["content"] for item in sent if item["role"] == "system")
    assert BLOCK_HEADER in system
    assert "search: найдено" in system
    assert "save_to_file: файл" in system
    assert system in record["system_prompt"] or BLOCK_HEADER in record["system_prompt"]


def test_intent_arguments_come_from_the_utterance(session_factory, monkeypatch,
                                                  pipeline_store):
    """Аргументы прогона собраны из реплики, а не взяты из константы."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        agent.generate(RAG_QUESTION)
        calls = list(registry.client.call_calls)
    finally:
        registry.close()
    assert calls[0]["arguments"]["query"] == "RAG"
    assert calls[0]["arguments"]["source"].startswith("file:")
    assert calls[2]["arguments"]["filename"] == "rag.md"


def test_plain_utterance_does_not_run_the_pipeline(session_factory, monkeypatch,
                                                   pipeline_store):
    """Обычная реплика: прогона нет, одиночный шаг MCP работает как раньше."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(PLAIN_QUESTION)
    finally:
        registry.close()

    assert record["pipeline"]["detected"] is False
    assert record["pipeline"]["run_id"] is None
    assert BLOCK_HEADER not in record["system_prompt"]
    assert pipeline_store.list_runs() == []


def test_pipeline_run_replaces_single_tool_call(session_factory, monkeypatch,
                                                pipeline_store):
    """Реплика-пайплайн не разбирается ещё и как одиночный вызов инструмента."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(RAG_QUESTION)
        calls = list(registry.client.call_calls)
    finally:
        registry.close()

    assert record["mcp"] is None and record["schedule"] is None
    assert [call["tool"] for call in calls] == ["search", "summarize", "save_to_file"]


def test_hard_invariant_refusal_skips_the_pipeline(session_factory, monkeypatch,
                                                   pipeline_store):
    """Отказ по hard-инварианту останавливает ход до прогона: побочных эффектов нет."""
    from support import seed_invariant

    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        seed_invariant(session_factory, *ARCHITECTURE_INVARIANT)
        record = agent.generate(FLASK_QUESTION)
        calls = list(registry.client.call_calls)
    finally:
        registry.close()

    assert record["status"] == "ok"
    assert record["invariants"]["verdict"] == "refusal"
    assert record["pipeline"] is None
    assert calls == []
    assert pipeline_store.list_runs() == []


def test_added_tokens_count_the_pipeline_block(session_factory, monkeypatch,
                                               pipeline_store):
    """Токены блока пайплайна входят в контроль лимита контекста."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(RAG_QUESTION)
    finally:
        registry.close()

    report = record["pipeline"]
    assert report["added_tokens"] > 0
    sent = agent.fake_client.generate_calls[-1]["messages"]
    system = next(item["content"] for item in sent if item["role"] == "system")
    assert report["added_tokens"] == agent.count_tokens(
        BLOCK_HEADER + system.split(BLOCK_HEADER, 1)[1].split("\n\n")[0])


def test_no_connection_reports_failed_run(session_factory, monkeypatch, pipeline_store):
    """Без MCP-соединения прогон записывается как failed, а ход агента не падает."""
    registry = MCPRegistry(client_factory=make_pipeline_factory())
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(RAG_QUESTION)
    finally:
        registry.close()

    assert record["status"] == "ok"
    report = record["pipeline"]
    assert report["detected"] is True
    assert report["status"] == "failed"
    assert report["failed_at_step"] == 0
    assert report["used_in_prompt"] is False
    assert BLOCK_HEADER not in record["system_prompt"]
    assert pipeline_store.run(report["run_id"])["status"] == "failed"


@pytest.mark.parametrize("question,detected", [
    (RAG_QUESTION, True),
    (PLAIN_QUESTION, False),
])
def test_detection_is_the_only_switch(session_factory, monkeypatch, pipeline_store,
                                      question, detected):
    """Прогон запускается ровно тогда, когда эвристика распознала композицию."""
    registry = _registry()
    try:
        service = _service(session_factory, registry)
        agent = _agent(session_factory, monkeypatch, registry, service)
        record = agent.generate(question)
    finally:
        registry.close()
    assert record["pipeline"]["detected"] is detected
    assert bool(pipeline_store.list_runs()) is detected
