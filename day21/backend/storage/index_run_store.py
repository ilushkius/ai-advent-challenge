"""Хранилище запусков индексации в SQLite (день 21): ``IndexRunStore``.

Здесь живёт таблица ``index_runs``: строка запуска создаётся ДО старта фоновой
работы, обновляется по ходу (этап и счётчики) и получает терминальный статус с
длительностями, метриками и текстом ошибки. Правила («какой переход этапа
допустим») — в домене (``domain/indexing_fsm.py``); хранилище их не повторяет.

Зачем это в БД, а не в памяти: прогон идёт в фоновом потоке процесса бэкенда, а
прогресс опрашивает интерфейс из другого процесса. Память процесса такого не
переживает, а ``GET /indexing/runs/{id}`` читает прогресс и после перезапуска.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from ..core import config
from ..models.indexing import IndexRun
from . import database
from .index_rows import index_run_dict

__all__ = ["IndexRunNotFoundError", "IndexRunStore"]


class IndexRunNotFoundError(Exception):
    """Запуска с таким id нет в БД (роутер отвечает 404)."""


class IndexRunStore:
    """Строки ``index_runs``: создание запуска, прогресс, терминальный статус."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``PipelineStore``).

        Короткие сессии намеренны: индексация — долгая работа в фоновом потоке,
        а SQLite — один писатель.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def create_run(self, *, strategy: str, status: str, started_at: datetime,
                   documents_total: int = 0) -> dict[str, Any]:
        """Заводит запуск и возвращает его запись."""
        with self.session() as session:
            row = IndexRun(
                strategy=strategy,
                status=status,
                started_at=started_at,
                documents_total=int(documents_total),
            )
            session.add(row)
            session.commit()
            return index_run_dict(row)

    def update_progress(self, run_id: int, *, status: Optional[str] = None,
                        documents_total: Optional[int] = None,
                        documents_done: Optional[int] = None,
                        chunks_fixed: Optional[int] = None,
                        chunks_structural: Optional[int] = None,
                        embeddings_total: Optional[int] = None,
                        embeddings_done: Optional[int] = None) -> dict[str, Any]:
        """Пишет этап и счётчики прогресса; ``None`` — «поле не менялось».

        ``documents_total`` здесь, а не только в ``create_run``: сколько документов
        нашлось, известно лишь после их сбора, то есть уже во время прогона.
        """
        fields = {
            "status": status,
            "documents_total": documents_total,
            "documents_done": documents_done,
            "chunks_fixed": chunks_fixed,
            "chunks_structural": chunks_structural,
            "embeddings_total": embeddings_total,
            "embeddings_done": embeddings_done,
        }
        with self.session() as session:
            row = self._find(session, run_id)
            if row is None:
                raise IndexRunNotFoundError(f"Запуск индексации {run_id} не найден")
            for name, value in fields.items():
                if value is not None:
                    setattr(row, name, int(value) if name != "status" else value)
            session.commit()
            return index_run_dict(row)

    def finish_run(self, run_id: int, *, status: str, finished_at: datetime,
                   duration_ms: int, embed_duration_ms: int = 0,
                   index_duration_ms: int = 0,
                   metrics: Optional[dict[str, Any]] = None,
                   error: Optional[str] = None) -> dict[str, Any]:
        """Ставит терминальный статус вместе с длительностями, метриками и ошибкой."""
        with self.session() as session:
            row = self._find(session, run_id)
            if row is None:
                raise IndexRunNotFoundError(f"Запуск индексации {run_id} не найден")
            row.status = status
            row.finished_at = finished_at
            row.duration_ms = int(duration_ms)
            row.embed_duration_ms = int(embed_duration_ms)
            row.index_duration_ms = int(index_duration_ms)
            row.metrics = metrics
            row.error = error
            if status == "completed":
                # Успешный прогон доработал все документы, даже если счётчик шёл частями.
                row.documents_done = row.documents_total
            session.commit()
            return index_run_dict(row)

    def run(self, run_id: int) -> Optional[dict[str, Any]]:
        """Запуск по id (``None`` — нет такого)."""
        with self.session() as session:
            row = self._find(session, run_id)
            return index_run_dict(row) if row is not None else None

    def latest(self) -> Optional[dict[str, Any]]:
        """Последний запуск (``None`` — прогонов ещё не было)."""
        with self.session() as session:
            row = (session.query(IndexRun)
                   .order_by(IndexRun.id.desc()).first())
            return index_run_dict(row) if row is not None else None

    def list_runs(self, limit: int = config.INDEX_RUNS_LIMIT) -> List[dict[str, Any]]:
        """Запуски от свежих к старым."""
        with self.session() as session:
            rows = (session.query(IndexRun)
                    .order_by(IndexRun.id.desc())
                    .limit(max(1, int(limit))).all())
            return [index_run_dict(row) for row in rows]

    def _find(self, session, run_id: int) -> Optional[IndexRun]:
        """Строка запуска по id (``None`` — нет такого)."""
        return session.query(IndexRun).filter(IndexRun.id == int(run_id)).first()
