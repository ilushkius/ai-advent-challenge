"""Служба пайплайнов (день 19): запуск, чтение истории, удаление.

Разделение с ``Pipeline`` простое: ``Pipeline`` знает, КАК выполнить шаги, а
``PipelineService`` — когда запускать (синхронно или фоном), что отдавать API и
как читать журнал. Роутер ``/pipelines`` и агент работают только с ней, поэтому
порядок «создать запуск → выполнить → поставить терминальный статус» описан в
одном месте.

Фоновый запуск. Прогон идёт в отдельном потоке (``threading.Thread``, daemon):
запрос ``POST /pipelines/run`` обязан вернуться сразу, а интерфейс — опрашивать
статус из БД. Строка запуска создаётся ДО старта потока, поэтому состояние
``running`` видно с первого же опроса (гонки «запуск ещё не записан» нет).

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
from ..domain.pipeline_fsm import PipelineState
from ..domain.pipeline_spec import (
    DEFAULT_PIPELINE,
    MSG_COMPLETED,
    MSG_FAILED,
    MSG_RUNNING,
    MSG_STOPPED,
    REASON_NOT_FOUND,
    STEP_FAILED,
    STEP_STOPPED,
    PipelineRejected,
    validate_pipeline,
)
from ..storage.pipeline_store import PipelineStore
from .pipeline import Pipeline

logger = get_logger(__name__)

#: Единственная служба процесса (ставится лениво при первом обращении).
_service: Optional["PipelineService"] = None


class PipelineService:
    """Запуски пайплайна: старт (в фоне или синхронно), чтение истории, удаление."""

    def __init__(self, pipeline: Optional[Pipeline] = None,
                 store: Optional[PipelineStore] = None) -> None:
        self._pipeline = pipeline
        self._store = store

    @property
    def pipeline(self) -> Pipeline:
        """Прогон: переданный или собранный на хранилище процесса."""
        if self._pipeline is None:
            self._pipeline = Pipeline(store=self.store)
        return self._pipeline

    @property
    def store(self) -> PipelineStore:
        """Хранилище журнала: переданное или хранилище процесса."""
        if self._store is None:
            self._store = PipelineStore()
        return self._store

    def start_pipeline(self, pipeline_config: Optional[dict],
                       initial_args: Optional[dict] = None,
                       *, background: bool = True) -> dict:
        """Запускает пайплайн: ``background=True`` — в потоке, ``False`` — сразу.

        Без конфигурации выполняется встроенный пайплайн (``DEFAULT_PIPELINE``):
        так ``POST /pipelines/run`` без тела и агент по реплике запускают одно и то
        же, а декларация живёт в одном месте — ``domain/pipeline_spec.py``.
        """
        cfg = validate_pipeline(pipeline_config or DEFAULT_PIPELINE)
        args = dict(initial_args or {})
        if not background:
            report = self.pipeline.run_pipeline(cfg, args)
            return {**report, "background": False}
        run = self.store.create_run(
            pipeline_name=cfg["name"],
            status=PipelineState.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
        run_id = int(run["id"])
        thread = threading.Thread(
            target=self._run,
            args=(run_id, cfg, args),
            daemon=True,
            name=f"pipeline-{run_id}",
        )
        thread.start()
        logger.info("Пайплайн %s запущен в фоне (шагов: %d)", run_id, len(cfg["steps"]))
        return {
            "run_id": run_id,
            "pipeline_name": cfg["name"],
            "status": PipelineState.RUNNING.value,
            "steps": [],
            "count": 0,
            "failed_at_step": None,
            "message": MSG_RUNNING,
            "error": None,
            "total_duration_ms": 0,
            "background": True,
        }

    def _run(self, run_id: int, cfg: dict, args: dict) -> None:
        """Тело фонового потока: прогон и терминальный статус при любом исходе."""
        started = time.perf_counter()
        try:
            self.pipeline.run_pipeline(cfg, args, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 — фон не должен ронять процесс
            logger.error("Пайплайн %s упал: %s", run_id, exc)
            self.store.update_run(
                run_id,
                status=PipelineState.FAILED.value,
                finished_at=datetime.now(timezone.utc),
                total_duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def report(self, run_id: int) -> dict:
        """Отчёт о запуске: строка запуска, все его шаги, итог и причина остановки."""
        run = self.store.run(run_id)
        if run is None:
            raise PipelineRejected(
                f"Запуск пайплайна {run_id} не найден", REASON_NOT_FOUND
            )
        steps = self.store.steps(run_id)
        failed = next(
            (step for step in steps if step["status"] == STEP_FAILED), None
        )
        stopped = next(
            (step for step in steps if step["status"] == STEP_STOPPED), None
        )
        return {
            "run": run,
            "steps": steps,
            "count": len(steps),
            "failed_at_step": failed["step_index"] if failed else None,
            "message": self._message(run["status"], stopped),
            "error": failed["error_message"] if failed else None,
        }

    def _message(self, status: str, stopped: Optional[dict]) -> str:
        """Итоговое сообщение запуска по его статусу (шаг ``stopped`` уточняет причину)."""
        if stopped is not None and stopped.get("error_message"):
            return str(stopped["error_message"])
        return {
            PipelineState.RUNNING.value: MSG_RUNNING,
            PipelineState.COMPLETED.value: MSG_COMPLETED,
            PipelineState.FAILED.value: MSG_FAILED,
            PipelineState.STOPPED.value: MSG_STOPPED,
        }.get(status, "")

    def list_runs(self, status: Optional[str] = None,
                  limit: int = config.PIPELINE_RUNS_LIMIT) -> dict:
        """История запусков (свежие первыми), при желании — одного статуса."""
        runs = self.store.list_runs(status=status, limit=limit)
        return {"runs": runs, "count": len(runs)}

    def steps(self, run_id: int) -> dict:
        """Шаги одного запуска (пустой список — запуск есть, шагов пока нет)."""
        if self.store.run(run_id) is None:
            raise PipelineRejected(
                f"Запуск пайплайна {run_id} не найден", REASON_NOT_FOUND
            )
        steps = self.store.steps(run_id)
        return {"run_id": int(run_id), "steps": steps, "count": len(steps)}

    def delete_run(self, run_id: int) -> dict:
        """Удаляет запуск вместе с шагами (каскад)."""
        if not self.store.delete_run(run_id):
            raise PipelineRejected(
                f"Запуск пайплайна {run_id} не найден", REASON_NOT_FOUND
            )
        return {"status": "deleted", "run_id": int(run_id)}

    def statuses(self) -> tuple[str, ...]:
        """Статусы запусков (значения ``PipelineState``) — для валидации фильтра."""
        return tuple(state.value for state in PipelineState)


def get_pipeline_service() -> PipelineService:
    """Служба пайплайнов процесса: создаётся лениво и живёт одна на процесс.

    Точка подмены для тестов: ``monkeypatch.setattr(main, "get_pipeline_service", ...)``
    — подмену видят и роутер (через ``core.dependencies``), и агент.
    """
    global _service
    if _service is None:
        _service = PipelineService()
    return _service
