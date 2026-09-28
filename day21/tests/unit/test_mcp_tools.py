"""Тесты структуры инструмента MCP и результата вызова (день 17).

Контракт инструмента — четыре поля: ``name``, ``description``, ``input_schema``,
``output_schema`` (последнее добавлено днём 17: не всякий сервер публикует схему
результата). Тесты фиксируют нормализацию (пустые описание и схемы не
превращаются в ``None``) и негативный сценарий: инструмент без имени — ошибка, а
не запись-призрак в списке. Здесь же — ``MCPToolResult``: словарь ответа
инструмента, который уходит и в промпт, и в отчёт API.
"""
import pytest

from backend.domain.mcp_tools import (
    MCPToolError,
    MCPToolInfo,
    MCPToolResult,
    make_tool_info,
    make_tool_infos,
)


def test_fields_and_to_dict_contract():
    """``to_dict`` отдаёт ровно четыре поля контракта с сохранением значений."""
    tool = make_tool_info("fetch", "Загружает URL", {"type": "object"},
                          {"type": "object", "properties": {"text": {}}})
    assert tool.to_dict() == {
        "name": "fetch",
        "description": "Загружает URL",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "properties": {"text": {}}},
    }


def test_missing_description_and_schemas_normalized():
    """Отсутствующие описание и схемы — ``""`` и ``{}``, а не ``None``."""
    tool = make_tool_info("list_allowed_directories", None, None)
    assert tool == MCPToolInfo(name="list_allowed_directories", description="",
                              input_schema={}, output_schema={})
    assert tool.to_dict()["output_schema"] == {}


def test_whitespace_name_trimmed():
    """Пробелы вокруг имени и описания снимаются (серверы их присылают)."""
    tool = make_tool_info("  read_file \n", "  Читает файл  ", {"type": "object"})
    assert tool.name == "read_file"
    assert tool.description == "Читает файл"


@pytest.mark.parametrize("name", [None, "", "   ", "\n"])
def test_nameless_tool_rejected(name):
    """Инструмент без имени — явная ошибка: его нельзя ни показать, ни вызвать."""
    with pytest.raises(MCPToolError) as exc:
        make_tool_info(name, "описание", {})
    assert "нет имени" in str(exc.value)


@pytest.mark.parametrize("schema", ["not-a-schema", None, 42, ["a"]])
def test_unexpected_schema_becomes_empty(schema):
    """Неожиданная схема не ломает разбор: вместо неё пустой объект."""
    tool = make_tool_info("t", "", schema, schema)
    assert tool.input_schema == {} and tool.output_schema == {}


def test_to_dict_copies_schemas():
    """Правка словаря из ``to_dict`` не меняет сам инструмент (защита от алиасов)."""
    tool = make_tool_info("t", "", {"properties": {"a": {}}},
                          {"properties": {"b": {}}})
    payload = tool.to_dict()
    payload["input_schema"]["properties"]["a"] = "broken"
    payload["output_schema"]["properties"]["b"] = "broken"
    assert tool.input_schema == {"properties": {"a": {}}}
    assert tool.output_schema == {"properties": {"b": {}}}


def test_make_tool_infos_keeps_order_and_reads_output_schema():
    """Список инструментов собирается в порядке ответа сервера вместе со схемами."""
    tools = make_tool_infos([
        {"name": "echo", "description": "Эхо", "input_schema": {"type": "object"},
         "output_schema": {"type": "object"}},
        {"name": "add", "description": None, "input_schema": None},
    ])
    assert [tool.name for tool in tools] == ["echo", "add"]
    assert tools[1].description == "" and tools[1].input_schema == {}
    assert tools[0].output_schema == {"type": "object"}
    assert tools[1].output_schema == {}


def test_tool_result_dict_contract():
    """Словарь результата содержит все поля, которые читают промпт и отчёт."""
    result = MCPToolResult(tool="get_user", arguments={"user_id": 1},
                           structured={"id": 1, "name": "Leanne"},
                           text='{"id": 1}', duration_ms=12)
    assert result.to_dict() == {
        "tool": "get_user",
        "arguments": {"user_id": 1},
        "structured": {"id": 1, "name": "Leanne"},
        "text": '{"id": 1}',
        "is_error": False,
        "duration_ms": 12,
    }


def test_tool_result_dict_copies_payload():
    """Аргументы и результат копируются: правка отчёта не меняет результат вызова."""
    result = MCPToolResult(tool="get_user", arguments={"user_id": 1},
                           structured={"id": 1})
    payload = result.to_dict()
    payload["arguments"]["user_id"] = 99
    payload["structured"]["id"] = 99
    assert result.arguments == {"user_id": 1}
    assert result.structured == {"id": 1}
