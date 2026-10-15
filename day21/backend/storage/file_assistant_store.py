"""Хранилище запусков ассистента файлов в SQLite (день 34): ``FileAssistantStore``.

Здесь живёт строка ``file_assistant_runs``: создание запуска, его закрытие целиком
(статус, план, журнал шагов, списки файлов и diff) и чтение истории. Правила
(«какой план годен», «что считается изменением файла», «какой вердикт») — в домене
(``file_assistant``, ``file_assistant_plan``, ``file_assistant_report``); хранилище
их не повторяет, поэтому тестируется без модели и без MCP.

Зачем хранилище вообще нужно. Прогон делает 2–4 вызова модели и десятки вызовов
инструментов, то есть идёт секунды; интерфейс при этом перерисовывается и читает
историю из другого потока. Память процесса такого не переживёт, поэтому цель, план и
журнал пишутся в БД, а ``GET /file-assistant/history`` читает их оттуда — и история
видна после рестарта приложения.

Хранилище без состояния, как ``SchedulerStore`` и ``PipelineStore``: своего
синглтона на процесс ему не нужно, фабрика сессий по умолчанию берётся у дня
(``database.SessionLocal``), а тесты передают свою.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from ..domain import file_assistant
from ..models.file_assistant import FileAssistantRun
from . import database
from .file_assistant_rows import run_dict

__all__ = ["FileAssistantRunNotFoundError", "FileAssistantStore"]


class FileAssistantRunNotFoundError(Exception):
    """Запуска с таким id нет в БД (роутер отвечает 404)."""


class FileAssistantStore:
    """Строки file_assistant_runs: запуски ассистента файлов и их журнал."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``PipelineStore``).

        Сессии короткие намеренно: между началом и концом прогона проходят запросы
        к модели и MCP-серверу, а SQLite — один писатель; держать транзакцию
        открытой всё это время нельзя.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- запуски ---
    def create_run(self, *, goal: str, status: str, started_at: datetime) -> dict[str, Any]:
        """Заводит запуск и возвращает его запись (план и журнал заполнятся позже)."""
        with self.session() as session:
            row = FileAssistantRun(
                goal=goal,
                plan=[],
                steps=[],
                files_read=[],
                files_modified=[],
                files_created=[],
                status=status,
                started_at=started_at,
            )
            session.add(row)
            session.commit()
            return run_dict(row)

    def update_run(self, run_id: int, *, status: str, finished_at: datetime,
                   plan: Optional[list] = None, steps: Optional[list] = None,
                   files_read: Optional[List[str]] = None,
                   files_modified: Optional[List[str]] = None,
                   files_created: Optional[List[str]] = None,
                   diff: Optional[str] = None) -> dict[str, Any]:
        """Закрывает запуск: статус, момент окончания и всё, что накопилось за прогон.

        Пишется одним обновлением, а не по частям: прогон завершён либо целиком, либо
        нет, и «наполовину закрытая» строка в истории была бы неотличима от
        продолжающегося прогона.
        """
        with self.session() as session:
            row = self.run_row(session, run_id)
            row.status = status
            row.finished_at = finished_at
            if plan is not None:
                row.plan = list(plan)
            if steps is not None:
                row.steps = list(steps)
            if files_read is not None:
                row.files_read = [str(path) for path in files_read]
            if files_modified is not None:
                row.files_modified = [str(path) for path in files_modified]
            if files_created is not None:
                row.files_created = [str(path) for path in files_created]
            if diff is not None:
                row.diff = str(diff)
            session.commit()
            return run_dict(row)

    def run(self, run_id: int) -> Optional[dict[str, Any]]:
        """Запуск по id вместе с diff-ом (``None`` — нет такого)."""
        with self.session() as session:
            row = self._find(session, run_id)
            if row is None:
                return None
            record = run_dict(row)
            record["diff"] = str(row.diff or "")
            return record

    def run_row(self, session, run_id: int) -> FileAssistantRun:
        """Строка запуска в уже открытой сессии или ``FileAssistantRunNotFoundError``."""
        row = self._find(session, run_id)
        if row is None:
            raise FileAssistantRunNotFoundError(f"Запуск ассистента файлов {run_id} "
                                                "не найден")
        return row

    def list_runs(self,
                  limit: int = file_assistant.HISTORY_LIMIT) -> List[dict[str, Any]]:
        """Запуски от свежих к старым; ``diff`` в список не входит (его отдаёт отдельно)."""
        with self.session() as session:
            rows = (session.query(FileAssistantRun)
                    .order_by(FileAssistantRun.id.desc())
                    .limit(max(1, int(limit))).all())
            return [run_dict(row) for row in rows]

    def _find(self, session, run_id: int) -> Optional[FileAssistantRun]:
        """Строка по id или ``None``."""
        return session.get(FileAssistantRun, int(run_id))
