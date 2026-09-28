"""Блок результата оркестрации в системном промпте (день 20).

Когда реплика запустила флоу по нескольким серверам, его результат уходит модели
отдельным системным блоком — рядом с блоками памяти, состояния задачи и данных MCP.
Смысл тот же, что у блока пайплайна дня 19: «данные уже собраны, не выдумывай поля
и не зови инструменты заново». Добавлено то, ради чего день и делался: блок
называет СЕРВЕРЫ и инструменты каждого шага — модель видит, откуда пришли данные.

Прогон ``failed`` блока не даёт: сообщать нечего (правило дня 17 — данные неудачного
вызова в промпт не попадают). Досрочно завершённый (``stopped``) блок даёт: важно,
чтобы модель знала про невыполненное условие, а не отвечала так, будто данные есть.

Модуль чистый: только стандартная библиотека (эталон — ``pipeline_prompt.py``).
"""
from __future__ import annotations

from typing import Any, Mapping

ORCHESTRATION_BLOCK_HEADER = "## Результат оркестрации"
ORCHESTRATION_BLOCK_FOOTER = (
    "Данные собраны цепочкой MCP-инструментов; используй их как источник правды "
    "и не выдумывай полей, которых здесь нет."
)

#: Статусы прогона, при которых блок не собирается.
_SILENT_STATUSES = ("failed", "")


def render_orchestration_block(report: Mapping[str, Any] | None) -> str:
    """Системный блок с результатом прогона (``""`` — блока нет)."""
    if not report or not report.get("detected"):
        return ""
    status = str(report.get("status") or "")
    if status in _SILENT_STATUSES:
        return ""
    lines = [ORCHESTRATION_BLOCK_HEADER]
    query = str(report.get("query") or "")
    if query:
        lines.append(f"Запрос: {query}")
    servers = [str(name) for name in (report.get("servers_used") or [])]
    lines.append(f"Серверы: {', '.join(servers) if servers else '—'}")
    steps = [step for step in (report.get("steps") or []) if isinstance(step, Mapping)]
    if steps:
        lines.append("Шаги:")
        lines.extend(step_line(step) for step in steps)
    message = report.get("message") or ""
    if message:
        lines.append(f"Итог: {message}")
    lines.append(ORCHESTRATION_BLOCK_FOOTER)
    return "\n".join(lines)


def step_line(step: Mapping[str, Any]) -> str:
    """Строка одного шага: инструмент, сервер, статус и время.

    Поля читаются устойчиво: у шага может не быть результата (``output_result``
    пуст у неупавшего шага с невыполненным условием), и строка обязана остаться
    читаемой — иначе отчёт о прогоне падал бы на том самом шаге, который и сломался.
    """
    tool = str(step.get("tool_name") or step.get("tool") or "?")
    server = str(step.get("server_name") or step.get("server") or "—")
    status = str(step.get("status") or "")
    duration = int(step.get("duration_ms") or 0)
    line = f"- {tool} ({server}): {status}, {duration} мс"
    error = str(step.get("error_message") or "")
    return f"{line} — {error}" if error else line


def structured_of(step: Mapping[str, Any]) -> Mapping[str, Any]:
    """Структурированный выход шага (пустой словарь, если результата нет)."""
    output = step.get("output_result")
    if not isinstance(output, Mapping):
        return {}
    structured = output.get("structured")
    return structured if isinstance(structured, Mapping) else {}
