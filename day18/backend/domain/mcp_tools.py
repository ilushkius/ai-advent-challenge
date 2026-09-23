"""Инструмент MCP-сервера и результат его вызова — структуры дня (день 17).

Каталог инструментов (``tools/list``) день 17 не только читает, но и вызывает
(``tools/call``), поэтому здесь два типа данных:

- ``MCPToolInfo`` — инструмент: имя, описание, ``input_schema`` (аргументы) и
  ``output_schema`` (структура результата, если сервер её публикует);
- ``MCPToolResult`` — ответ инструмента: структурированный результат
  (``structuredContent``), текстовые блоки и флаг ``is_error``.

Конструктор ``MCPToolResult`` работает на данных, а не на объектах SDK: разбор
``CallToolResult`` делает клиент (``MCPClient._raw_parts``), а тесты собирают
результат напрямую — поэтому модуль чистый, MCP SDK здесь не импортируется.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


class MCPToolError(ValueError):
    """Описание инструмента не разобрано (например, у инструмента нет имени)."""


@dataclass(frozen=True, slots=True)
class MCPToolInfo:
    """Инструмент MCP-сервера: имя, описание и схемы аргументов и результата."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Словарь ровно с четырьмя полями контракта: name, description и схемы.

        Схемы копируются ГЛУБОКО: Pydantic-схема API сохраняет ссылку на этот
        словарь, поэтому правка ответа не должна задевать сам инструмент.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(self.input_schema),
            "output_schema": copy.deepcopy(self.output_schema),
        }


def make_tool_info(
    name: str | None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> MCPToolInfo:
    """Собирает ``MCPToolInfo`` из полей ответа ``tools/list``.

    Имя обязательно: без него инструмент нельзя ни показать, ни вызвать, поэтому
    пустое имя — ошибка, а не молчаливое пропускание записи. Отсутствующие
    описание и схемы нормализуются в ``""`` и ``{}``: UI и API тогда не различают
    «поля нет» и «поле пустое». ``output_schema`` приходит не от всякого сервера —
    инструмент без объявленного результата остаётся полностью рабочим.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise MCPToolError("У инструмента MCP-сервера нет имени (поле name пустое)")
    return MCPToolInfo(
        name=clean_name,
        description=(description or "").strip(),
        input_schema=_as_schema(input_schema),
        output_schema=_as_schema(output_schema),
    )


def make_tool_infos(tools: list[dict[str, Any]]) -> list[MCPToolInfo]:
    """Собирает список структур из словарей ``{"name", "description", "input_schema"}``."""
    return [
        make_tool_info(tool.get("name"), tool.get("description"),
                       tool.get("input_schema"), tool.get("output_schema"))
        for tool in tools
    ]


def _as_schema(schema: Any) -> dict[str, Any]:
    """Схема из ответа сервера: словарь как есть, всё остальное — пустой словарь."""
    return dict(schema) if isinstance(schema, dict) else {}


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """Ответ инструмента: структурированный результат, текст и признак ошибки.

    ``is_error`` приходит от сервера: ошибка самого инструмента — это данные
    ответа, а не исключение (``ExternalAPIError`` сервера дня 17 доезжает сюда
    текстом, см. ``structured=None``, ``text=...``). Транспортные сбои и таймауты
    до этого типа не доходят — их ловит клиент и отдаёт исключением.
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    structured: Any = None
    text: str = ""
    is_error: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Словарь контракта ответа: аргументы и результат копируются глубоко."""
        return {
            "tool": self.tool,
            "arguments": copy.deepcopy(self.arguments),
            "structured": copy.deepcopy(self.structured),
            "text": self.text,
            "is_error": self.is_error,
            "duration_ms": self.duration_ms,
        }
