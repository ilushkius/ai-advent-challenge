"""Тесты прогона пайплайна (день 19): маппинг, условие, ошибки и журнал.

``Pipeline`` проверяется на фейковом MCP-реестре (``pipeline_fakes``), но настоящей
БД: важно, что делает ПРОГОН, а не сервер. Проверяются четыре исхода шага (успех,
отказ по аргументам, ошибка инструмента, остановка условием), форма записи
``output_result`` (по ней работает маппинг следующих шагов) и то, что причина
остановки доезжает до журнала — иначе история запусков ничего не объясняет.
"""

import copy
from datetime import datetime, timezone

import pytest

from backend.domain.pipeline_spec import (
    DEFAULT_PIPELINE,
    MSG_COMPLETED,
    MSG_NO_DATA,
    STEP_FAILED,
    STEP_OK,
    STEP_STOPPED,
    PipelineRejected,
)
from backend.services.mcp_tool_runner import MCPToolRunner
from backend.services.pipeline import Pipeline

from pipeline_fakes import make_pipeline_registry

#: Аргументы запуска встроенного пайплайна для тестов.
ARGS = {
    "query": "RAG",
    "source": "file:notes.md",
    "limit": 5,
    "style": "short",
    "max_length": 600,
    "filename": "run.md",
    "format": "md",
}


@pytest.fixture
def offline_pipeline(pipeline_store):
    """Пайплайн на реестре БЕЗ соединения: проверяет отказ правил допуска."""
    registry = make_pipeline_registry()
    try:
        yield Pipeline(runner=MCPToolRunner(registry), store=pipeline_store)
    finally:
        registry.close()


def test_full_pipeline_runs_three_steps_and_logs_them(pipeline, pipeline_store):
    """Встроенный пайплайн проходит три шага, и каждый попадает в журнал."""
    report = pipeline.run_pipeline(DEFAULT_PIPELINE, dict(ARGS))
    assert report["status"] == "completed"
    assert report["message"] == MSG_COMPLETED
    assert report["failed_at_step"] is None and report["error"] is None
    assert [step["tool_name"] for step in report["steps"]] == [
        "search", "summarize", "save_to_file"]
    assert all(step["status"] == STEP_OK for step in report["steps"])
    assert pipeline_store.steps(report["run_id"]) == report["steps"]
    run = pipeline_store.run(report["run_id"])
    assert run["status"] == "completed" and run["finished_at"] is not None


def test_output_result_has_one_shape_for_every_step(pipeline):
    """Форма результата шага одна и та же: по ней строятся пути маппинга."""
    report = pipeline.run_pipeline(DEFAULT_PIPELINE, dict(ARGS))
    for step in report["steps"]:
        output = step["output_result"]
        assert set(output) == {"reason_code", "structured", "text", "is_error",
                               "duration_ms"}
        assert output["is_error"] is False
        assert isinstance(output["structured"], dict)
    search, summarize, saved = (step["output_result"]["structured"]
                                for step in report["steps"])
    assert summarize["total_items"] == len(search["items"])
    assert saved["filename"] == "run.md"


def test_data_flows_through_mapping(pipeline, pipeline_registry):
    """Аргументы шага — это данные предыдущего шага, а не шаблон."""
    pipeline.run_pipeline(DEFAULT_PIPELINE, {**ARGS, "filename": "mapped.md"})
    search_call, summarize_call, save_call = pipeline_registry.client.call_calls
    assert search_call["arguments"]["query"] == "RAG"
    items = summarize_call["arguments"]["items"]
    assert isinstance(items, list) and items
    assert items == pipeline_registry.client.results["search"]["items"]
    assert save_call["arguments"]["content"].startswith("Найдено")
    assert save_call["arguments"]["filename"] == "mapped.md"


def test_search_limit_is_passed_to_the_tool(pipeline, pipeline_registry):
    """Аргумент запуска ``limit`` доезжает до инструмента как число."""
    pipeline.run_pipeline(DEFAULT_PIPELINE, {**ARGS, "limit": 3})
    assert pipeline_registry.client.call_calls[0]["arguments"]["limit"] == 3


