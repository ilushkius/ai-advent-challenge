"""Хранилище запусков оркестрации в SQLite (день 20): ``OrchestrationStore``.

Здесь живут строки ``orchestration_runs`` и ``orchestration_steps``: создание
запуска, его терминальный статус, одна строка журнала на шаг, чтение истории и
СТАТИСТИКА по серверам и инструментам. Правила («какие переходы статуса
допустимы», «как разрешаются ссылки аргументов») — в домене
(``orchestration_fsm``, ``pipeline_mapping``); хранилище их не повторяет, поэтому
тестируется без автомата и без реестра серверов.

Зачем хранилище вообще нужно: прогон может идти в фоновом потоке, а интерфейс
опрашивает его статус из другого потока и процесса. Память процесса такого не
переживёт, поэтому запуск и шаги пишутся в БД, а ``GET /orchestration/runs/{id}``
читает их оттуда — и прогресс виден, пока прогон идёт, и история переживает
рестарт приложения.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import func

from ..core import config
from ..models.orchestration import OrchestrationRun, OrchestrationStep
from . import database
from .orchestration_rows import run_dict, step_dict

__all__ = ["OrchestrationRunNotFoundError", "OrchestrationStore"]


class OrchestrationRunNotFoundError(Exception):
    """Запуска с таким id нет в БД (роутер отвечает 404)."""


class OrchestrationStore:
    """Строки orchestration_runs/orchestration_steps: запуски и их шаги."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``PipelineStore``).

        Сессии короткие намеренно: прогон может идти в фоновом потоке, а SQLite —
        один писатель, поэтому держать транзакцию открытой всё время прогона нельзя.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- запуски ---
    def create_run(self, *, query: str, plan: dict[str, Any], status: str,
                   started_at: datetime,
                   servers_used: Optional[List[str]] = None) -> dict[str, Any]:
        """Заводит запуск и возвращает его запись."""
        with self.session() as session:
            row = OrchestrationRun(
                query=query,
                plan=dict(plan or {}),
                status=status,
                started_at=started_at,
                total_duration_ms=0,
                servers_used=[str(name) for name in (servers_used or [])],
            )
            session.add(row)
            session.commit()
            return run_dict(row)

    def update_run(self, run_id: int, *, status: str, finished_at: datetime,
                   total_duration_ms: int,
                   servers_used: Optional[List[str]] = None) -> dict[str, Any]:
        """Ставит терминальный статус, момент окончания, длительность и список серверов."""
        with self.session() as session:
            row = self.run_row(session, run_id)
            row.status = status
            row.finished_at = finished_at
            row.total_duration_ms = int(total_duration_ms)
            if servers_used is not None:
                row.servers_used = [str(name) for name in servers_used]
            session.commit()
            return run_dict(row)

    def run(self, run_id: int) -> Optional[dict[str, Any]]:
        """Запуск по id (``None`` — нет такого)."""
        with self.session() as session:
            row = self._find(session, run_id)
            return run_dict(row) if row is not None else None

    def run_row(self, session, run_id: int) -> OrchestrationRun:
        """Строка запуска в уже открытой сессии или ``OrchestrationRunNotFoundError``."""
        row = self._find(session, run_id)
        if row is None:
            raise OrchestrationRunNotFoundError(f"Запуск оркестрации {run_id} не найден")
        return row

    def list_runs(self, status: Optional[str] = None,
                  limit: int = config.ORCH_RUNS_LIMIT) -> List[dict[str, Any]]:
        """Запуски от свежих к старым, при желании — только одного статуса."""
        with self.session() as session:
            query = session.query(OrchestrationRun)
            if status:
                query = query.filter(OrchestrationRun.status == status)
            rows = (query.order_by(OrchestrationRun.id.desc())
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
    def add_step(self, *, run_id: int, step_index: int, server_name: str,
                 tool_name: str, input_args: dict[str, Any],
                 output_result: Optional[dict[str, Any]], duration_ms: int, status: str,
                 error_message: Optional[str] = None) -> dict[str, Any]:
        """Пишет строку журнала по одному шагу прогона."""
        with self.session() as session:
            row = OrchestrationStep(
                run_id=int(run_id),
                step_index=int(step_index),
                server_name=server_name,
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
              limit: int = config.ORCH_STEPS_LIMIT) -> List[dict[str, Any]]:
        """Шаги запуска по возрастанию номера (в порядке выполнения)."""
        with self.session() as session:
            rows = (session.query(OrchestrationStep)
                    .filter(OrchestrationStep.run_id == int(run_id))
                    .order_by(OrchestrationStep.step_index.asc())
                    .limit(max(1, int(limit))).all())
            return [step_dict(row) for row in rows]

    # --- статистика ---
    def stats(self) -> dict[str, Any]:
        """Сводка по журналу: запуски, шаги, среднее время, вызовы по серверам и инструментам.

        Считается по ``orchestration_steps`` (шаг — единица работы), а число
        запусков — по ``orchestration_runs``: так статистика не зависит от того,
        сколько шагов успел выполнить упавший прогон.
        """
        with self.session() as session:
            runs = int(session.query(func.count(OrchestrationRun.id)).scalar() or 0)
            steps = int(session.query(func.count(OrchestrationStep.id)).scalar() or 0)
            avg = session.query(func.avg(OrchestrationStep.duration_ms)).scalar()
            by_server = (
                session.query(
                    OrchestrationStep.server_name,
                    func.count(OrchestrationStep.id),
                    func.avg(OrchestrationStep.duration_ms),
                )
                .group_by(OrchestrationStep.server_name)
                .order_by(func.count(OrchestrationStep.id).desc())
                .all()
            )
            by_tool = (
                session.query(
                    OrchestrationStep.tool_name,
                    OrchestrationStep.server_name,
                    func.count(OrchestrationStep.id),
                )
                .group_by(OrchestrationStep.tool_name, OrchestrationStep.server_name)
                .order_by(func.count(OrchestrationStep.id).desc())
                .all()
            )
        return {
            "runs": runs,
            "steps": steps,
            "avg_step_ms": round(float(avg), 2) if avg is not None else 0.0,
            "servers": [
                {"server": name, "calls": int(calls),
                 "avg_ms": round(float(average or 0), 2)}
                for name, calls, average in by_server
            ],
            "tools": [
                {"tool": tool, "server": server, "calls": int(calls)}
                for tool, server, calls in by_tool
            ],
        }

    def _find(self, session,
              run_id: int) -> Optional[OrchestrationRun]:
        """Строка запуска по id (``None`` — нет такого)."""
        return (session.query(OrchestrationRun)
                .filter(OrchestrationRun.id == int(run_id)).first())
