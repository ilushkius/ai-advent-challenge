"""Интеграционный тест сервера обработки данных на настоящем stdio (день 20).

Проверяется весь путь целиком: клиент дня поднимает
``mcp_servers/data_server/server.py`` дочерним процессом того же интерпретатора и
зовёт инструменты по JSON-RPC. Сети тест не требует вовсе: сервер обработки данных
не читает ни HTTP, ни файлов, а DeepSeek выключен режимом ``--llm off``.

Здесь же фиксируется контракт инструментов: каталог — ровно четыре имени,
``inputSchema`` собирается SDK из типов параметров, ``outputSchema`` — из
``TypedDict``, ``structuredContent`` равен самому словарю, а ошибка инструмента
приходит данными (``is_error``) с русским текстом причины.

Тест медленнее юнит-тестов (поднимается процесс), поэтому клиент в фикстуре один
на тест и всегда закрывается в ``finally``.
"""
import sys
from pathlib import Path

import pytest

from backend.services.mcp_client import MCPClient

SERVER = Path(__file__).resolve().parents[1] / ".." / "mcp_servers" / "data_server" / "server.py"

#: Имена инструментов, которые обязан публиковать сервер обработки данных.
EXPECTED_TOOLS = {"summarize", "extract_keywords", "filter_by_date", "aggregate"}


@pytest.fixture
def client():
    """Клиент на своём сервере: команда запуска с выключенной LLM (без сети)."""
    instance = MCPClient(f'{sys.executable} "{SERVER.resolve()}" --llm off', timeout=30.0)
    try:
        yield instance
    finally:
        instance.close()


def test_catalog_has_four_typed_tools(client):
    """Каталог — четыре инструмента, у каждого описание и обе схемы."""
    client.connect()
    tools = {tool.name: tool for tool in client.list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    assert all(tool.description.strip() for tool in tools.values())

    summarize = tools["summarize"]
    assert summarize.input_schema["required"] == ["items"]
    assert summarize.input_schema["properties"]["items"]["type"] == "array"
    assert summarize.input_schema["properties"]["style"]["default"] == "short"
    assert {"summary_text", "key_points", "total_items", "style_used",
            "engine"} <= set(summarize.output_schema["properties"])

    assert tools["extract_keywords"].input_schema["required"] == ["text"]
    assert tools["filter_by_date"].input_schema["required"] == ["items"]
    assert tools["filter_by_date"].output_schema["properties"], "нет outputSchema"
    aggregate = tools["aggregate"]
    assert aggregate.input_schema["required"] == ["items"]
    assert aggregate.input_schema["properties"]["metric"]["default"] == "count"


def test_summarize_falls_back_to_aggregation(client):
    """Без ключа ``--llm off`` сводку собирает агрегация: движок ``aggregation``."""
    client.connect()
    result = client.call_tool("summarize", {
        "items": [{"title": "RAG", "content": "поиск"},
                  {"title": "Чанкинг", "content": "нарезка"}],
        "style": "bullets",
        "max_length": 400,
    })
    assert result.is_error is False
    assert result.structured["engine"] == "aggregation"
    assert result.structured["total_items"] == 2
    assert result.structured["key_points"] == ["RAG", "Чанкинг"]
    assert result.structured["summary_text"].startswith("- RAG")


def test_summarize_rejects_empty_list(client):
    """Пустой список — ошибка инструмента: сводить нечего."""
    client.connect()
    result = client.call_tool("summarize", {"items": []})
    assert result.is_error is True
    assert "пуст" in result.text
    assert result.structured is None


def test_extract_keywords_returns_frequencies(client):
    """Ключевые слова приходят списком, строкой и счётчиком — одним словарём."""
    client.connect()
    result = client.call_tool("extract_keywords", {
        "text": "RAG поиск RAG чанкинг", "limit": 5,
    })
    assert result.is_error is False
    assert result.structured["keywords"] == ["rag", "поиск", "чанкинг"]
    assert result.structured["joined"] == "rag, поиск, чанкинг"
    assert result.structured["count"] == 3
    assert result.structured["engine"] == "frequency"


def test_filter_by_date_keeps_the_bounds(client):
    """Отбор по дате принимает ISO и ``ДД.ММ.ГГГГ``, а записи без даты считает."""
    client.connect()
    result = client.call_tool("filter_by_date", {
        "items": [{"id": 1, "created_at": "2026-01-02"},
                  {"id": 2, "created_at": "02.01.2026"},
                  {"id": 3, "created_at": "нет даты"},
                  {"id": 4}],
        "field": "created_at",
        "since": "2026-01-02",
        "until": "02.01.2026",
        "limit": 10,
    })
    assert result.is_error is False
    assert [item["id"] for item in result.structured["items"]] == [1, 2]
    assert result.structured["count"] == 2
    assert result.structured["skipped"] == 2
    assert result.structured["since"] == "2026-01-02"


def test_aggregate_groups_and_counts(client):
    """Группировка по полю: ``sum`` по ``value_field`` и число групп в ответе."""
    client.connect()
    result = client.call_tool("aggregate", {
        "items": [{"status": "ok", "amount": 10}, {"status": "ok", "amount": 5},
                  {"status": "fail", "amount": 1}],
        "group_by": "status",
        "metric": "sum",
        "value_field": "amount",
        "limit": 5,
    })
    assert result.is_error is False
    assert result.structured["groups"] == [{"key": "ok", "value": 15.0},
                                           {"key": "fail", "value": 1.0}]
    assert result.structured["count"] == 2
    assert result.structured["metric"] == "sum"


def test_tool_errors_come_as_data_with_reason(client):
    """Ошибки инструментов — данные с русским текстом причины, а не исключения."""
    client.connect()

    blank = client.call_tool("extract_keywords", {"text": "   "})
    assert blank.is_error is True and blank.structured is None
    assert "Нет текста" in blank.text

    bad_style = client.call_tool("summarize", {
        "items": [{"title": "RAG"}], "style": "exotic"})
    assert bad_style.is_error is True
    assert "не поддержан" in bad_style.text and "exotic" in bad_style.text

    bad_metric = client.call_tool("aggregate", {
        "items": [{"status": "ok"}], "metric": "median"})
    assert bad_metric.is_error is True
    assert "не поддержана" in bad_metric.text

    missing_field = client.call_tool("aggregate", {
        "items": [{"status": "ok"}], "metric": "sum"})
    assert missing_field.is_error is True
    assert "требует value_field" in missing_field.text
