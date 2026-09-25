"""Прогон декларативного пайплайна MCP-инструментов (день 19).

``Pipeline`` читает конфигурацию (``backend/domain/pipeline_spec.py``), выполняет
шаги по порядку и пишет журнал в SQLite (``backend/storage/pipeline_store.py``).
Это единственное место, где домен пайплайна встречается с реестром MCP: шаги
выполняются через ``MCPToolRunner`` — тем же путём, что и одиночный вызов
инструмента из чата, поэтому правила допуска (соединение, каталог, аргументы)
действуют и здесь, а неудача шага приходит исходом, а не исключением.

Порядок одного шага: **маппинг аргументов → условие перехода → вызов → журнал →
переход FSM**. Именно в этом порядке, потому что:

- маппинг разрешает ссылки ``$steps.<i>.<путь>``/``{имя}`` — до вызова инструмента,
  иначе незаполненная ссылка ушла бы на сервер пустой строкой;
- условие проверяется до вызова: «нет данных для обработки» — это не ошибка
  инструмента, а решение не звать его вовсе (прогон завершается досрочно);
- строка журнала пишется ВСЕГДА, включая шаги, которые упали на маппинге: иначе
  причина остановки не доехала бы до истории и отчёта.

``output_result`` шага — единая форма для всех инструментов:
``{"reason_code", "structured", "text", "is_error", "duration_ms"}``. Она
одинакова у успеха и неудачи, поэтому пути маппинга
(``$steps.<i>.structured.<поле>``) определены всегда, а не только у удачных шагов.

Прогон останавливается на первом не-``ok`` шаге: ошибка шага — это конец
пайплайна, а не «продолжим с мусором» (требование дня).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logging_utils import get_logger

from ..domain.mcp_tool_call import MCPToolCallState
from ..domain.pipeline_fsm import PipelineEvent, PipelineFSM, PipelineState
from ..domain.pipeline_mapping import PipelineMappingError, evaluate_guard, resolve_mapping
from ..domain.pipeline_spec import (
    MSG_COMPLETED,
    STEP_FAILED,
    STEP_OK,
    STEP_STOPPED,
    validate_pipeline,
)
from ..storage.pipeline_store import PipelineStore
from ..storage.scheduler_rows import jsonable
from .mcp_tool_runner import MCPToolRunner

logger = get_logger(__name__)

#: Текст ошибки шага, если исход пуст (инструмент не выполнялся).
FALLBACK_STEP_ERROR = "инструмент не выполнился"


class Pipeline:
    """Декларативный пайплайн MCP-инструментов: шаги, маппинг данных, журнал в SQLite."""

    def __init__(self, runner: Optional[MCPToolRunner] = None,
                 store: Optional[PipelineStore] = None) -> None:
        self._runner = runner
        self._store = store

    @property
    def runner(self) -> MCPToolRunner:
        """Вызыватель инструментов: переданный или реестр процесса."""
        if self._runner is None:
            self._runner = MCPToolRunner()
        return self._runner

    @property
    def store(self) -> PipelineStore:
        """Хранилище журнала: переданное или хранилище процесса."""
        if self._store is None:
            self._store = PipelineStore()
        return self._store

    def run_pipeline(self, pipeline_config: dict,
                     initial_args: Optional[dict] = None,
                     *, run_id: Optional[int] = None) -> dict[str, Any]:
        """Выполняет пайплайн и возвращает отчёт о прогоне.

        ``run_id`` передаёт фоновый запуск: строка ``pipeline_runs`` уже создана
        сервисом (чтобы интерфейс увидел запуск сразу), и прогон только дописывает её.
        """
        cfg = validate_pipeline(pipeline_config)
        initial = dict(initial_args or {})
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        if run_id is None:
            run_id = self.store.create_run(
                pipeline_name=cfg["name"],
                status=PipelineState.RUNNING.value,
                started_at=started_at,
            )["id"]

        fsm = PipelineFSM()
        fsm.handle(PipelineEvent.START)
        outputs: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        failed_at: Optional[int] = None
        stop_message = ""
        total = len(cfg["steps"])

        for index, step in enumerate(cfg["steps"]):
            context = {"initial": initial, "steps": outputs}
            tool = step["tool"]
            resolved = None
            try:
                resolved = resolve_mapping(step.get("args") or {}, context)
                guard = step.get("guard")
                if guard:
                    passed, message = evaluate_guard(guard, context)
                else:
                    passed, message = True, ""
            except PipelineMappingError as exc:
                steps.append(self._log_step(
                    run_id, index, tool, resolved, None, 0, STEP_FAILED, str(exc),
                ))
                fsm.handle(PipelineEvent.FAIL)
                failed_at = index
                logger.warning("Пайплайн %s: шаг %s не собран: %s", run_id, tool, exc)
                break
            if not passed:
                steps.append(self._log_step(
                    run_id, index, tool, resolved, None, 0, STEP_STOPPED, message,
                ))
                fsm.handle(PipelineEvent.STOP)
                stop_message = message
                logger.info("Пайплайн %s: шаг %s пропущен: %s", run_id, tool, message)
                break

            outcome = self.runner.call(tool, resolved)
            output = {
                "reason_code": outcome.reason_code,
                "structured": outcome.result.structured if outcome.result else None,
                "text": outcome.result.text if outcome.result else "",
                "is_error": bool(outcome.result.is_error) if outcome.result else True,
                "duration_ms": outcome.duration_ms,
            }
            ok = outcome.state is MCPToolCallState.DONE
            error = None if ok else (outcome.error or FALLBACK_STEP_ERROR)
            steps.append(self._log_step(
                run_id, index, tool, resolved, output, outcome.duration_ms,
                STEP_OK if ok else STEP_FAILED, error,
            ))
            if ok:
                outputs.append(output)
                fsm.handle(PipelineEvent.ADVANCE if index < total - 1
                           else PipelineEvent.FINISH)
            else:
                fsm.handle(PipelineEvent.FAIL)
                failed_at = index
                logger.warning("Пайплайн %s: шаг %s упал (%s): %s",
                               run_id, tool, outcome.reason_code, error)
                break

        total_ms = int((time.perf_counter() - started) * 1000)
        self.store.update_run(
            run_id,
            status=fsm.state.value,
            finished_at=datetime.now(timezone.utc),
            total_duration_ms=total_ms,
        )
        return {
            "run_id": run_id,
            "pipeline_name": cfg["name"],
            "status": fsm.state.value,
            "steps": steps,
            "count": len(steps),
            "failed_at_step": failed_at,
            "message": stop_message or (
                MSG_COMPLETED if fsm.state is PipelineState.COMPLETED else ""
            ),
            "error": next(
                (step["error_message"] for step in steps if step["status"] == STEP_FAILED),
                None,
            ),
            "total_duration_ms": total_ms,
        }

    def _log_step(self, run_id: int, index: int, tool: str,
                  args: Optional[dict], output: Optional[dict], duration_ms: int,
                  status: str, error_message: Optional[str]) -> dict[str, Any]:
        """Пишет строку журнала шага и возвращает её же для отчёта прогона."""
        return self.store.add_step(
            run_id=run_id,
            step_index=index,
            tool_name=tool,
            input_args=jsonable(args or {}),
            output_result=jsonable(output),
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
        )
