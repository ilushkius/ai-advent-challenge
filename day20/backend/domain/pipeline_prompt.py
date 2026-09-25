"""Блок результата пайплайна в системном промпте (день 19).

Когда реплика запустила пайплайн, его результат уходит модели отдельным системным
блоком — рядом с блоками памяти, состояния задачи и данных MCP. Блок короткий:
имя пайплайна, строки шагов с объёмами и итог. Смысл — «данные уже собраны, не
выдумывай поля и не зови инструменты заново».

Прогоны ``failed`` и нераспознанные реплики блока не дают: сообщать модели нечего
(у неудачного прогона в промпт не попадает ничего — правило дня 17 для данных
неудачного вызова). Досрочно завершённый (``stopped``) блок даёт: важно, чтобы
модель знала про «нет данных для обработки», а не отвечала так, будто сводка есть.

Модуль чистый: только стандартная библиотека (эталон — ``scheduler_prompt.py``).
"""
from __future__ import annotations

from typing import Any, Mapping

PIPELINE_BLOCK_HEADER = "## Результат пайплайна"
PIPELINE_BLOCK_FOOTER = (
    "Используй эти данные как источник правды в ответе и не выдумывай поля, "
    "которых здесь нет."
)

#: Статусы прогона, при которых блок не собирается.
_SILENT_STATUSES = ("failed", "")


def render_pipeline_block(report: Mapping[str, Any] | None) -> str:
    """Системный блок с результатом прогона (``""`` — блока нет)."""
    if not report or not report.get("detected"):
        return ""
    status = str(report.get("status") or "")
    if status in _SILENT_STATUSES:
        return ""
    name = report.get("pipeline_name") or report.get("name") or ""
    lines = [PIPELINE_BLOCK_HEADER, f"Пайплайн: {name}"]
    if status != "stopped":
        steps = list(report.get("steps") or [])
        if steps:
            lines.append("Шаги:")
            lines.extend(step_line(step) for step in steps)
    message = report.get("message") or ""
    if message:
        lines.append(f"Итог: {message}")
    lines.append(PIPELINE_BLOCK_FOOTER)
    return "\n".join(lines)


def step_line(step: Mapping[str, Any]) -> str:
    """Строка одного шага: инструмент и главное число его выхода.

    Поля читаются устойчиво: у шага может не быть результата (``output_result``
    пуст у неудачного шага), и тогда строка обязана остаться читаемой — иначе отчёт
    о прогоне падал бы на том самом шаге, который и сломался.
    """
    tool = str(step.get("tool_name") or step.get("tool") or "")
    output = _structured(step)
    status = str(step.get("status") or "")
    if tool == "search":
        return (f"- search: найдено {output.get('count', 0)} элементов "
                f"(источник {output.get('source_kind', '—')}: "
                f"{output.get('source', '—')})")
    if tool == "summarize":
        points = output.get("key_points") or []
        return (f"- summarize: {len(points)} ключевых пунктов, стиль "
                f"{output.get('style_used', '—')}, движок {output.get('engine', '—')}")
    if tool == "save_to_file":
        return (f"- save_to_file: файл {output.get('filename', '—')} "
                f"({output.get('size_bytes', 0)} байт, {output.get('format', '—')})")
    return f"- {tool}: {status}"


def _structured(step: Mapping[str, Any]) -> Mapping[str, Any]:
    """Структурированный выход шага (пустой словарь, если результата нет)."""
    output = step.get("output_result")
    if not isinstance(output, Mapping):
        return {}
    structured = output.get("structured")
    return structured if isinstance(structured, Mapping) else {}
