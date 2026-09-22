"""Инструмент MCP-сервера как структура дня (день 16).

День 16 только ЧИТАЕТ список инструментов: ``name``, ``description``,
``input_schema`` (JSON Schema аргументов, как её отдаёт сервер). Вызова
инструментов в этом дне нет — задача дня в том, чтобы установить соединение и
показать каталог возможностей сервера.

Модуль чистый: MCP SDK здесь не импортируется (``mcp.types.Tool`` разбирает
сервис), поэтому правила нормализации тестируются без сети.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


class MCPToolError(ValueError):
    """Описание инструмента не разобрано (например, у инструмента нет имени)."""


@dataclass(frozen=True, slots=True)
class MCPToolInfo:
    """Инструмент MCP-сервера: имя, описание и схема аргументов."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Словарь ровно с тремя полями контракта: name, description, input_schema.

        Схема копируется ГЛУБОКО: Pydantic-схема API сохраняет ссылку на этот
        словарь, поэтому правка ответа не должна задевать сам инструмент.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(self.input_schema),
        }


def make_tool_info(
    name: str | None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
) -> MCPToolInfo:
    """Собирает ``MCPToolInfo`` из полей ответа ``tools/list``.

    Имя обязательно: без него инструмент нельзя ни показать, ни (в будущем)
    вызвать, поэтому пустое имя — ошибка, а не молчаливое пропускание записи.
    Отсутствующие описание и схема нормализуются в ``""`` и ``{}``: UI и API
    тогда не различают «поля нет» и «поле пустое».
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise MCPToolError("У инструмента MCP-сервера нет имени (поле name пустое)")
    schema = dict(input_schema) if isinstance(input_schema, dict) else {}
    return MCPToolInfo(
        name=clean_name,
        description=(description or "").strip(),
        input_schema=schema,
    )


def make_tool_infos(tools: list[dict[str, Any]]) -> list[MCPToolInfo]:
    """Собирает список структур из словарей ``{"name", "description", "input_schema"}``."""
    return [
        make_tool_info(tool.get("name"), tool.get("description"), tool.get("input_schema"))
        for tool in tools
    ]
