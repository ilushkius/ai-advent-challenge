"""Юнит-тесты панелей и соединения ассистента разработчика (день 31).

Панели раздела — это не «мелочь разметки»: `GET /dev-assistant/tools` и
`GET /dev-assistant/git-context` обязаны отвечать 200 всегда, а причина отказа
(недоступный сервер, ошибка инструмента) приходит полем `error`. Здесь же
проверяется жизненный цикл соединения со stdio-сервером: служба поднимает его сама
один раз на процесс и закрывает по `close()`, иначе сервер остался бы висеть
дочерним процессом после остановки бэкенда.

Фейки — в `tests/dev_assistant_fakes.py`, поведение ответов ``/help`` — в
`tests/unit/test_dev_assistant_service.py`.
"""
from __future__ import annotations

import pytest

from backend.core import config
from backend.domain import dev_assistant
from backend.services import dev_assistant_service
from backend.services.dev_assistant_service import DevAssistantService
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.storage.llm_usage_store import LLMUsageStore

from dev_assistant_fakes import (
    FakeIndexService,
    FakeMCP,
    FakeStdioClient,
    FailingStdioClient,
    make_service,
)
from rag_fakes import GROUNDED_REPLY, RagStubClient


def test_default_dependencies_are_resolved_lazily():
    """Без подстановок служба берёт индекс и top_k процесса, а MCP — из конструктора."""
    service = DevAssistantService()
    assert isinstance(service.index_service, IndexService)
    assert service.top_k == dev_assistant.DEFAULT_TOP_K
    assert service._mcp_target == dev_assistant.DEV_SERVER_TARGET


def test_tools_catalog_lists_server_tools():
    """Панель инструментов: имя сервера, число инструментов и их описания."""
    service = make_service(mcp=FakeMCP())

    catalog = service.tools()

    assert catalog["server"] == "dev_server"
    assert catalog["connected"] is True
    assert catalog["error"] == ""
    assert catalog["count"] == len(dev_assistant.TOOLS)
    assert {tool["name"] for tool in catalog["tools"]} == set(dev_assistant.TOOLS)
    assert all(tool["description"] and "input_schema" in tool
               for tool in catalog["tools"])


def test_tools_catalog_reports_unavailable_server(monkeypatch):
    """Недоступный сервер: каталог пуст, причина — в поле ``error``, исключения нет."""
    monkeypatch.setattr(dev_assistant_service, "MCPClient", FailingStdioClient)
    service = DevAssistantService()

    catalog = service.tools()
    git = service.git_context()

    assert catalog["connected"] is False and catalog["count"] == 0
    assert "сервер не отвечает" in catalog["error"]
    assert git["branch"] == "" and git["clean"] is True
    assert "сервер не отвечает" in git["error"]


def test_git_context_reports_tool_error():
    """Ошибка инструмента в панели git: пустое состояние и текст ошибки из ответа."""
    service = make_service(mcp=FakeMCP(tool_error="git не сработал: нет в PATH"))

    git = service.git_context()

    assert git["branch"] == "" and git["modified_files"] == []
    assert "нет в PATH" in git["error"]


def test_connection_is_built_once_and_closed(monkeypatch):
    """Соединение со stdio-сервером поднимается один раз и закрывается методом ``close``."""
    monkeypatch.setattr(dev_assistant_service, "MCPClient", FakeStdioClient)
    monkeypatch.setattr(FakeStdioClient, "created", 0)
    service = DevAssistantService()

    catalog = service.tools()
    git = service.git_context()

    assert catalog["count"] == len(dev_assistant.TOOLS)
    assert git["branch"] == "main" and git["modified_files"] == ["day21/app.py"]
    assert FakeStdioClient.created == 1
    assert FakeStdioClient.last_kwargs["target"] == dev_assistant.DEV_SERVER_TARGET
    client = service.server
    service.close()
    assert client.closed is True and service._server is None


def test_connection_uses_fleet_working_directory(monkeypatch):
    """Сервер поднимается из каталога дня: относительные пути команд совпадают с API."""
    monkeypatch.setattr(dev_assistant_service, "MCPClient", FakeStdioClient)
    service = DevAssistantService()

    service.tools()

    assert FakeStdioClient.last_kwargs["cwd"] == config.MCP_FLEET_CWD


def test_unavailable_server_is_recorded_in_handle_help(monkeypatch, session_factory):
    """Сервер не поднялся: записи с ошибкой у всех плановых инструментов, ответ по RAG."""
    monkeypatch.setattr(dev_assistant_service, "MCPClient", FailingStdioClient)
    stub = RagStubClient()
    client = LLMClient(agent_id=dev_assistant.AGENT_ID, client_factory=lambda: stub,
                       store=LLMUsageStore(session_factory=session_factory))
    service = DevAssistantService(index_service=FakeIndexService(), llm_client=client,
                                  sleep=lambda _seconds: None)

    record = service.handle_help("какие файлы изменены и как устроен RAG?")

    assert [item["tool"] for item in record["mcp_tools_used"]] == [
        dev_assistant.TOOL_GIT_BRANCH, dev_assistant.TOOL_GIT_DIFF]
    assert all(item["ok"] is False for item in record["mcp_tools_used"])
    assert any("недоступен" in warning for warning in record["warnings"])
    assert record["sources"]
    assert record["answer"] == GROUNDED_REPLY


def test_make_client_resolves_key(monkeypatch):
    """Клиент DeepSeek собирается по ключу из конфига, без ключа — ``RuntimeError``."""
    monkeypatch.setattr(config, "resolve_api_key", lambda: "")
    with pytest.raises(RuntimeError):
        dev_assistant_service.make_dev_assistant_client()

    sentinel = object()
    monkeypatch.setattr(config, "resolve_api_key", lambda: "key-123")
    monkeypatch.setattr(dev_assistant_service, "make_client", lambda *args: sentinel)
    assert dev_assistant_service.make_dev_assistant_client() is sentinel


def test_process_singleton_is_reused(monkeypatch):
    """Служба процесса одна: второй вызов возвращает тот же экземпляр."""
    monkeypatch.setattr(dev_assistant_service, "_service", None)
    first = dev_assistant_service.get_dev_assistant_service()
    assert dev_assistant_service.get_dev_assistant_service() is first
