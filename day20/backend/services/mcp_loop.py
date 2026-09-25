"""Цикл событий в отдельном потоке: приём корутин из синхронного кода (день 17).

MCP SDK асинхронный, а роуты FastAPI и Streamlit — синхронные, поэтому клиенту
нужен «мост»: daemon-поток с циклом событий, в который синхронный код отправляет
корутины и ждёт результат. Мост вынесен из ``mcp_client.py`` отдельным модулем:
протокол и многопоточная обвязка читаются раздельно, и каждый из них укладывается
в лимит строк.

Три операции покрывают всё, что нужно клиенту:

- ``submit`` — выполнить корутину и дождаться результата (``tools/list``,
  ``tools/call``); по таймауту будущее отменяется, а вызывающий получает ошибку,
  которую ему передали фабрикой ``on_timeout`` — без знания про MCP;
- ``spawn`` — запустить долгоживущую корутину без ожидания (задача соединения,
  которая живёт до ``shutdown``);
- ``call_soon`` — выполнить функцию в потоке цикла (установить событие остановки).

Модуль не импортирует MCP SDK: он про ``asyncio`` и ``threading``, поэтому его
поведение проверяется без сервера.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
from typing import Any, Callable

#: Запас на запуск потока с циклом: ожидание его готовности из чужого потока.
SUBMIT_GRACE = 10.0


class MCPEventLoop:
    """Цикл событий в daemon-потоке: ``submit`` / ``spawn`` / ``call_soon`` / ``stop``."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """Поднят ли поток с живым циклом событий."""
        return self._loop is not None and not self._loop.is_closed()

    def submit(self, coro: Any, timeout: float,
               on_timeout: Callable[[], Exception]) -> Any:
        """Выполняет корутину и ждёт результат; таймаут — исключение из ``on_timeout``."""
        future = self.spawn(coro)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise on_timeout() from exc

    def spawn(self, coro: Any) -> concurrent.futures.Future:
        """Запускает корутину без ожидания (долгоживущая задача соединения)."""
        return asyncio.run_coroutine_threadsafe(coro, self._ensure())

    def call_soon(self, fn: Callable[[], None]) -> None:
        """Вызывает функцию в потоке цикла (установить событие остановки)."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(fn)

    def stop(self, timeout: float) -> None:
        """Останавливает цикл, ждёт поток и закрывает цикл (повторный вызов — no-op)."""
        loop, thread, self._loop, self._thread = self._loop, self._thread, None, None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=timeout)
        with contextlib.suppress(Exception):
            loop.close()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        """Поднимает поток с циклом событий (один на объект, daemon)."""
        if self.running:
            return self._loop  # type: ignore[return-value]
        loop = asyncio.new_event_loop()
        started = threading.Event()
        thread = threading.Thread(
            target=_run_loop, args=(loop, started), name=self._name, daemon=True,
        )
        thread.start()
        started.wait(timeout=SUBMIT_GRACE)
        self._loop, self._thread = loop, thread
        return loop


def _run_loop(loop: asyncio.AbstractEventLoop, started: threading.Event) -> None:
    """Тело служебного потока: цикл событий живёт до ``loop.stop()``."""
    asyncio.set_event_loop(loop)
    loop.call_soon(started.set)  # сигнал: цикл готов принимать корутины
    loop.run_forever()
