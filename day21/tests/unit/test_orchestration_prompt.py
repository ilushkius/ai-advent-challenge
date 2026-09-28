"""Тесты системного блока результата оркестрации (день 20).

Блок — это то, ради чего результат прогона вообще уходит модели: «данные собраны,
вот с каких серверов, не выдумывай полей». Поэтому проверяются четыре правила дня
17/19, перенесённые на флот: без распознавания блока нет, у НЕУДАЧНОГО прогона блока
нет (данные ошибки в промпт не попадают), у досрочно завершённого — есть (модель
обязана знать про невыполненное условие), а строки шагов читаемы даже тогда, когда у
шага нет результата.
"""
from backend.domain.orchestration_prompt import (
    ORCHESTRATION_BLOCK_FOOTER,
    ORCHESTRATION_BLOCK_HEADER,
    render_orchestration_block,
    step_line,
    structured_of,
)


def _report(**overrides) -> dict:
    """Отчёт прогона в форме, которую отдаёт сервис оркестрации."""
    base = {
        "detected": True,
        "run_id": 1,
        "status": "completed",
        "query": "найди данные про RAG и сохрани в базу",
        "message": "оркестрация выполнена",
        "plan_source": "heuristic",
        "servers_used": ["search_server", "data_server", "storage_server"],
        "steps": [
            {"step_index": 0, "server_name": "search_server", "tool_name": "search_web",
             "status": "ok", "duration_ms": 120,
             "output_result": {"structured": {"count": 5}}},
            {"step_index": 1, "server_name": "data_server", "tool_name": "summarize",
             "status": "ok", "duration_ms": 300,
             "output_result": {"structured": {"summary_text": "Сводка"}}},
        ],
    }
    base.update(overrides)
    return base


#: Отчёты, для которых блока быть не должно.
SILENT = (
    None,
    {},
    {"detected": False, "status": "completed"},
    {"detected": True, "status": "failed"},
    {"detected": True, "status": ""},
)


def test_silent_cases_render_nothing():
    """Нераспознанная реплика и неудачный прогон блока не дают."""
    for report in SILENT:
        assert render_orchestration_block(report) == ""


def test_completed_report_block_has_all_parts():
    """Успешный прогон даёт заголовок, запрос, серверы, строки шагов, итог и футер."""
    block = render_orchestration_block(_report())
    lines = block.splitlines()
    assert lines[0] == ORCHESTRATION_BLOCK_HEADER
    assert lines[-1] == ORCHESTRATION_BLOCK_FOOTER
    assert "Запрос: найди данные про RAG и сохрани в базу" in block
    assert "Серверы: search_server, data_server, storage_server" in block
    assert "- search_web (search_server): ok, 120 мс" in block
    assert "- summarize (data_server): ok, 300 мс" in block
    assert "Итог: оркестрация выполнена" in block
    assert "## Результат оркестрации" in block


def test_stopped_report_still_gives_a_block():
    """Досрочно завершённый прогон сообщает условие: модель не должна «додумать» данные."""
    report = _report(status="stopped", message="нет данных для обработки",
                     steps=[{"step_index": 0, "server_name": "search_server",
                             "tool_name": "search_web", "status": "stopped",
                             "duration_ms": 0, "error_message": "нет данных для обработки"}])
    block = render_orchestration_block(report)
    assert "Итог: нет данных для обработки" in block
    assert "stopped" in block


def test_report_without_servers_and_query_is_still_readable():
    """Пустые серверы и запрос не ломают блок: строки остаются, серверы — прочерк."""
    block = render_orchestration_block(_report(query="", servers_used=[], steps=[]))
    assert "Серверы: —" in block
    assert "Запрос:" not in block
    assert ORCHESTRATION_BLOCK_FOOTER in block


def test_step_line_survives_missing_result_and_error():
    """Строка шага читается и без результата, и с текстом ошибки."""
    minimal = {"tool_name": "fetch_url", "server_name": "search_server", "status": "ok"}
    assert step_line(minimal) == "- fetch_url (search_server): ok, 0 мс"
    failed = {"tool": "teleport", "status": "failed", "error_message": "нет инструмента"}
    assert step_line(failed) == "- teleport (—): failed, 0 мс — нет инструмента"


def test_structured_of_reads_only_structured_part():
    """``structured_of`` отдаёт структуру ответа и пустой словарь без неё."""
    assert structured_of({"output_result": {"structured": {"count": 3}}}) == {"count": 3}
    assert structured_of({"output_result": {"text": "текст"}}) == {}
    assert structured_of({"output_result": None}) == {}
    assert structured_of({}) == {}
