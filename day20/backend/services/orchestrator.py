"""Прогон оркестрации: план шагов, маршрутизация по серверам и журнал (день 20).

``Orchestrator`` — единственное место, где домен оркестрации встречается с флотом
MCP-серверов:

1. **план** (``build_plan``) — данные: либо присланный клиентом (``source=given``),
   либо предложенный моделью (``source=llm``), либо собранный эвристикой из
   встроенного сценария, отфильтрованного по доступным инструментам
   (``source=heuristic``). Без плана прогон не начинается, но прогон без ключа
   DeepSeek — обычный случай, а не ошибка;
2. **прогон** (``run``/``execute``) — по шагам: маппинг аргументов → условие →
   маршрутизация (``registry.find_tool_by_name``) → подключение сервера при нужде
   (``registry.ensure_connected``) → вызов через ``MCPToolRunner`` → строка журнала
   → событие FSM;
3. **журнал** — ``orchestration_runs`` (запуск) и ``orchestration_steps`` (шаг с
   сервером, инструментом, входом, выходом и временем). Строка пишется ВСЕГДА,
   включая шаги, упавшие на маппинге: иначе причина остановки не доехала бы до
   истории, интерфейса и отчёта.

Почему порядок именно такой. Маппинг идёт до вызова, потому что незаполненная
ссылка ушла бы серверу пустой строкой; условие проверяется до вызова, потому что
«нет данных» — это решение не звать инструмент, а не его ошибка; маршрутизация
идёт после маппинга, потому что имя инструмента — часть шага, а не аргументов.

``output_result`` шага — единая форма для всех инструментов:
``{"reason_code", "structured", "text", "is_error", "duration_ms"}``. Она
одинакова у успеха и неудачи, поэтому пути маппинга
(``$steps.<i>.structured.<поле>``) определены всегда. Исключение — шаг, упавший на
маппинге: у него ``output_result=None`` (данных нет вовсе), и это тоже данные.

``servers_used`` — серверы, до которых дошёл прогон, в порядке первого появления:
по ним интерфейс показывает «шагов 5, серверов 3», а строка базы — состав флота,
который реально участвовал.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logging_utils import get_logger

from ..domain.mcp_tool_call import (
    REASON_NOT_CONNECTED,
    REASON_UNKNOWN_TOOL,
    MCPToolCallState,
)
from ..domain.orchestration_fsm import (
    OrchestrationEvent,
    OrchestrationFSM,
    OrchestrationState,
)
from ..domain.orchestration_plan import heuristic_plan
from ..domain.orchestration_spec import (
    MSG_COMPLETED,
    launch_arguments,
    MSG_FAILED,
    MSG_RUNNING,
    STEP_FAILED,
    STEP_OK,
    STEP_STOPPED,
    validate_plan,
)
from ..domain.pipeline_mapping import (
    PipelineMappingError,
    evaluate_guard,
    resolve_mapping,
)
from ..storage.orchestration_store import OrchestrationStore
from ..storage.scheduler_rows import jsonable
from .mcp_client import MCPError
from .mcp_registry import MCPRegistry, get_mcp_registry
from .mcp_tool_runner import MCPToolRunner
from .orchestration_planner import OrchestrationPlanner

logger = get_logger(__name__)

#: Текст ошибки шага, если исход пуст (инструмент не выполнялся).
FALLBACK_STEP_ERROR = "шаг не выполнился"

#: Источники плана: попадают в отчёт, интерфейс и системный блок.
SOURCE_GIVEN = "given"
SOURCE_LLM = "llm"
SOURCE_HEURISTIC = "heuristic"


class Orchestrator:
    """План шагов по флоту серверов: построение, прогон и журнал в SQLite."""

    def __init__(self, registry: Optional[MCPRegistry] = None,
                 store: Optional[OrchestrationStore] = None,
                 planner: Optional[OrchestrationPlanner] = None) -> None:
        self._registry = registry
        self._store = store
        self._planner = planner

    @property
    def registry(self) -> MCPRegistry:
        """Реестр флота: переданный или реестр процесса."""
        return self._registry or get_mcp_registry()

    @property
    def store(self) -> OrchestrationStore:
        """Хранилище журнала: переданное или хранилище процесса."""
        if self._store is None:
            self._store = OrchestrationStore()
        return self._store

    @property
    def planner(self) -> OrchestrationPlanner:
        """Планировщик плана: переданный или новый (сам решит, есть ли ключ)."""
        if self._planner is None:
            self._planner = OrchestrationPlanner()
        return self._planner

    # ---------- план ----------
    def build_plan(self, query: str, *, plan: Optional[dict] = None) -> dict:
        """План прогона: присланный, предложенный моделью или собранный эвристикой.

        Источник плана пишется в сам план (``source``): по нему видно в журнале и в
        интерфейсе, почему шаги именно такие — модель их придумала, пришёл клиент
        или сработал встроенный сценарий (например, когда ключа DeepSeek нет).
        """
        if plan is not None:
            built = validate_plan(plan)
            built["source"] = SOURCE_GIVEN
            return built
        tools = self.registry.list_all_tools()
        proposed = self.planner.plan(query, tools)
        if proposed is not None:
            built = validate_plan(proposed)
            built["source"] = SOURCE_LLM
            return built
        built = heuristic_plan(query, [item.name for item in tools])
        built["source"] = SOURCE_HEURISTIC
        return built

    # ---------- прогон ----------
    def run(self, query: str, *, plan: Optional[dict] = None,
            initial_args: Optional[dict] = None,
            run_id: Optional[int] = None) -> dict:
        """Строит план (если он не передан готовым) и выполняет прогон."""
        cfg = self.build_plan(query, plan=plan)
        return self.execute(query, cfg, initial_args=initial_args, run_id=run_id)

    def execute(self, query: str, plan: dict, *,
                initial_args: Optional[dict] = None,
                run_id: Optional[int] = None) -> dict:
        """Выполняет готовый план шаг за шагом и возвращает отчёт о прогоне.

        ``run_id`` передаёт фоновый запуск: строка ``orchestration_runs`` уже
        создана сервисом (чтобы интерфейс увидел запуск сразу), и прогон только
        дописывает её.
        """
        cfg = validate_plan(plan)
        source = str((plan or {}).get("source") or SOURCE_GIVEN)
        # Источник плана сохраняется в самой конфигурации: она уходит и в журнал
        # (колонка plan), и в отчёт — по ней видно, откуда взялись шаги.
        cfg["source"] = source
        # Аргументы запуска с умолчаниями дня: заглушки ``{limit}``/``{filename}``
        # есть во встроенном сценарии, поэтому прогон с одной репликой не должен
        # падать на маппинге. Переданные значения сильнее умолчаний.
        initial = launch_arguments(query, initial_args)
        started = time.perf_counter()
        if run_id is None:
            run_id = int(self.store.create_run(
                query=query,
                plan=cfg,
                status=OrchestrationState.RUNNING.value,
                started_at=datetime.now(timezone.utc),
                servers_used=[],
            )["id"])

        fsm = OrchestrationFSM()
        fsm.handle(OrchestrationEvent.START)
        outputs: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        servers: list[str] = []
        failed_at: Optional[int] = None
        error: Optional[str] = None
        stop_message = ""
        total = len(cfg["steps"])

        for index, step in enumerate(cfg["steps"]):
            context = {"initial": initial, "steps": outputs}
            tool = step["tool"]
            resolved: Optional[dict] = None
            try:
                resolved = resolve_mapping(step.get("args") or {}, context)
                guard = step.get("guard")
                passed, message = (evaluate_guard(guard, context) if guard
                                   else (True, ""))
            except PipelineMappingError as exc:
                steps.append(self._log_step(
                    run_id, index, "", tool, resolved, None, 0, STEP_FAILED, str(exc),
                ))
                fsm.handle(OrchestrationEvent.FAIL)
                failed_at, error = index, str(exc)
                logger.warning("Оркестрация %s: шаг %s не собран: %s", run_id, tool, exc)
                break
            if not passed:
                steps.append(self._log_step(
                    run_id, index, "", tool, resolved, None, 0, STEP_STOPPED, message,
                ))
                fsm.handle(OrchestrationEvent.STOP)
                stop_message = message
                logger.info("Оркестрация %s: шаг %s пропущен: %s", run_id, tool, message)
                break

            server = self.registry.find_tool_by_name(tool)
            if server is None:
                known = ", ".join(item.name for item in self.registry.list_all_tools())
                reason = (f"Инструмент «{tool}» не публикует ни один сервер флота. "
                          f"Известны: {known or 'нет'}")
                # Упавший сервер не отдаёт каталог, поэтому его инструменты невидимы —
                # без этой подсказки «неизвестный инструмент» выглядел бы как ошибка
                # плана, хотя причина в неподнявшемся сервере.
                down = self._down_servers_hint()
                if down:
                    reason = f"{reason}. {down}"
                output = _failed_output(REASON_UNKNOWN_TOOL, reason)
                steps.append(self._log_step(
                    run_id, index, "", tool, resolved, output, 0, STEP_FAILED, reason,
                ))
                fsm.handle(OrchestrationEvent.FAIL)
                failed_at, error = index, reason
                logger.warning("Оркестрация %s: %s", run_id, reason)
                break
            if server not in servers:
                servers.append(server)

            try:
                self.registry.ensure_connected(server)
            except MCPError as exc:
                reason = (f"Сервер «{server}» не подключён и не поднялся: {exc}")
                output = _failed_output(REASON_NOT_CONNECTED, reason)
                steps.append(self._log_step(
                    run_id, index, server, tool, resolved, output, 0, STEP_FAILED, reason,
                ))
                fsm.handle(OrchestrationEvent.FAIL)
                failed_at, error = index, reason
                logger.warning("Оркестрация %s: %s", run_id, reason)
                break

            runner = MCPToolRunner(self.registry, server_name=server)
            outcome = runner.call(tool, resolved)
            output = {
                "reason_code": outcome.reason_code,
                "structured": outcome.result.structured if outcome.result else None,
                "text": outcome.result.text if outcome.result else "",
                "is_error": bool(outcome.result.is_error) if outcome.result else True,
                "duration_ms": outcome.duration_ms,
            }
            ok = outcome.state is MCPToolCallState.DONE
            step_error = None if ok else (outcome.error or FALLBACK_STEP_ERROR)
            steps.append(self._log_step(
                run_id, index, server, tool, resolved, output, outcome.duration_ms,
                STEP_OK if ok else STEP_FAILED, step_error,
            ))
            if ok:
                outputs.append(output)
                fsm.handle(OrchestrationEvent.ADVANCE if index < total - 1
                           else OrchestrationEvent.FINISH)
            else:
                fsm.handle(OrchestrationEvent.FAIL)
                failed_at, error = index, step_error
                logger.warning("Оркестрация %s: шаг %s (%s) упал: %s",
                               run_id, tool, server, step_error)
                break

        total_ms = int((time.perf_counter() - started) * 1000)
        self.store.update_run(
            run_id,
            status=fsm.state.value,
            finished_at=datetime.now(timezone.utc),
            total_duration_ms=total_ms,
            servers_used=servers,
        )
        logger.info("Оркестрация %s: %s (%d шагов, серверов: %d, %d мс)",
                    run_id, fsm.state.value, len(steps), len(servers), total_ms)
        return {
            "run_id": run_id,
            "query": query,
            "status": fsm.state.value,
            "plan": cfg,
            "plan_source": source,
            "steps": steps,
            "count": len(steps),
            "servers_used": servers,
            "failed_at_step": failed_at,
            "message": stop_message or _status_message(fsm.state),
            "error": error,
            "total_duration_ms": total_ms,
        }

    def _down_servers_hint(self) -> str:
        """Подсказка «какие серверы флота не поднялись» (пусто — все на месте).

        Нужна именно в отказе маршрутизации: инструменты упавшего сервера в каталоге
        отсутствуют, и без этой строки причина выглядела бы как ошибка плана.
        """
        down = [
            f"{record['name']} ({record['error'] or record['state']})"
            for record in self.registry.servers()
            if not record["connected"]
        ]
        if not down:
            return ""
        return "Не подключены серверы: " + "; ".join(down)

    def _log_step(self, run_id: int, index: int, server: str, tool: str,
                  args: Optional[dict], output: Optional[dict], duration_ms: int,
                  status: str, error_message: Optional[str]) -> dict[str, Any]:
        """Пишет строку журнала шага и возвращает её же для отчёта прогона."""
        return self.store.add_step(
            run_id=run_id,
            step_index=index,
            server_name=server,
            tool_name=tool,
            input_args=jsonable(args or {}),
            output_result=jsonable(output),
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
        )


def _failed_output(reason_code: str, text: str) -> dict[str, Any]:
    """Форма выхода шага, который до вызова не дошёл (нет инструмента или сервера)."""
    return {
        "reason_code": reason_code,
        "structured": None,
        "text": text,
        "is_error": True,
        "duration_ms": 0,
    }


def _status_message(state: OrchestrationState) -> str:
    """Итоговое сообщение по статусу прогона (без уточнения от шага ``stopped``)."""
    return {
        OrchestrationState.RUNNING: MSG_RUNNING,
        OrchestrationState.COMPLETED: MSG_COMPLETED,
        OrchestrationState.FAILED: MSG_FAILED,
    }.get(state, "")
