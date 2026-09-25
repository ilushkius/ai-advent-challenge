"""Спецификация сервера флота: имя, команда запуска, описание и кэш каталога.

Флот MCP-серверов дня 20 описывается ДАННЫМИ (``day20/mcp_servers.json``), а не
кодом: чтобы добавить сервер, достаточно дописать запись в файл — реестр дня
поднимает по ней отдельное stdio-соединение. Формат записи::

    {"name": "search_server", "command": "uv",
     "args": ["run", "python", "mcp_servers/search_server/server.py"],
     "description": "Поиск данных", "tools_cache": []}

Поле ``tools_cache`` хранит последний прочитанный ``tools/list`` этого сервера.
Это не удобство, а необходимость: интерфейс и планировщик плана должны видеть
каталог инструментов, даже когда сервер ещё не поднялся (или поднялся не сразу),
а ``GET /mcp/servers`` — показывать состав флота без запуска процессов.

``target`` собирает команду в строку — ровно тот вид, который разбирает
``domain/mcp_target.parse_target`` ('' '' ). Токены с пробелами (Windows-пути)
заключаются в кавычки: ``parse_target`` понимает их и снимает сам.

Модуль чистый: ``config`` и стандартная библиотека, никакого MCP SDK.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..core import config

#: Ключ записей флота в файле конфигурации.
SERVERS_KEY = "servers"


class MCPServerSpecError(ValueError):
    """Конфигурация флота не разобрана: битый JSON или негодная запись сервера."""


@dataclass(frozen=True, slots=True)
class MCPServerSpec:
    """Один сервер флота: как его запустить и что он обещает в описании."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    description: str = ""
    tools_cache: tuple[dict[str, Any], ...] = field(default=())

    @property
    def target(self) -> str:
        """Строка цели для ``parse_target``: команда и аргументы через пробел."""
        return " ".join(_quote(part) for part in (self.command, *self.args))

    def to_dict(self) -> dict[str, Any]:
        """Запись сервера для файла конфигурации (без состояния подключения)."""
        return {
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "description": self.description,
            "tools_cache": [dict(tool) for tool in self.tools_cache],
        }

    def to_status(self, *, connected: bool, state: str, tool_count: int,
                  error: str | None = None) -> dict[str, Any]:
        """Запись сервера для API: конфигурация плюс состояние подключения."""
        return {
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "description": self.description,
            "target": self.target,
            "transport": "stdio",
            "connected": connected,
            "state": state,
            "tool_count": tool_count,
            "error": error,
        }


def _quote(token: str) -> str:
    """Токен команды: токены с пробелами и кавычками берутся в двойные кавычки."""
    text = str(token)
    if text and not any(char in text for char in ' \t"'):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def load_server_specs(path: str | Path) -> list[MCPServerSpec]:
    """Читает файл флота: список серверов; отсутствующий файл — пустой список.

    Отсутствие файла — не ошибка: приложение поднимается и без флота (тогда
    оркестрация честно скажет, что серверов нет). Негодный JSON — ошибка: молча
    работать с пустым флотом, когда файл есть, но испорчен, значит скрыть причину.
    """
    file = Path(path)
    if not file.is_file():
        return []
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MCPServerSpecError(f"Файл серверов не разобран ({file}): {exc}") from exc
    return validate_specs(payload)


def validate_specs(payload: Any) -> list[MCPServerSpec]:
    """Проверяет конфигурацию флота и нормализует её в список ``MCPServerSpec``.

    Проверяется то, без чего сервер нельзя запустить и различить: имя и команда
    непусты и в границах ``config``, имена уникальны, ``args`` — список строк,
    ``tools_cache`` — список словарей. Порядок записей сохраняется: он же порядок
    маршрутизации (первый сервер с таким инструментом выигрывает).
    """
    if isinstance(payload, dict):
        payload = payload.get(SERVERS_KEY)
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise MCPServerSpecError(
            f"Конфигурация флота должна быть объектом с списком «{SERVERS_KEY}»"
        )
    specs: list[MCPServerSpec] = []
    seen: set[str] = set()
    for index, record in enumerate(payload):
        spec = _validate_spec(record, index)
        if spec.name in seen:
            raise MCPServerSpecError(f"Сервер «{spec.name}» объявлен дважды")
        seen.add(spec.name)
        specs.append(spec)
    return specs


def _validate_spec(record: Any, index: int) -> MCPServerSpec:
    """Одна запись флота: имя, команда, аргументы, описание и кэш инструментов."""
    if not isinstance(record, dict):
        raise MCPServerSpecError(f"Запись сервера {index} должна быть объектом")
    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MCPServerSpecError(f"У записи {index} не указано имя сервера «name»")
    name = name.strip()
    if len(name) > config.MCP_SERVER_NAME_MAX:
        raise MCPServerSpecError(
            f"Имя сервера «{name}» длиннее {config.MCP_SERVER_NAME_MAX} символов"
        )
    command = record.get("command")
    if not isinstance(command, str) or not command.strip():
        raise MCPServerSpecError(f"У сервера «{name}» не указана команда запуска «command»")
    args = record.get("args") or []
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise MCPServerSpecError(
            f"Аргументы сервера «{name}» должны быть списком строк «args»"
        )
    description = record.get("description") or ""
    if not isinstance(description, str):
        raise MCPServerSpecError(f"Описание сервера «{name}» должно быть строкой")
    cache = record.get("tools_cache") or []
    if not isinstance(cache, list) or not all(isinstance(item, dict) for item in cache):
        raise MCPServerSpecError(
            f"Кэш инструментов сервера «{name}» должен быть списком объектов"
        )
    if len(cache) > config.MCP_FLEET_TOOLS_MAX:
        raise MCPServerSpecError(
            f"Кэш инструментов сервера «{name}» длиннее {config.MCP_FLEET_TOOLS_MAX} записей"
        )
    return MCPServerSpec(
        name=name,
        command=command.strip(),
        args=tuple(args),
        description=description.strip()[:config.MCP_SERVER_DESCRIPTION_MAX],
        tools_cache=tuple(dict(tool) for tool in cache),
    )


def dump_specs(specs: Iterable[MCPServerSpec]) -> dict[str, Any]:
    """Обратный вид: словарь для записи в файл конфигурации флота."""
    return {SERVERS_KEY: [spec.to_dict() for spec in specs]}


def find_spec(specs: Sequence[MCPServerSpec], name: str) -> MCPServerSpec | None:
    """Сервер по имени (``None`` — в конфигурации такого нет)."""
    for spec in specs:
        if spec.name == name:
            return spec
    return None
