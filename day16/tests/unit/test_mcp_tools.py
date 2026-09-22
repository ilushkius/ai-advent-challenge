"""Тесты структуры инструмента MCP (день 16): нормализация полей контракта.

Контракт дня — три поля: ``name``, ``description``, ``input_schema``. Тесты
фиксируют нормализацию (пустые описание и схема не превращаются в ``None``) и
негативный сценарий: инструмент без имени — ошибка, а не запись-призрак в списке.
"""
import pytest

from backend.domain.mcp_tools import (
    MCPToolError,
    MCPToolInfo,
    make_tool_info,
    make_tool_infos,
)


def test_fields_and_to_dict_contract():
    """``to_dict`` отдаёт ровно три поля контракта с сохранением значений."""
    tool = make_tool_info("fetch", "Загружает URL", {"type": "object"})
    assert tool.to_dict() == {
        "name": "fetch",
        "description": "Загружает URL",
        "input_schema": {"type": "object"},
    }


def test_missing_description_and_schema_normalized():
    """Отсутствующие описание и схема — ``""`` и ``{}``, а не ``None``."""
    tool = make_tool_info("list_allowed_directories", None, None)
    assert tool == MCPToolInfo(name="list_allowed_directories", description="",
                              input_schema={})
    assert tool.to_dict()["input_schema"] == {}


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


def test_non_dict_schema_becomes_empty():
    """Неожиданная схема не ломает разбор: вместо неё пустой объект."""
    assert make_tool_info("t", "", "not-a-schema").input_schema == {}


def test_to_dict_copies_schema():
    """Правка словаря из ``to_dict`` не меняет сам инструмент (защита от алиасов)."""
    tool = make_tool_info("t", "", {"properties": {"a": {}}})
    payload = tool.to_dict()
    payload["input_schema"]["properties"]["a"] = "broken"
    assert tool.input_schema == {"properties": {"a": {}}}


def test_make_tool_infos_keeps_order():
    """Список инструментов собирается в порядке ответа сервера."""
    tools = make_tool_infos([
        {"name": "echo", "description": "Эхо", "input_schema": {"type": "object"}},
        {"name": "add", "description": None, "input_schema": None},
    ])
    assert [tool.name for tool in tools] == ["echo", "add"]
    assert tools[1].description == "" and tools[1].input_schema == {}
