"""Системный блок пайплайна в промпте: строки шагов и итог прогона (день 19).

Проверяется, что модели уходит короткая и правдивая выжимка: числа шагов
(сколько элементов нашёл ``search``, сколько пунктов у ``summarize``, размер файла
у ``save_to_file``), статус досрочного завершения с сообщением «нет данных» и —
главное — что неудачный прогон и нераспознанная реплика не дают блока вовсе.
Отдельно проверяется устойчивость строки шага: у упавшего шага результата нет, и
блок обязан остаться читаемым, а не уронить отчёт о прогоне.
"""
import pytest

from backend.domain.pipeline_prompt import (
    PIPELINE_BLOCK_FOOTER,
    PIPELINE_BLOCK_HEADER,
    render_pipeline_block,
    step_line,
)


def _step(tool, status, structured=None, output=None):
    """Строка журнала шага: инструмент, статус и (необязательный) структурированный выход."""
    if output is None and structured is not None:
        output = {"structured": structured, "text": "", "reason_code": None}
    return {"step_index": 0, "tool_name": tool, "input_args": {},
            "output_result": output, "duration_ms": 5, "status": status,
            "error_message": None}


SEARCH_STEP = _step("search", "ok", {"count": 3, "source_kind": "file",
                                    "source": "file:mcp_server/data/notes.md"})
SUMMARIZE_STEP = _step("summarize", "ok", {"key_points": ["RAG", "FSM"],
                                           "style_used": "short", "engine": "aggregation"})
SAVE_STEP = _step("save_to_file", "ok", {"filename": "rag.md", "size_bytes": 128,
                                         "format": "md"})


@pytest.mark.parametrize("report", [
    None,
    {},
    {"detected": False, "status": "completed", "steps": [SEARCH_STEP]},
    {"detected": True, "status": "failed", "steps": [SEARCH_STEP],
     "message": "пайплайн остановлен: шаг завершился ошибкой"},
    {"detected": True, "status": "", "steps": [SEARCH_STEP]},
    {"detected": True, "steps": [SEARCH_STEP]},
])
def test_silent_reports_give_empty_block(report):
    """Нераспознанная реплика и неудачный прогон не дают модели ничего."""
    assert render_pipeline_block(report) == ""


@pytest.mark.parametrize("tool,structured,expected", [
    ("search", {"count": 3, "source_kind": "file",
                "source": "file:mcp_server/data/notes.md"},
     "- search: найдено 3 элементов (источник file: file:mcp_server/data/notes.md)"),
    ("summarize", {"key_points": ["RAG", "FSM"], "style_used": "short",
                   "engine": "aggregation"},
     "- summarize: 2 ключевых пунктов, стиль short, движок aggregation"),
    ("save_to_file", {"filename": "rag.md", "size_bytes": 128, "format": "md"},
     "- save_to_file: файл rag.md (128 байт, md)"),
])
def test_step_line_prints_tool_numbers(tool, structured, expected):
    """Строка шага несёт объёмы выхода: элементы, ключевые пункты, байты файла."""
    assert step_line(_step(tool, "ok", structured)) == expected


def test_completed_block_lists_all_steps_with_footer():
    """Полный прогон: заголовок, имя пайплайна, строка на каждый шаг, итог и футер."""
    report = {"detected": True, "status": "completed",
              "pipeline_name": "search-summarize-save", "message": "пайплайн выполнен",
              "steps": [SEARCH_STEP, SUMMARIZE_STEP, SAVE_STEP]}
    block = render_pipeline_block(report)
    lines = block.splitlines()
    assert lines[0] == PIPELINE_BLOCK_HEADER
    assert lines[1] == "Пайплайн: search-summarize-save"
    assert "Шаги:" in lines
    assert [line for line in lines if line.startswith("- ")] == [
        step_line(SEARCH_STEP), step_line(SUMMARIZE_STEP), step_line(SAVE_STEP),
    ]
    assert "Итог: пайплайн выполнен" in lines
    assert lines[-1] == PIPELINE_BLOCK_FOOTER


def test_stopped_block_gives_message_without_steps():
    """Досрочное завершение: сообщение «нет данных» есть, строк шагов нет."""
    report = {"detected": True, "status": "stopped",
              "pipeline_name": "search-summarize-save", "message": "нет данных для обработки",
              "steps": [SEARCH_STEP]}
    block = render_pipeline_block(report)
    assert block.startswith(PIPELINE_BLOCK_HEADER)
    assert "Пайплайн: search-summarize-save" in block
    assert "Итог: нет данных для обработки" in block
    assert block.endswith(PIPELINE_BLOCK_FOOTER)
    assert "Шаги:" not in block
    assert "- search" not in block


def test_block_without_message_has_no_itog_line():
    """Прогон без сообщения не даёт пустой строки «Итог:»."""
    report = {"detected": True, "status": "completed", "pipeline_name": "p1",
              "steps": [SEARCH_STEP]}
    block = render_pipeline_block(report)
    assert "Итог" not in block
    assert "Шаги:" in block


def test_pipeline_name_falls_back_to_name_key():
    """Имя пайплайна читается и из поля name — блок не остаётся без названия."""
    report = {"detected": True, "status": "completed", "name": "custom-pipeline",
              "steps": [SEARCH_STEP]}
    assert "Пайплайн: custom-pipeline" in render_pipeline_block(report)


def test_unknown_tool_line_is_tool_and_status():
    """Неизвестный инструмент даёт строку «инструмент: статус» без выдуманных чисел."""
    assert step_line(_step("custom_tool", "failed", None)) == "- custom_tool: failed"


def test_step_line_reads_tool_key_fallback():
    """Инструмент читается и из ключа tool, если имени нет."""
    assert step_line({"tool": "save_to_file", "status": "ok",
                      "output_result": {"structured": {"filename": "a.md"}}}) == (
        "- save_to_file: файл a.md (0 байт, —)")


@pytest.mark.parametrize("tool,output,expected", [
    ("search", None, "- search: найдено 0 элементов (источник —: —)"),
    ("summarize", None, "- summarize: 0 ключевых пунктов, стиль —, движок —"),
    ("save_to_file", None, "- save_to_file: файл — (0 байт, —)"),
    ("search", {"structured": "текст"}, "- search: найдено 0 элементов (источник —: —)"),
    ("summarize", {"structured": {"key_points": None}},
     "- summarize: 0 ключевых пунктов, стиль —, движок —"),
    ("save_to_file", {}, "- save_to_file: файл — (0 байт, —)"),
])
def test_step_line_survives_missing_or_foreign_output(tool, output, expected):
    """Упавший шаг без результата всё равно даёт читаемую строку, а не исключение."""
    step = {"tool_name": tool, "status": "failed", "output_result": output}
    assert step_line(step) == expected
