"""Хранилище запусков пайплайна в SQLite (день 19): ``PipelineStore``.

Здесь живут строки ``pipeline_runs`` и ``pipeline_steps``: создание запуска, его
терминальный статус, одна строка журнала на шаг и чтение истории. Правила («какие
переходы статуса допустимы», «как разрешаются ссылки аргументов») — в домене
(``pipeline_fsm``, ``pipeline_mapping``); хранилище их не повторяет, поэтому
тестируется без автомата и без пайплайна.

Зачем хранилище вообще нужно: прогон запускается в фоновом потоке, а интерфейс
опрашивает его статус из другого потока и процесса. Память процесса такого не
переживёт, поэтому запуск и шаги пишутся в БД, а ``GET /pipelines/runs/{id}``
читает их оттуда — и прогресс виден, пока прогон идёт.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from ..core import config
from ..models.pipeline import PipelineRun, PipelineStep
from . import database
from .pipeline_rows import run_dict, step_dict

__all__ = ["PipelineRunNotFoundError", "PipelineStore"]


class PipelineRunNotFoundError(Exception):
    """Запуска с таким id нет в БД (роутер отвечает 404)."""


class PipelineStore:
    """Строки pipeline_runs/pipeline_steps: запуски пайплайна и их шаги."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``SchedulerStore``).

        Сессии короткие намеренно: прогон идёт в фоновом потоке, а SQLite — один
        писатель, поэтому держать транзакцию открытой всё время прогона нельзя.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- запуски ---
    def create_run(self, *, pipeline_name: str, status: str,
                   started_at: datetime) -> dict[str, Any]:
        """Заводит запуск и возвращает его запись."""
        with self.session() as session:
            row = PipelineRun(
                pipeline_name=pipeline_name,
                status=status,
                started_at=started_at,
                total_duration_ms=0,
            )
            session.add(row)
            session.commit()
            return run_dict(row)

    def update_run(self, run_id: int, *, status: str, finished_at: datetime,
                   total_duration_ms: int) -> dict[str, Any]:
        """Ставит терминальный статус, момент окончания и общую длительность."""
        with self.session() as session:
            row = self.run_row(session, run_id)
            row.status = status
            row.finished_at = finished_at
            row.total_duration_ms = int(total_duration_ms)
            session.commit()
            return run_dict(row)

    def run(self, run_id: int) -> Optional[dict[str, Any]]:
        """Запуск по id (``None`` — нет такого)."""
        with self.session() as session:
            row = self._find(session, run_id)
            return run_dict(row) if row is not None else None

    def run_row(self, session, run_id: int) -> PipelineRun:
        """Строка запуска в уже открытой сессии или ``PipelineRunNotFoundError``."""
        row = self._find(session, run_id)
        if row is None:
            raise PipelineRunNotFoundError(f"Запуск пайплайна {run_id} не найден")
        return row

    def list_runs(self, status: Optional[str] = None,
                  limit: int = config.PIPELINE_RUNS_LIMIT) -> List[dict[str, Any]]:
        """Запуски от свежих к старым, при желании — только одного статуса."""
        with self.session() as session:
            query = session.query(PipelineRun)
            if status:
                query = query.filter(PipelineRun.status == status)
            rows = (query.order_by(PipelineRun.id.desc())
                    .limit(max(1, int(limit))).all())
            return [run_dict(row) for row in rows]

    def delete_run(self, run_id: int) -> bool:
        """Удаляет запуск вместе с его шагами (каскад); ``False`` — запуска не было."""
        with self.session() as session:
            row = self._find(session, run_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # --- шаги ---
    def add_step(self, *, run_id: int, step_index: int, tool_name: str,
                 input_args: dict[str, Any], output_result: Optional[dict[str, Any]],
                 duration_ms: int, status: str,
                 error_message: Optional[str] = None) -> dict[str, Any]:
        """Пишет строку журнала по одному шагу прогона."""
        with self.session() as session:
            row = PipelineStep(
                run_id=run_id,
                step_index=int(step_index),
                tool_name=tool_name,
                input_args=dict(input_args or {}),
                output_result=output_result,
                duration_ms=int(duration_ms),
                status=status,
                error_message=error_message,
            )
            session.add(row)
            session.commit()
            return step_dict(row)

    def steps(self, run_id: int,
              limit: int = config.PIPELINE_STEPS_LIMIT) -> List[dict[str, Any]]:
        """Шаги запуска по возрастанию номера (в порядке выполнения)."""
        with self.session() as session:
            rows = (session.query(PipelineStep)
                    .filter(PipelineStep.run_id == int(run_id))
                    .order_by(PipelineStep.step_index.asc())
                    .limit(max(1, int(limit))).all())
            return [step_dict(row) for row in rows]

    def _find(self, session, run_id: int) -> Optional[PipelineRun]:
        """Строка запуска по id (``None`` — нет такого)."""
        return session.query(PipelineRun).filter(PipelineRun.id == int(run_id)).first()
