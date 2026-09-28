"""Инструменты планировщика на настоящем stdio (день 19).

Клиент поднимает ``mcp_server/server.py`` дочерним процессом, а бэкенд дня
подменяется локальным стендом (``tests/backend_stub.py``): в сеть тест не ходит, но
путь целиком настоящий — JSON-RPC по stdio, HTTP к бэкенду и разбор ответа SDK.

Здесь же фиксируется контракт новых инструментов: ``input_schema`` собирается SDK
из типов параметров, ``outputSchema`` — из ``TypedDict``, ``structuredContent``
равен самому словарю. Отдельно проверяется отказ бэкенда: он должен доехать до
модели как ``isError`` с текстом причины, а не как обрыв связи.
"""
import sys
from pathlib import Path

import pytest

from backend.services.mcp_client import MCPClient

from backend_stub import BAD_INTERVAL_DETAIL, REMINDER_ID, SUMMARY_ID, TASK_ID

SERVER = Path(__file__).resolve().parents[2] / "mcp_server" / "server.py"

#: Девять инструментов сервера дня: три читают данные, три планируют работу,
#: три собирают пайплайн (день 19 — они проверяются в test_mcp_server_stdio.py).
EXPECTED_TOOLS = {"get_user", "get_post", "list_user_posts",
                  "schedule_reminder", "collect_data", "generate_summary",
                  "search", "summarize", "save_to_file"}

#: Инструменты, которые ходят в бэкенд дня (а не во внешний API).
SCHEDULER_TOOLS = ("schedule_reminder", "collect_data", "generate_summary")


@pytest.fixture
def client(backend_api_base):
    """Клиент на своём сервере: цель — команда запуска с адресом стенда бэкенда."""
    instance = MCPClient(
        f'{sys.executable} "{SERVER.resolve()}" --backend-url {backend_api_base}',
        timeout=30.0,
    )
    try:
        yield instance
    finally:
        instance.close()


def test_catalog_lists_nine_tools(client):
    """Каталог — девять инструментов дня, у планировщика описаны параметры."""
    client.connect()
    tools = {tool.name: tool for tool in client.list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    reminder = tools["schedule_reminder"]
    assert reminder.input_schema["required"] == ["text", "delay_seconds"]
    assert reminder.input_schema["properties"]["delay_seconds"]["type"] == "integer"
    assert reminder.output_schema.get("properties"), "outputSchema не опубликована"
    assert "reminder_id" in reminder.output_schema["properties"]


@pytest.mark.parametrize("tool", SCHEDULER_TOOLS)
def test_scheduler_tools_declare_their_output(client, tool):
    """У каждого инструмента планировщика опубликована структура результата."""
    client.connect()
    tools = {item.name: item for item in client.list_tools()}
    assert tools[tool].output_schema.get("properties")
    assert tools[tool].description


def test_schedule_reminder_returns_structured_task(client):
    """Напоминание: ответ инструмента — структура с номером задачи и напоминания."""
    client.connect()
    result = client.call_tool("schedule_reminder",
                              {"text": "позвонить клиенту", "delay_seconds": 300})
    assert result.is_error is False
    payload = result.structured
    assert payload["task_id"] == TASK_ID
    assert payload["reminder_id"] == REMINDER_ID
    assert payload["text"] == "позвонить клиенту"
    assert payload["next_run_at"] and payload["message"]


def test_collect_data_returns_interval_and_first_record(client):
    """Сбор: инструмент сообщает период, имя сбора и что первая запись уже есть."""
    client.connect()
    result = client.call_tool("collect_data", {
        "source_url": "https://jsonplaceholder.typicode.com/posts",
        "interval_seconds": 10, "name": "posts",
    })
    assert result.is_error is False
    payload = result.structured
    assert payload["name"] == "posts" and payload["interval_seconds"] == 10
    assert payload["records_saved"] == 1
    assert payload["source_url"].endswith("/posts")


def test_generate_summary_returns_period_and_metrics(client):
    """Сводка: в ответе период, число записей и ключевые метрики."""
    client.connect()
    result = client.call_tool("generate_summary",
                              {"name": "posts", "interval_seconds": 20})
    assert result.is_error is False
    payload = result.structured
    assert payload["summary_id"] == SUMMARY_ID
    assert payload["total_records"] == 2
    assert payload["period_start"] and payload["period_end"]
    assert "numeric" in payload["key_metrics"]
    assert payload["summary_text"].startswith("Сводка")


def test_backend_refusal_arrives_as_tool_error(client):
    """Отказ бэкенда (негодные аргументы) — ``isError`` с текстом причины."""
    client.connect()
    result = client.call_tool("collect_data", {
        "source_url": "https://example.test/posts", "interval_seconds": 0,
        "name": "posts",
    })
    assert result.is_error is True
    assert BAD_INTERVAL_DETAIL in result.text
    assert result.structured is None
