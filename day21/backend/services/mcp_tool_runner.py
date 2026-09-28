"""Вызов MCP-инструмента от начала до конца: допуск, вызов, отчёт (день 17).

Единственное место, где домен встречается с реестром. Агент, API и скрипт
демонстрации не собирают этот путь сами — они вызывают ``call`` или
``call_for_prompt`` и получают ``MCPToolCallOutcome``: что решили правила
допуска, ушёл ли запрос, что ответил сервер и сколько это заняло.

Почему неудачи — это результат, а не исключение. Ход агента не должен рушиться
из-за внешнего сервера: сбой связи (``reason_code="transport"``) и ошибка
инструмента (``"tool_error"``) возвращаются исходом со состоянием ``failed``, а
исключение остаётся только для программных ошибок (``except Exception`` тоже
превращается в исход — «инструмент не сработал» не равно «приложение сломалось»).

Реестр передаётся в конструктор (в тестах — фейковый) и по умолчанию берётся
реестр процесса: так агент не создаёт соединений, а пользуется тем, что открыл
пользователь в разделе «🔌 MCP».
"""
from __future__ import annotations

import time
from typing import Any

from shared.logging_utils import get_logger

from ..domain.mcp_intent import classify_tool_call
from ..domain.mcp_tool_call import (
    REASON_TOOL_ERROR,
    REASON_TRANSPORT,
    MCPToolCallEvent,
    MCPToolCallFSM,
    MCPToolCallOutcome,
    admission_reason,
)
from ..domain.mcp_tools import MCPToolInfo
from .mcp_client import MCPError
from .mcp_registry import MCPRegistry, get_mcp_registry

logger = get_logger(__name__)


class MCPToolRunner:
    """Вызов MCP-инструмента: проверка допуска, сам вызов, отчёт-результат.

    ``server_name`` выбирает, куда идёт вызов (день 20): без имени — активное
    соединение (раздел «🔌 MCP», как в дне 17), с именем — сервер флота
    (``registry.tools_of`` и ``registry.call_tool_on``). Правила допуска, коды
    причин и форма исхода в обоих случаях одни и те же: оркестратор и агент не
    должны знать, откуда пришёл инструмент.
    """

    def __init__(self, registry: MCPRegistry | None = None,
                 server_name: str | None = None) -> None:
        self._registry = registry
        self._server_name = server_name

    @property
    def registry(self) -> MCPRegistry:
        """Реестр вызова: переданный или реестр процесса (леновый singleton)."""
        return self._registry or get_mcp_registry()

    @property
    def server_name(self) -> str | None:
        """Сервер флота, к которому привязан раннер (None — активное соединение)."""
        return self._server_name

    def status(self) -> dict:
        """Состояние подключения (активного либо сервера флота)."""
        if self._server_name is None:
            return self.registry.status()
        for record in self.registry.servers():
            if record["name"] == self._server_name:
                return record
        return {"name": self._server_name, "connected": False, "state": "unknown",
                "tool_count": 0, "error": None}

    def connected(self) -> bool:
        """Есть ли открытое соединение с нужным сервером прямо сейчас."""
        if self._server_name is not None:
            return self.registry.connected(self._server_name)
        client = self.registry.client
        return client is not None and client.connected

    def available_tools(self) -> list[MCPToolInfo]:
        """Каталог сервера (``[]`` — если сервера нет в флоте или соединения нет).

        Отсутствие каталога — не ошибка вызова: по пустому списку правила допуска
        скажут «нет соединения» или «инструмент не найден», а не уронят запрос.
        """
        try:
            if self._server_name is not None:
                return self.registry.tools_of(self._server_name)
            return self.registry.tools()
        except MCPError as exc:
            logger.debug("MCP: каталог инструментов недоступен: %s", exc)
            return []

    def call(self, tool_name: str,
             arguments: dict[str, Any] | None = None) -> MCPToolCallOutcome:
        """Вызывает инструмент, если он допущен; иначе возвращает отказ."""
        fsm = MCPToolCallFSM()
        fsm.handle(MCPToolCallEvent.PLAN)
        args = dict(arguments or {})
        catalog = self.available_tools()
        connected = self.connected()
        reason, code = admission_reason(tool_name, args, catalog, connected)
        if reason is not None:
            fsm.handle(MCPToolCallEvent.REJECT)
            logger.info("MCP: вызов %s отклонён (%s): %s", tool_name, code, reason)
            return MCPToolCallOutcome(
                state=fsm.state, detected=True, connected=connected, accepted=False,
                tool=tool_name, arguments=args, reason_code=code, error=reason,
            )

        fsm.handle(MCPToolCallEvent.INVOKE)
        started = time.perf_counter()
        try:
            if self._server_name is not None:
                result = self.registry.call_tool_on(self._server_name, tool_name, args)
            else:
                result = self.registry.call_active_tool(tool_name, args)
        except MCPError as exc:
            return self._failed(fsm, tool_name, args, str(exc), REASON_TRANSPORT,
                                started)
        except Exception as exc:  # noqa: BLE001 — сбой инструмента не роняет ход
            return self._failed(fsm, tool_name, args, str(exc), REASON_TRANSPORT,
                                started)

        if result.is_error:
            return self._failed(
                fsm, tool_name, args,
                result.text or "Инструмент вернул ошибку без описания",
                REASON_TOOL_ERROR, started, result=result,
            )
        fsm.handle(MCPToolCallEvent.SUCCEED)
        logger.info("MCP: инструмент %s вернул результат за %d мс",
                    tool_name, result.duration_ms)
        return MCPToolCallOutcome(
            state=fsm.state, detected=True, connected=connected, accepted=True,
            tool=tool_name, arguments=args, result=result,
            duration_ms=result.duration_ms,
        )

    def call_for_prompt(self, prompt: str) -> MCPToolCallOutcome:
        """Решает по реплике, нужен ли инструмент, и вызывает его.

        Инструмент не вызывался (``state="idle"``, ``detected=False``) — обычный
        случай: «Сколько будет 2+2?» не упоминает ни пользователей, ни постов.
        """
        catalog = self.available_tools()
        plan = classify_tool_call(prompt, [tool.name for tool in catalog])
        if plan is None:
            return MCPToolCallOutcome(connected=self.connected())
        logger.debug("MCP: реплика распознана как %s (фраза %r)", plan.tool, plan.phrase)
        return self.call(plan.tool, plan.arguments)

    def _failed(self, fsm: MCPToolCallFSM, tool_name: str, args: dict[str, Any],
                error: str, reason_code: str, started: float,
                result: Any = None) -> MCPToolCallOutcome:
        """Общий исход неудачного вызова: состояние ``failed`` и причина."""
        fsm.handle(MCPToolCallEvent.FAIL)
        logger.warning("MCP: вызов %s не удался (%s): %s", tool_name, reason_code, error)
        return MCPToolCallOutcome(
            state=fsm.state, detected=True, connected=self.connected(), accepted=False,
            tool=tool_name, arguments=args, result=result,
            reason_code=reason_code, error=error, duration_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> int:
    """Миллисекунды с момента ``started`` (для исходов без результата сервера)."""
    return int((time.perf_counter() - started) * 1000)
