"""Тесты хранилища пайплайна (день 19): запуски, их шаги и каскадное удаление.

Проверяется контракт ``PipelineStore``: запуск создаётся со статусом ``running``,
шаги пишутся по порядку и читаются отсортированными по номеру, фильтр истории
работает по статусу, а удаление запуска уносит его шаги (каскад) — иначе журнал
рос бы вечно, и «удалил запуск» не значило бы «удалил его след».
"""

from datetime import datetime, timezone

import pytest

from backend.storage.pipeline_store import PipelineRunNotFoundError, PipelineStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run(store: PipelineStore, name: str = "pipe", status: str = "running") -> int:
    """Заводит запуск и возвращает его номер."""
    return int(store.create_run(pipeline_name=name, status=status,
                                started_at=_now())["id"])


def test_create_run_returns_running_row(pipeline_store):
    """Новый запуск приходит словарём со статусом running и пустым концом."""
    run = pipeline_store.create_run(pipeline_name="search-summarize-save",
                                    status="running", started_at=_now())
    assert run["pipeline_name"] == "search-summarize-save"
    assert run["status"] == "running"
    assert run["finished_at"] is None and run["total_duration_ms"] == 0
    assert run["started_at"].endswith("+00:00")


def test_steps_are_read_in_step_index_order(pipeline_store):
    """Шаги читаются по возрастанию номера, даже если записаны в другом порядке."""
    run_id = _run(pipeline_store)
    pipeline_store.add_step(run_id=run_id, step_index=2, tool_name="save_to_file",
                            input_args={"content": "x"}, output_result=None,
                            duration_ms=3, status="ok")
    pipeline_store.add_step(run_id=run_id, step_index=0, tool_name="search",
                            input_args={"query": "RAG"},
                            output_result={"structured": {"count": 2}},
                            duration_ms=11, status="ok")
    steps = pipeline_store.steps(run_id)
    assert [step["step_index"] for step in steps] == [0, 2]
    assert steps[0]["tool_name"] == "search"
    assert steps[0]["output_result"] == {"structured": {"count": 2}}
    assert steps[0]["duration_ms"] == 11


def test_step_without_result_keeps_null_and_error_text(pipeline_store):
    """У шага без результата остаётся NULL, а причина ошибки видна текстом."""
    run_id = _run(pipeline_store)
    step = pipeline_store.add_step(
        run_id=run_id, step_index=1, tool_name="summarize", input_args={},
        output_result=None, duration_ms=0, status="failed",
        error_message="Аргумент «items» должен быть array",
    )
    assert step["output_result"] is None
    assert step["status"] == "failed"
    assert "items" in step["error_message"]


def test_update_run_sets_terminal_state_and_duration(pipeline_store):
    """Терминальный статус дописывает конец и общую длительность."""
    run_id = _run(pipeline_store)
    updated = pipeline_store.update_run(run_id, status="completed",
                                        finished_at=_now(), total_duration_ms=42)
    assert updated["status"] == "completed"
    assert updated["total_duration_ms"] == 42
    assert updated["finished_at"] is not None
    assert pipeline_store.run(run_id)["status"] == "completed"


def test_list_runs_returns_fresh_first_and_filters_by_status(pipeline_store):
    """История идёт от свежих к старым, фильтр статуса отбирает только нужные."""
    first = _run(pipeline_store, status="completed")
    second = _run(pipeline_store, status="failed")
    third = _run(pipeline_store, status="completed")
    assert [run["id"] for run in pipeline_store.list_runs()] == [third, second, first]
    completed = pipeline_store.list_runs(status="completed")
    assert [run["id"] for run in completed] == [third, first]
    assert pipeline_store.list_runs(limit=1)[0]["id"] == third


def test_delete_run_removes_its_steps(pipeline_store):
    """Удаление запуска уносит его шаги: строки без запуска не остаются."""
    run_id = _run(pipeline_store)
    pipeline_store.add_step(run_id=run_id, step_index=0, tool_name="search",
                            input_args={}, output_result={"structured": {"count": 0}},
                            duration_ms=1, status="ok")
    assert pipeline_store.delete_run(run_id) is True
    assert pipeline_store.steps(run_id) == []
    assert pipeline_store.run(run_id) is None
    assert pipeline_store.delete_run(run_id) is False


def test_run_row_on_missing_run_raises(pipeline_store):
    """Строка отсутствующего запуска — явная ошибка с номером, а не None."""
    with pipeline_store.session() as session:
        with pytest.raises(PipelineRunNotFoundError) as exc:
            pipeline_store.run_row(session, 999)
    assert "999" in str(exc.value)
