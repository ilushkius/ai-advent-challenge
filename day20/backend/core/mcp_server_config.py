"""Доступ к файлу конфигурации флота MCP-серверов (день 20).

Домен (``domain/mcp_server_spec.py``) описывает ФОРМАТ конфигурации и ничего не
знает про диск; этот модуль — его связь с файлом ``day20/mcp_servers.json``:
читать, обновить кэш инструментов, записать обратно.

Запись атомарная (``.tmp`` + ``os.replace``): файл читают и реестр, и второй
процесс дня (Streamlit), а частично записанный JSON они не разберут. Обновляется
ровно поле ``tools_cache`` одного сервера, остальные записи сохраняются как были,
включая порядок, — поэтому ручные правки файла не теряются.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from ..core import config
from ..domain.mcp_server_spec import (
    SERVERS_KEY,
    MCPServerSpec,
    MCPServerSpecError,
    dump_specs,
    find_spec,
    load_server_specs,
)

#: Импорт ``get_logger`` через строку: shared/ в sys.path добавляет backend/__init__.py.
from shared.logging_utils import get_logger  # noqa: E402

logger = get_logger(__name__)


def load_specs(path: str | Path | None = None) -> list[MCPServerSpec]:
    """Серверы флота из файла (по умолчанию — ``config.MCP_SERVERS_FILE``)."""
    return load_server_specs(path or config.MCP_SERVERS_FILE)


def save_tools_cache(name: str, tools: Sequence[object],
                     path: str | Path | None = None) -> Path:
    """Записывает кэш ``tools/list`` сервера ``name`` в файл конфигурации.

    ``tools`` — либо ``MCPToolInfo`` (у них есть ``to_dict``), либо уже словари.
    Файла нет — ошибка: конфигурация флота не должна появляться «на лету», её
    заводит человек (иначе кэш переживёт исчезновение файла и запутает состояние).
    """
    file = Path(path or config.MCP_SERVERS_FILE)
    if not file.is_file():
        raise MCPServerSpecError(f"Файл серверов не найден: {file}")
    specs = load_server_specs(file)
    spec = find_spec(specs, name)
    if spec is None:
        known = ", ".join(item.name for item in specs) or "нет"
        raise MCPServerSpecError(
            f"Сервер «{name}» не объявлен в файле серверов. Известны: {known}"
        )
    payload = dump_specs(_with_cache(spec, tools, specs))
    _write_atomic(file, payload)
    logger.info("Флот MCP: кэш инструментов сервера %s обновлён (%d)", name, len(spec.tools_cache))
    return file


def _with_cache(spec: MCPServerSpec, tools: Sequence[object],
                specs: Sequence[MCPServerSpec]) -> list[MCPServerSpec]:
    """Список серверов, где у ``spec`` заменён только кэш инструментов."""
    cache = tuple(_tool_dict(tool) for tool in tools)
    updated = MCPServerSpec(
        name=spec.name, command=spec.command, args=spec.args,
        description=spec.description, tools_cache=cache,
    )
    return [updated if item.name == spec.name else item for item in specs]


def _tool_dict(tool: object) -> dict:
    """Инструмент в виде словаря: структуры дня отдают себя сами."""
    to_dict = getattr(tool, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if isinstance(tool, dict):
        return dict(tool)
    raise MCPServerSpecError(f"Инструмент не описан словарём: {tool!r}")


def _write_atomic(file: Path, payload: dict) -> None:
    """Пишет JSON в ``<file>.tmp`` и подменяет файл одним ``os.replace``."""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = file.with_suffix(file.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, file)
    except OSError as exc:
        raise MCPServerSpecError(f"Не удалось записать файл серверов {file}: {exc}") from exc


__all__ = ["SERVERS_KEY", "load_specs", "save_tools_cache"]
