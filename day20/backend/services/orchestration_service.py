"""Служба оркестрации (день 20): запуск, чтение истории, статистика, удаление.

Разделение с ``Orchestrator`` простое: оркестратор знает, КАК построить план и
выполнить шаги, а ``OrchestrationService`` — когда запускать (синхронно или фоном),
что отдавать API и как читать журнал. Роутер ``/orchestration``, агент и
Streamlit работают только с ней, поэтому порядок «построить план → создать запуск →
выполнить → поставить терминальный статус» описан в одном месте.

Фоновый запуск. Прогон идёт в отдельном потоке (``threading.Thread``, daemon):
запрос ``POST /orchestration/demo`` обязан вернуться сразу, а интерфейс —
опрашивать статус из БД и рисовать прогресс. Строка запуска создаётся ДО старта
потока, поэтому состояние ``running`` видно с первого же опроса (гонки «запуск ещё
не записан» нет).

Исключение в потоке не убивает процесс бэкенда: ``_run`` ловит всё, пишет в лог и
ставит запуску терминальный статус ``failed``. Прогон без терминального статуса
означал бы вечный «выполняется» в интерфейсе — это худший исход, чем ошибка.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from shared.logging_utils import get_logger

from ..core import config
from ..domain.orchestration_fsm import OrchestrationState
from ..domain.orchestration_spec import (
    DEMO_PLAN,
    DEMO_QUERY,
    MSG_COMPLETED,
    MSG_FAILED,
    MSG_RUNNING,
    MSG_STOPPED,
    REASON_BAD_QUERY,
    REASON_NOT_FOUND,
    STEP_FAILED,
    STEP_STOPPED,
    OrchestrationRejected,
    demo_arguments,
)
from ..storage.orchestration_store import OrchestrationStore
from .orchestrator import Orchestrator

logger = get_logger(__name__)

#: Единственная служба процесса (ставится лениво при первом обращении).
_service: Optional["OrchestrationService"] = None


class OrchestrationService:
    """Запуски оркестрации: старт (в фоне или синхронно), история, статистика."""

    def __init__(self, orchestrator: Optional[Orchestrator] = None,
                 store: Optional[OrchestrationStore] = None) -> None:
        self._orchestrator = orchestrator
        self._store = store

    @property
    def orchestrator(self) -> Orchestrator:
        """Оркестратор: переданный или собранный на хранилище процесса."""
        if self._orchestrator is None:
            self._orchestrator = Orchestrator(store=self.store)
        return self._orchestrator

    @property
    def store(self) -> OrchestrationStore:
        """Хранилище журнала: переданное или хранилище процесса."""
        if self._store is None:
            self._store = OrchestrationStore()
        return self._store

    # ---------- запуски ----------
    def start_run(self, query: str, *, plan: Optional[dict] = None,
                  initial_args: Optional[dict] = None,
                  background: bool = True) -> dict:
        """Запускает оркестрацию: ``background=True`` — в потоке, ``False`` — сразу.

        План строится ДО создания строки запуска: она хранит план целиком, и
        ``GET /orchestration/runs/{id}`` показывает шаги даже пока прогон идёт.
        Негодный план (или пустой флот) — ``OrchestrationRejected``, роутер отдаёт
        400 и ничего не запускает.
        """
        args = dict(initial_args or {})
        cfg = self.orchestrator.build_plan(query, plan=plan)
        if not background:
            report = self.orchestrator.execute(query, cfg, initial_args=args)
            return {**report, "background": False}
        run = self.store.create_run(
            query=query,
            plan=cfg,
            status=OrchestrationState.RUNNING.value,
            started_at=datetime.now(timezone.utc),
            servers_used=[],
        )
        run_id = int(run["id"])
        thread = threading.Thread(
            target=self._run,
            args=(run_id, query, cfg, args),
            daemon=True,
            name=f"orchestration-{run_id}",
        )
        thread.start()
        logger.info("Оркестрация %s запущена в фоне (шагов: %d)", run_id, len(cfg["steps"]))
        return {
            "run_id": run_id,
            "query": query,
            "status": OrchestrationState.RUNNING.value,
            "plan": cfg,
            "plan_source": str(cfg.get("source") or ""),
            "steps": [],
            "count": 0,
            "servers_used": [],
            "failed_at_step": None,
            "message": MSG_RUNNING,
            "error": None,
            "total_duration_ms": 0,
            "background": True,
        }

    def start_demo(self, *, background: bool = True,
                   initial_args: Optional[dict] = None) -> dict:
        """Запускает демонстрационный сценарий: пять шагов по трём серверам.

        Это тот же путь, что у кнопки «🚀 Запустить демо-сценарий»: реплика, план и
        аргументы берутся из домена, поэтому кнопка, CLI-прогон и тест запускают
        ровно один и тот же сценарий. ``initial_args`` дополняет умолчания дня —
        так можно перенаправить демо на другой файл или формат, не меняя план.

        Пустой флот отвергается до создания запуска: план демо-сценария всегда
        валиден, поэтому без этой проверки кнопка отвечала бы «запущено», а прогон
        падал бы на первом шаге — причина («флот пуст») должна приходить сразу и
        одним понятным текстом, как у ``/orchestration/run`` без плана.
        """
        if not self.orchestrator.registry.list_all_tools():
            raise OrchestrationRejected(
                "Флот пуст: ни один сервер не опубликовал инструментов — "
                "демонстрационный сценарий выполнять нечем",
                REASON_BAD_QUERY,
            )
        args = demo_arguments()
        args.update(initial_args or {})
        return self.start_run(DEMO_QUERY, plan=DEMO_PLAN, initial_args=args,
                              background=background)

    def _run(self, run_id: int, query: str, cfg: dict, args: dict) -> None:
        """Тело фонового потока: прогон и терминальный статус при любом исходе."""
        started = time.perf_counter()
        try:
            self.orchestrator.execute(query, cfg, initial_args=args, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 — фон не должен ронять процесс
            logger.error("Оркестрация %s упала: %s", run_id, exc)
            self.store.update_run(
                run_id,
                status=OrchestrationState.FAILED.value,
                finished_at=datetime.now(timezone.utc),
                total_duration_ms=int((time.perf_counter() - started) * 1000),
                servers_used=[],
            )

    # ---------- чтение ----------
    def report(self, run_id: int) -> dict:
        """Отчёт о запуске: строка запуска, все шаги, серверы, итог и причина остановки."""
        run = self.store.run(run_id)
        if run is None:
            raise OrchestrationRejected(
                f"Запуск оркестрации {run_id} не найден", REASON_NOT_FOUND
            )
        steps = self.store.steps(run_id)
        failed = next((step for step in steps if step["status"] == STEP_FAILED), None)
        stopped = next((step for step in steps if step["status"] == STEP_STOPPED), None)
        return {
            "run": run,
            "steps": steps,
            "count": len(steps),
            "servers_used": list(run.get("servers_used") or []),
            "failed_at_step": failed["step_index"] if failed else None,
            "message": self._message(run["status"], stopped),
            "error": failed["error_message"] if failed else None,
        }

    def _message(self, status: str, stopped: Optional[dict]) -> str:
        """Итоговое сообщение запуска (шаг ``stopped`` уточняет причину досрочности)."""
        if stopped is not None and stopped.get("error_message"):
            return str(stopped["error_message"])
        return {
            OrchestrationState.RUNNING.value: MSG_RUNNING,
            OrchestrationState.COMPLETED.value: MSG_COMPLETED,
            OrchestrationState.FAILED.value: MSG_FAILED,
            OrchestrationState.STOPPED.value: MSG_STOPPED,
        }.get(status, "")

    def list_runs(self, status: Optional[str] = None,
                  limit: int = config.ORCH_RUNS_LIMIT) -> dict:
        """История запусков (свежие первыми) плюс статистика по журналу шагов."""
        runs = self.store.list_runs(status=status, limit=limit)
        return {"runs": runs, "count": len(runs), "stats": self.store.stats()}

    def steps(self, run_id: int) -> dict:
        """Шаги одного запуска (пустой список — запуск есть, шагов пока нет)."""
        if self.store.run(run_id) is None:
            raise OrchestrationRejected(
                f"Запуск оркестрации {run_id} не найден", REASON_NOT_FOUND
            )
        steps = self.store.steps(run_id)
        return {"run_id": int(run_id), "steps": steps, "count": len(steps)}

    def delete_run(self, run_id: int) -> dict:
        """Удаляет запуск вместе с шагами (каскад)."""
        if not self.store.delete_run(run_id):
            raise OrchestrationRejected(
                f"Запуск оркестрации {run_id} не найден", REASON_NOT_FOUND
            )
        return {"status": "deleted", "run_id": int(run_id)}

    def statuses(self) -> tuple[str, ...]:
        """Статусы запусков (значения ``OrchestrationState``) — для фильтра API."""
        return tuple(state.value for state in OrchestrationState)


def get_orchestration_service() -> OrchestrationService:
    """Служба оркестрации процесса: создаётся лениво и живёт одна на процесс.

    Точка подмены для тестов:
    ``monkeypatch.setattr(main, "get_orchestration_service", ...)`` — подмену видят
    и роутер (через ``core.dependencies``), и агент.
    """
    global _service
    if _service is None:
        _service = OrchestrationService()
    return _service
