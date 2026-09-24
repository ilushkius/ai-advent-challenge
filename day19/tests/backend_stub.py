"""Стенд бэкенда дня для тестов MCP-инструментов планировщика (день 18).

Инструменты планировщика не пишут в БД сами: их тела — вызов
``POST /scheduler/tasks`` бэкенда дня. Чтобы проверить это без запуска настоящего
uvicorn, поднимается локальный HTTP-сервер, который отвечает на ту же ручку
заготовленным ответом (та же идея, что у ``stub_api.py`` дня 17, где так
проверялся внешний API).

Стенд проверяет и отказ: ``interval_seconds = 0`` получает 400 с текстом причины —
так тест видит, что ошибка бэкенда доезжает до модели как ``is_error`` с понятным
текстом, а не как обрыв связи.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

#: Текст отказа для «плохих» аргументов (как его формулирует домен дня).
BAD_INTERVAL_DETAIL = (
    "Аргумент «interval_seconds» инструмента «collect_data» должен быть целым "
    "числом от 1 до 86400, получено 0"
)

#: Номера, которые стенд «присваивает» задачам, — по ним тест сверяет ответ.
TASK_ID = 41
REMINDER_ID = 7
SUMMARY_ID = 3


def _task(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Задача в форме ответа ``POST /scheduler/tasks``."""
    return {
        "id": TASK_ID,
        "name": f"{tool}: {arguments.get('name') or arguments.get('text') or ''}",
        "tool_name": tool,
        "arguments": arguments,
        "schedule_type": "date" if tool == "schedule_reminder" else "interval",
        "schedule_value": {"seconds": arguments.get("interval_seconds", 10)},
        "schedule_label": "каждые 10 с",
        "status": "active",
        "next_run_at": "2026-09-23T10:00:10+00:00",
        "allowed_events": ["pause", "complete"],
    }


def _result(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Результат немедленного шага инструмента (как у настоящего бэкенда)."""
    if tool == "schedule_reminder":
        return {
            "reminder": {
                "id": REMINDER_ID,
                "text": arguments.get("text"),
                "remind_at": "2026-09-23T10:00:30+00:00",
                "status": "scheduled",
            },
            "reminder_id": REMINDER_ID,
        }
    if tool == "collect_data":
        return {"collection": {
            "name": arguments.get("name"),
            "source_url": arguments.get("source_url"),
            "records_saved": 1,
            "records_in_payload": 3,
            "last_collected_at": "2026-09-23T10:00:00+00:00",
            "collected_id": 5,
        }}
    return {"summary": {
        "id": SUMMARY_ID,
        "name": arguments.get("name"),
        "content": "Сводка «posts» за период 2026-09-23 09:59:40 — 10:00:00 (20 с).",
        "period_start": "2026-09-23T09:59:40+00:00",
        "period_end": "2026-09-23T10:00:00+00:00",
        "total_records": 2,
        "key_metrics": {"numeric": {"id": {"avg": 1.5, "min": 1, "max": 2}}},
    }}


class _Handler(BaseHTTPRequestHandler):
    """Ручка ``POST /scheduler/tasks`` с заготовленным ответом."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 — имя задано базовым классом
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"detail": "тело запроса не JSON"})
            return
        tool = str(body.get("tool") or "")
        arguments = body.get("arguments") or {}
        if arguments.get("interval_seconds") == 0:
            self._json(400, {"detail": BAD_INTERVAL_DETAIL})
            return
        self._json(201, {
            "task": _task(tool, arguments),
            "result": _result(tool, arguments),
            "immediate": True,
            "message": f"Инструмент {tool} поставлен в планировщик",
            "error": None,
        })

    def _json(self, status: int, payload: Any) -> None:
        """Отвечает JSON-ом с нужным кодом."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:
        """Молчит: вывод стенда не должен засорять вывод тестов."""


@contextmanager
def backend_api_stub() -> Iterator[str]:
    """Поднимает стенд на свободном порту и отдаёт его базовый URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
