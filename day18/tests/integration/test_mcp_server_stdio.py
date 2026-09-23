"""Интеграционный тест своего MCP-сервера на настоящем stdio (день 18).

Проверяется весь путь целиком: клиент поднимает ``day18/mcp_server/server.py``
дочерним процессом того же интерпретатора, а внешний API подменяется локальным
стендом (``tests/stub_api.py``) — в сеть тест не ходит, но HTTP-запросы и разбор
ответов настоящие. Здесь же фиксируется контракт инструментов: ``input_schema``
собирается SDK из типов параметров, ``output_schema`` — из ``TypedDict``, а
``structuredContent`` равен самому словарю.

Тест медленнее юнит-тестов (поднимается процесс и HTTP-стенд), поэтому клиент в
фикстуре один на тест и всегда закрывается в ``finally``.
"""
import sys
from pathlib import Path

import pytest

from backend.services.mcp_client import MCPClient, MCPNotConnectedError

SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_server" / "server.py"

#: Имена инструментов, которые обязан публиковать сервер дня (день 18: шесть —
#: три читают внешний API, три ставят фоновые задачи через бэкенд дня).
EXPECTED_TOOLS = {"get_user", "get_post", "list_user_posts",
                  "schedule_reminder", "collect_data", "generate_summary"}


@pytest.fixture
def client(stub_api_base):
    """Клиент на своём сервере: цель — команда запуска с адресом стенда."""
    instance = MCPClient(
        f'{sys.executable} "{SERVER.resolve()}" --api-base {stub_api_base}',
        timeout=30.0,
    )
    try:
        yield instance
    finally:
        instance.close()


def test_catalog_has_three_tools_with_schemas(client):
    """Каталог — шесть инструментов дня, у каждого схемы аргументов и результата."""
    client.connect()
    tools = client.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS

    user = next(tool for tool in tools if tool.name == "get_user")
    assert user.input_schema.get("required") == ["user_id"]
    assert user.input_schema["properties"]["user_id"]["type"] == "integer"
    assert user.output_schema.get("properties"), "output_schema не опубликована"
    assert "name" in user.output_schema["properties"]
    assert user.description

    posts = next(tool for tool in tools if tool.name == "list_user_posts")
    assert posts.input_schema["required"] == ["user_id"]
    assert posts.input_schema["properties"]["limit"]["default"] == 5


def test_call_returns_structured_user(client):
    """Вызов возвращает структурированные данные пользователя, а не только текст."""
    client.connect()
    result = client.call_tool("get_user", {"user_id": 1})
    assert result.is_error is False
    assert result.structured["name"] and result.structured["email"]
    assert result.structured["city"]
    assert result.tool == "get_user" and result.arguments == {"user_id": 1}
    assert result.duration_ms >= 0


def test_call_reports_missing_user_as_tool_error(client):
    """Несуществующий id — ответ с ``isError`` и текстом про 404, а не исключение."""
    client.connect()
    result = client.call_tool("get_user", {"user_id": 999})
    assert result.is_error is True
    assert "999" in result.text and "404" in result.text
    assert result.structured is None


def test_list_user_posts_respects_limit(client):
    """``limit`` ограничивает ответ, а ``count`` считает именно возвращённые посты."""
    client.connect()
    result = client.call_tool("list_user_posts", {"user_id": 1, "limit": 2})
    assert result.is_error is False
    assert result.structured["count"] == 2
    assert [post["id"] for post in result.structured["posts"]] == [1, 2]


def test_call_requires_connection(client):
    """Без соединения вызов недоступен: явная ошибка, а не пустой результат."""
    with pytest.raises(MCPNotConnectedError):
        client.call_tool("get_user", {"user_id": 1})
