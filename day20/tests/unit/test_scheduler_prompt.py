"""Отчёт и блок промпта по шагу планировщика (день 18).

Проверяется главное различие дня: отчёт и блок появляются ТОЛЬКО когда фоновая
задача действительно зарегистрирована (состояние ``done`` у инструмента
планировщика). Отказ, сбой, «вызов не потребовался» и инструмент чтения данных —
это отсутствие задачи, поэтому отчёт ``None``, а блок пустой.
"""
import pytest

from backend.domain.mcp_tool_call import MCPToolCallOutcome, MCPToolCallState
from backend.domain.mcp_tools import MCPToolResult
from backend.domain.scheduler_prompt import (
    SCHEDULER_BLOCK_HEADER,
    render_schedule_report,
    render_scheduler_block,
)

#: Плоский ответ инструмента планировщика (как его собирает MCP-сервер дня).
COLLECT_RESULT = {
    "task_id": 4,
    "name": "posts",
    "source_url": "https://example.test/posts",
    "interval_seconds": 10,
    "next_run_at": "2026-09-23T10:00:10+00:00",
    "records_saved": 1,
    "message": "Сбор «posts» запущен",
}

SUMMARY_RESULT = {
    "task_id": 5,
    "summary_id": 2,
    "name": "posts",
    "total_records": 3,
    "summary_text": "Сводка «posts» за период 10:00:00 — 10:00:20 (20 с).",
    "message": "Сводка «posts» сформирована",
}


def _outcome(tool, state=MCPToolCallState.DONE, structured=None, text="", is_error=False):
    """Исход вызова инструмента для проверки отчёта."""
    result = None
    if state is not MCPToolCallState.IDLE:
        result = MCPToolResult(tool=tool, arguments={}, structured=structured,
                               text=text, is_error=is_error)
    return MCPToolCallOutcome(state=state, detected=True, connected=True,
                              accepted=state is MCPToolCallState.DONE,
                              tool=tool, result=result)


def test_report_for_done_scheduler_tool():
    """Успешный шаг планировщика даёт отчёт с задачей, подтверждением и сводкой."""
    report = render_schedule_report(_outcome("collect_data", structured=COLLECT_RESULT))
    assert report is not None
    assert report["registered"] is True
    assert report["tool"] == "collect_data"
    assert report["task"]["id"] == 4
    assert report["task"]["next_run_at"] == "2026-09-23T10:00:10+00:00"
    assert report["message"] == "Сбор «posts» запущен"


def test_report_carries_summary_text():
    """Если инструмент посчитал сводку, её текст едет в отчёте."""
    report = render_schedule_report(_outcome("generate_summary", structured=SUMMARY_RESULT))
    assert report is not None and report["summary"] == SUMMARY_RESULT["summary_text"]


def test_report_prefers_ready_task_record():
    """Готовая запись задачи из ответа инструмента берётся как есть."""
    task = {"id": 9, "name": "Сбор: posts", "schedule_label": "каждые 10 с"}
    report = render_schedule_report(
        _outcome("collect_data", structured={"task": task, "message": "ок"})
    )
    assert report is not None and report["task"] == task


@pytest.mark.parametrize("state", [
    MCPToolCallState.IDLE,
    MCPToolCallState.REJECTED,
    MCPToolCallState.FAILED,
])
def test_no_report_when_task_not_registered(state):
    """Отказ, сбой и «вызов не потребовался» — фоновой задачи нет, отчёт ``None``."""
    assert render_schedule_report(_outcome("collect_data", state=state,
                                           structured=COLLECT_RESULT)) is None
    assert render_scheduler_block(_outcome("collect_data", state=state,
                                           structured=COLLECT_RESULT)) == ""


def test_no_report_for_reading_tool():
    """Инструмент чтения данных фоновой задачи не создаёт."""
    outcome = _outcome("get_user", structured={"id": 1, "name": "Leanne"})
    assert render_schedule_report(outcome) is None
    assert render_scheduler_block(outcome) == ""


def test_block_tells_the_model_the_task_exists():
    """Блок промпта сообщает модели, что задача уже стоит, и не даёт выдумать расписание."""
    outcome = _outcome("collect_data", structured=COLLECT_RESULT)
    block = render_scheduler_block(outcome)
    assert block.startswith(SCHEDULER_BLOCK_HEADER)
    assert "collect_data" in block
    assert "Задача №4" in block and "10:00:10" in block
    assert "уже зарегистрирована" in block


def test_block_includes_summary_line():
    """Текст сводки попадает и в блок промпта: модель отвечает по данным, а не «примерно»."""
    block = render_scheduler_block(_outcome("generate_summary", structured=SUMMARY_RESULT))
    assert "Сводка:" in block and "20 с" in block