def test_guard_stops_run_without_calling_next_step(pipeline, pipeline_registry,
                                                   pipeline_store):
    """Пустой результат поиска останавливает прогон: следующий инструмент не вызван."""
    pipeline_registry.client.results = {
        "search": {"query": "нет", "source": "file:notes.md", "source_kind": "file",
                   "count": 0, "items": []},
        "summarize": {"summary_text": "не должно вызываться", "key_points": [],
                      "total_items": 0, "style_used": "short", "engine": "aggregation"},
        "save_to_file": {"filename": "stopped.md", "filepath": "/tmp/stopped.md",
                         "size_bytes": 0, "format": "md", "saved_at": "2026-09-24"},
    }
    report = pipeline.run_pipeline(DEFAULT_PIPELINE,
                                   {**ARGS, "filename": "stopped.md"})

    assert report["status"] == "stopped"
    assert report["message"] == MSG_NO_DATA
    assert report["failed_at_step"] is None and report["error"] is None
    assert [step["tool_name"] for step in report["steps"]] == ["search", "summarize"]
    assert report["steps"][1]["status"] == STEP_STOPPED
    assert report["steps"][1]["error_message"] == MSG_NO_DATA
    assert [call["tool"] for call in pipeline_registry.client.call_calls] == ["search"]
    assert pipeline_store.run(report["run_id"])["status"] == "stopped"


def test_bad_arguments_are_rejected_before_the_server(pipeline, pipeline_store):
    """Отказ по ``input_schema`` — шаг failed с кодом bad_arguments, и он в журнале."""
    broken = copy.deepcopy(DEFAULT_PIPELINE)
    broken["steps"][1]["args"]["items"] = "$steps.0.structured.query"
    report = pipeline.run_pipeline(broken, dict(ARGS))

    assert report["status"] == "failed"
    assert report["failed_at_step"] == 1
    assert report["steps"][0]["status"] == STEP_OK
    failed = report["steps"][1]
    assert failed["status"] == STEP_FAILED
    assert failed["output_result"]["reason_code"] == "bad_arguments"
    assert failed["error_message"]
    assert len(pipeline_store.steps(report["run_id"])) == 2
    assert pipeline_store.run(report["run_id"])["status"] == "failed"


def test_tool_error_is_data_not_exception(pipeline, pipeline_registry, pipeline_store):
    """Ошибка инструмента останавливает прогон, но приходит данными с текстом."""
    pipeline_registry.client.errors = {"summarize": "Стиль не поддержан"}
    report = pipeline.run_pipeline(DEFAULT_PIPELINE, dict(ARGS))

    assert report["status"] == "failed"
    assert report["failed_at_step"] == 1
    assert "Стиль не поддержан" in report["error"]
    failed = report["steps"][1]
    assert failed["output_result"]["is_error"] is True
    assert failed["output_result"]["structured"] is None
    assert pipeline_store.run(report["run_id"])["status"] == "failed"


def test_without_connection_steps_fail_with_not_connected(offline_pipeline,
                                                          pipeline_store):
    """Без MCP-соединения первый шаг падает с причиной not_connected."""
    report = offline_pipeline.run_pipeline(DEFAULT_PIPELINE, dict(ARGS))
    assert report["status"] == "failed"
    assert report["failed_at_step"] == 0
    assert report["steps"][0]["output_result"]["reason_code"] == "not_connected"
    assert "соединени" in report["error"].lower()
    assert pipeline_store.run(report["run_id"])["status"] == "failed"


def test_mapping_failure_is_logged_as_failed_step(pipeline, pipeline_store):
    """Несобранный шаг тоже попадает в журнал — иначе причина остановки теряется."""
    broken = copy.deepcopy(DEFAULT_PIPELINE)
    broken["steps"][2]["args"]["content"] = "$steps.5.structured.summary_text"
    report = pipeline.run_pipeline(broken, dict(ARGS))

    assert report["status"] == "failed"
    assert report["failed_at_step"] == 2
    assert report["steps"][2]["status"] == STEP_FAILED
    assert report["steps"][2]["output_result"] is None
    assert "$steps.5" in report["steps"][2]["error_message"]
    assert len(pipeline_store.steps(report["run_id"])) == 3


def test_existing_run_id_is_reused(pipeline, pipeline_store):
    """Прогон с переданным ``run_id`` дописывает существующую строку, а не создаёт новую."""
    run_id = int(pipeline_store.create_run(
        pipeline_name="external", status="running",
        started_at=datetime.now(timezone.utc))["id"])
    report = pipeline.run_pipeline(DEFAULT_PIPELINE, dict(ARGS), run_id=run_id)
    assert report["run_id"] == run_id
    assert len(pipeline_store.list_runs()) == 1
    assert pipeline_store.run(run_id)["status"] == "completed"


def test_config_is_validated_before_anything_runs(offline_pipeline, pipeline_store):
    """Негодная конфигурация отклоняется до создания запуска."""
    with pytest.raises(PipelineRejected):
        offline_pipeline.run_pipeline({"steps": []}, dict(ARGS))
    assert pipeline_store.list_runs() == []
