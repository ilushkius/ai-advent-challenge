"""Тесты хранилища запусков оркестрации (день 20).

Хранилище — единственное место, где прогон переживает рестарт, поэтому проверяются
и форма записей (запуск с планом и списком серверов, шаг с сервером и текстом
ошибки), и порядок чтения, и каскадное удаление, и СТАТИСТИКА по журналу: по ней
строятся «вызовы по серверам» и «топ инструментов» в интерфейсе и отчёте.
"""
from datetime import datetime, timezone

import pytest

from backend.storage.orchestration_store import (
    OrchestrationRunNotFoundError,
    OrchestrationStore,
)


def _store(session_factory) -> OrchestrationStore:
    return OrchestrationStore(session_factory=session_factory)


def _run(store: OrchestrationStore, query: str = "запрос") -> int:
    """Заводит запуск и возвращает его номер."""
    record = store.create_run(
        query=query,
        plan={"name": "план", "steps": [{"tool": "search_web", "args": {}}]},
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    return int(record["id"])


def _step(store: OrchestrationStore, run_id: int, index: int, *, server: str,
          tool: str, status: str = "ok", duration_ms: int = 10,
          error: str | None = None, output: dict | None = None) -> dict:
    """Пишет строку журнала шага."""
    return store.add_step(
        run_id=run_id, step_index=index, server_name=server, tool_name=tool,
        input_args={"idx": index}, output_result=output, duration_ms=duration_ms,
        status=status, error_message=error,
    )


def test_create_run_has_running_shape(session_factory):
    """Новый запуск: статус ``running``, пустые серверы, нет момента окончания."""
    store = _store(session_factory)
    run_id = _run(store)
    record = store.run(run_id)
    assert record["status"] == "running"
    assert record["servers_used"] == []
    assert record["finished_at"] is None
    assert record["total_duration_ms"] == 0
    assert record["plan"]["name"] == "план"
    assert record["query"] == "запрос"
    assert record["started_at"]


def test_update_run_sets_terminal_state(session_factory):
    """Обновление ставит терминальный статус, время, длительность и серверы."""
    store = _store(session_factory)
    run_id = _run(store)
    updated = store.update_run(
        run_id, status="completed", finished_at=datetime.now(timezone.utc),
        total_duration_ms=1234, servers_used=["search_server", "data_server"])
    assert updated["status"] == "completed"
    assert updated["total_duration_ms"] == 1234
    assert updated["servers_used"] == ["search_server", "data_server"]
    assert updated["finished_at"]
    # Без явного списка серверов прежний не стирается: обновление статуса не должно
    # терять состав флота, который уже записан.
    again = store.update_run(run_id, status="failed",
                             finished_at=datetime.now(timezone.utc),
                             total_duration_ms=10)
    assert again["servers_used"] == ["search_server", "data_server"]


def test_run_row_raises_for_unknown_id(session_factory):
    """Неизвестный номер запуска — исключение хранилища (роутер отдаёт 404)."""
    store = _store(session_factory)
    assert store.run(4321) is None
    with store.session() as session:
        with pytest.raises(OrchestrationRunNotFoundError):
            store.run_row(session, 4321)
    assert store.delete_run(4321) is False


def test_steps_are_read_in_plan_order(session_factory):
    """Шаги читаются по возрастанию номера, даже если записаны вперемешку."""
    store = _store(session_factory)
    run_id = _run(store)
    _step(store, run_id, 2, server="storage_server", tool="save_to_db")
    _step(store, run_id, 0, server="search_server", tool="search_web")
    _step(store, run_id, 1, server="data_server", tool="summarize")
    steps = store.steps(run_id)
    assert [step["step_index"] for step in steps] == [0, 1, 2]
    assert [step["server_name"] for step in steps] == [
        "search_server", "data_server", "storage_server"]
    assert steps[0]["tool_name"] == "search_web"
    assert steps[0]["input_args"] == {"idx": 0}
    assert steps[0]["status"] == "ok"
    assert steps[0]["duration_ms"] == 10


def test_step_keeps_error_and_empty_result(session_factory):
    """Строка журнала несёт текст ошибки и допускает пустой результат."""
    store = _store(session_factory)
    run_id = _run(store)
    step = _step(store, run_id, 0, server="", tool="teleport", status="failed",
                 duration_ms=0, error="инструмент не найден", output=None)
    assert step["error_message"] == "инструмент не найден"
    assert step["output_result"] is None
    assert step["server_name"] == ""
    assert step["status"] == "failed"


def test_list_runs_is_newest_first_and_filters_by_status(session_factory):
    """История идёт от свежих к старым и умеет фильтровать по статусу."""
    store = _store(session_factory)
    first = _run(store, "первый")
    second = _run(store, "второй")
    store.update_run(first, status="completed", finished_at=datetime.now(timezone.utc),
                     total_duration_ms=5)
    runs = store.list_runs()
    assert [run["id"] for run in runs] == [second, first]
    assert [run["id"] for run in store.list_runs(status="completed")] == [first]
    assert [run["id"] for run in store.list_runs(limit=1)] == [second]


def test_delete_run_removes_steps_cascade(session_factory):
    """Удаление запуска уносит его шаги: история шагов без запуска не имеет смысла."""
    store = _store(session_factory)
    run_id = _run(store)
    _step(store, run_id, 0, server="search_server", tool="search_web")
    assert store.steps(run_id) != []
    assert store.delete_run(run_id) is True
    assert store.run(run_id) is None
    assert store.steps(run_id) == []


def test_stats_counts_servers_and_tools(session_factory):
    """Статистика считает запуски, шаги, среднее время и вызовы по серверам/инструментам."""
    store = _store(session_factory)
    run_id = _run(store)
    _step(store, run_id, 0, server="search_server", tool="search_web", duration_ms=100)
    _step(store, run_id, 1, server="data_server", tool="summarize", duration_ms=200)
    _step(store, run_id, 2, server="data_server", tool="extract_keywords",
          duration_ms=300, status="failed", error="нужен текст")
    stats = store.stats()
    assert stats["runs"] == 1
    assert stats["steps"] == 3
    assert stats["avg_step_ms"] == 200.0
    by_server = {item["server"]: item for item in stats["servers"]}
    assert by_server["data_server"]["calls"] == 2
    assert by_server["data_server"]["avg_ms"] == 250.0
    assert by_server["search_server"]["calls"] == 1
    assert stats["servers"][0]["server"] == "data_server", "сортировка по числу вызовов"
    tools = {item["tool"]: item for item in stats["tools"]}
    assert tools["summarize"] == {"tool": "summarize", "server": "data_server", "calls": 1}
    assert tools["extract_keywords"]["calls"] == 1


def test_stats_of_empty_journal_is_zeroed(session_factory):
    """Пустой журнал даёт нули, а не ошибку: интерфейс рисует статистику всегда."""
    stats = _store(session_factory).stats()
    assert stats == {"runs": 0, "steps": 0, "avg_step_ms": 0.0, "servers": [], "tools": []}
