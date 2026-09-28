"""Отчёт и блок промпта по шагу планировщика (день 18).

Когда агент по реплике вызвал инструмент планировщика, ход получает две вещи:

* ``record["schedule"]`` — отчёт для API и интерфейса: зарегистрирован ли фоновый
  процесс, какой инструмент, что за задача, чем она ответила и каким текстом это
  подтверждается;
* системный блок «Данные планировщика» — тот же факт для модели: без него она
  отвечает «я не могу планировать задачи», хотя задача уже стоит.

Отчёт и блок собираются здесь, а не в агенте, потому что это текст контракта:
формулировку правят в одном месте, и её проверяют тесты (как
``render_mcp_tool_block`` дня 17).

Почему только при ``DONE``: отказ правил допуска (``REJECTED``), сбой связи
(``FAILED``) и «вызов не потребовался» (``IDLE``) — это отсутствие фоновой задачи,
а не задача. Тогда отчёт ``None``, блок пустой, а о самой неудаче пользователь
узнаёт из поля ``mcp`` ответа.

Модуль чистый: ни MCP SDK, ни HTTP, ни Streamlit.
"""

from __future__ import annotations

from typing import Any, Optional

from .mcp_tool_call import MCPToolCallOutcome, MCPToolCallState
from .schedule_spec import COLLECT_DATA, GENERATE_SUMMARY, SCHEDULE_REMINDER

#: Инструменты, которые планируют фоновую работу (остальные — запрос данных).
SCHEDULER_TOOL_NAMES = frozenset({SCHEDULE_REMINDER, COLLECT_DATA, GENERATE_SUMMARY})

#: Заголовок блока: по нему тест и интерфейс проверяют, что данные дошли до промпта.
SCHEDULER_BLOCK_HEADER = "## Данные планировщика"

#: Строка-инструкция: без неё модель обещает «напомнить сама», а не подтверждает задачу.
SCHEDULER_BLOCK_FOOTER = (
    "Фоновая задача уже зарегистрирована в планировщике: подтверди это "
    "пользователю и не выдумывай расписание, которого здесь нет."
)

#: Подтверждение по умолчанию, когда инструмент не прислал своего текста.
_TOOL_MESSAGES = {
    SCHEDULE_REMINDER: "Напоминание запланировано",
    COLLECT_DATA: "Периодический сбор данных запущен",
    GENERATE_SUMMARY: "Регулярная сводка настроена",
}


def render_schedule_report(outcome: Optional[MCPToolCallOutcome]) -> Optional[dict[str, Any]]:
    """Отчёт о шаге планировщика (``None`` — фоновый процесс не зарегистрирован).

    Читает плоский ответ MCP-инструмента (``task_id``, ``next_run_at``, ``message``,
    ``summary_text``) и, если инструмент прислал готовую запись задачи (``task``),
    берёт её как есть.
    """
    if outcome is None or outcome.result is None:
        return None
    if outcome.state is not MCPToolCallState.DONE:
        return None
    result = outcome.result
    tool = outcome.tool or result.tool
    if tool not in SCHEDULER_TOOL_NAMES:
        return None
    payload = result.structured if isinstance(result.structured, dict) else {}
    summary = payload.get("summary_text") or payload.get("summary")
    return {
        "registered": True,
        "tool": tool,
        "task": _task_of(payload),
        "summary": str(summary) if summary else None,
        "message": _message_of(tool, payload),
    }


def render_scheduler_block(outcome: Optional[MCPToolCallOutcome]) -> str:
    """Блок системного промпта о зарегистрированной задаче (``""`` — задачи нет)."""
    report = render_schedule_report(outcome)
    if report is None:
        return ""
    lines = [
        SCHEDULER_BLOCK_HEADER,
        f"Инструмент: {report['tool']}",
        f"Результат: {report['message']}",
    ]
    task = report.get("task") or {}
    if task.get("id"):
        lines.append(f"Задача №{task['id']}: {task.get('name') or '—'}")
    if task.get("schedule_label"):
        lines.append(f"Расписание: {task['schedule_label']}")
    if task.get("next_run_at"):
        lines.append(f"Следующий запуск: {task['next_run_at']}")
    if report.get("summary"):
        lines.append(f"Сводка: {report['summary']}")
    lines.extend(["", SCHEDULER_BLOCK_FOOTER])
    return "\n".join(lines)


def _task_of(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Запись задачи из ответа инструмента (``None`` — инструмент её не вернул).

    Отсутствующие поля приводятся к пустым строкам, а не остаются ``None``: отчёт
    уходит в ответ API, а схема задачи там строковая — иначе валидация ответа
    падала бы на инструменте, который не прислал имя или подпись расписания.
    """
    task = payload.get("task")
    if isinstance(task, dict):
        return dict(task)
    if payload.get("task_id") is None:
        return None
    return {
        "id": payload.get("task_id"),
        "name": str(payload.get("name") or ""),
        "schedule_label": str(payload.get("schedule_label") or ""),
        "next_run_at": payload.get("next_run_at"),
    }


def _message_of(tool: str, payload: dict[str, Any]) -> str:
    """Подтверждение инструмента или подпись по умолчанию для его вида."""
    message = str(payload.get("message") or "").strip()
    return message or _TOOL_MESSAGES.get(tool, "Фоновая задача зарегистрирована")
