"""Техническая обвязка вызовов MCP-сервера файлов (день 34): ``FileMCPCalls``.

Модуль отделён от службы ассистента файлов по той же причине, что ``rag_llm`` отделён
от ``rag_service``: «поднять процесс, вызвать инструмент и разобрать ответ» — это
транспорт, а «решить, какие шаги выполнить и что записать в историю» — предметная
логика дня. Служба держит один объект ``FileMCPCalls`` на процесс и о SDK не знает.

Три вещи здесь:

- ``FileMCPError`` — сервер файлов не поднялся или соединение оборвалось. Это не
  ошибка шага: шаг ещё не начинался, и вызывающий код (служба, роутер) решает, что
  делать — обработчик роутера переводит её в 500;
- ленивое подключение — стандартный ввод-вывод stdio-процесса поднимается при первом
  вызове инструмента, а не в конструкторе: интерфейс и ``lifespan`` создают службу на
  старте, а процесс сервера нужен только в момент прогона;
- ``call`` — один вызов инструмента с ЧЕТЫРЬМЯ формами ответа, приведёнными к одной:
  успех, разобранный результат, текст ошибки и время в миллисекундах. Ошибка самого
  инструмента (``is_error``) и обрыв связи — разные вещи, но вызывающему коду обе
  приходят текстом: он пишет их в журнал и останавливает прогон, а не падает стеком.

Содержимое файлов и тексты правок в лог НЕ попадают: логируется имя инструмента и
время, а не payload.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from ..core import config
from ..domain import file_assistant
from .mcp_client import MCPClient
from .mcp_errors import MCPError

__all__ = ["FileMCPCalls", "FileMCPError"]


class FileMCPError(RuntimeError):
    """MCP-сервер файлов не поднялся: соединение не открылось (роутер отвечает 500)."""


class FileMCPCalls:
    """Соединение с сервером файлов и вызовы его инструментов одним исходом."""

    def __init__(self, *, target: str = file_assistant.FILE_SERVER_TARGET,
                 cwd: Optional[object] = None, client: Optional[Any] = None) -> None:
        self._target = target
        self._cwd = cwd
        self._client = client
        self._server: Optional[Any] = None
        self._lock = threading.RLock()

    @property
    def server(self) -> Any:
        """MCP-клиент сервера файлов: подменённый или подключённый один раз.

        Соединение держится на процесс: поднимать stdio-сервер на каждый шаг плана
        значило бы платить секунды за одно и то же. Сбой подключения —
        ``FileMCPError``, а не сломанное состояние клиента.
        """
        if self._client is not None:
            return self._client
        with self._lock:
            if self._server is None:
                self._server = self._connect()
            return self._server

    def _connect(self) -> Any:
        """Поднимает stdio-сервер и читает его каталог; сбой — ``FileMCPError``."""
        client = MCPClient(self._target,
                           cwd=self._cwd if self._cwd is not None
                           else config.MCP_FLEET_CWD)
        try:
            client.connect()
            client.list_tools()
        except MCPError as exc:
            client.close()
            raise FileMCPError(str(exc)) from exc
        return client

    def call(self, name: str, arguments: dict) -> tuple:
        """Один вызов инструмента: ``(успех, разобранный результат, ошибка, мс)``.

        Недоступный сервер и обрыв связи ловятся исключением транспорта, а ошибка
        самого инструмента приходит данными (``is_error``) — вызывающий код отличает
        «шаг не выполнен из-за инструмента» от «сервера нет» по тексту, но обрабатывает
        одинаково: пишет ошибку в журнал.
        """
        try:
            client = self.server
        except FileMCPError as exc:
            return False, None, file_assistant.WARN_MCP_UNAVAILABLE.format(error=exc), 0
        try:
            result = client.call_tool(name, dict(arguments))
        except MCPError as exc:
            return False, None, file_assistant.WARN_MCP_UNAVAILABLE.format(error=exc), 0
        duration = int(getattr(result, "duration_ms", 0) or 0)
        if result.is_error:
            return False, self.payload(result), file_assistant.WARN_TOOL_FAILED.format(
                tool=name, error=result.text), duration
        return True, self.payload(result), "", duration

    @staticmethod
    def payload(result: Any) -> Any:
        """Результат инструмента в его естественной форме.

        Форм три, и все три приходят от настоящего сервера: объект (``read_file``,
        ``write_file``, ``apply_patch`` — ``structuredContent`` равен словарю
        инструмента); ``{"result": …}`` (SDK оборачивает возврат-список или строку —
        ``list_files``, ``search_in_files``, ``get_file_diff``); и просто текст, когда
        структуры нет (``json.loads`` текста, а если и это не JSON — текст как есть).
        Разбор форм живёт в одном месте: журнал, списки файлов и diff получают уже
        нормальное значение и о видах ответа MCP не знают.
        """
        structured = getattr(result, "structured", None)
        if structured is None:
            text = str(getattr(result, "text", "") or "").strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except ValueError:
                return text
        if isinstance(structured, dict):
            return structured["result"] if set(structured) == {"result"} else structured
        return structured

    def close(self) -> None:
        """Закрывает СВОЁ соединение (подменённый клиент не трогает)."""
        with self._lock:
            client = self._server
            self._server = None
        if client is not None:
            client.close()
