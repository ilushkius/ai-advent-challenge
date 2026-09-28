"""Блок результата MCP-инструмента для системного промпта (день 17).

Успешный вызов инструмента превращается в блок системного сообщения: модель
видит данные как источник правды и не выдумывает поля. Блок собирается здесь, а
не в агенте, потому что это текст контракта — его проверяют тесты, а менять
формулировку правки (заголовок «## Данные MCP-инструмента») нужно в одном месте.

Почему блок добавляется только при ``DONE``: отказ правил допуска
(``REJECTED``), сбой связи (``FAILED``) и «вызов не потребовался» (``IDLE``) —
это отсутствие данных, а не данные. Модель получает пустую строку, а о самой
неудаче узнаёт пользователь: она видна в поле ``mcp`` ответа API.

Модуль чистый: ни MCP SDK, ни HTTP, ни Streamlit — только ``json``.
"""
from __future__ import annotations

import json
from typing import Any

from .mcp_tool_call import MCPToolCallOutcome, MCPToolCallState

#: Заголовок блока: по нему тест и отчёт проверяют, что данные дошли до промпта.
MCP_BLOCK_HEADER = "## Данные MCP-инструмента"

#: Строка-инструкция: без неё модель дополняет данные своими догадками.
MCP_BLOCK_FOOTER = (
    "Используй эти данные как источник правды в ответе и не выдумывай поля, "
    "которых здесь нет."
)


def render_mcp_tool_block(outcome: MCPToolCallOutcome) -> str:
    """Блок системного промпта с результатом инструмента (``""`` — данных нет)."""
    if outcome.state is not MCPToolCallState.DONE or outcome.result is None:
        return ""
    payload: Any = outcome.result.structured
    if payload is None:
        payload = outcome.result.text
    lines = [
        MCP_BLOCK_HEADER,
        f"Инструмент: {outcome.tool or outcome.result.tool}",
        "Аргументы: " + _as_json(outcome.arguments),
        "Результат (JSON): " + _as_json(payload),
        "",
        MCP_BLOCK_FOOTER,
    ]
    return "\n".join(lines)


def _as_json(value: Any) -> str:
    """Значение одной строкой JSON (``sort_keys`` — чтобы блок был воспроизводим)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
