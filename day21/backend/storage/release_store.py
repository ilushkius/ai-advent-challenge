"""Хранилище запусков подготовки релиза в SQLite (день 35): ``ReleaseStore``.

Здесь живёт строка ``release_runs``: создание запуска (статус ``running``), его
закрытие целиком (статус, версия с причиной, тексты разделов, признак проверок и
список записанных файлов) и чтение истории. Правила (какая версия следующая, из чего
собирается раздел, что считается пройденной проверкой) — в домене
(``release``, ``release_checks``); хранилище их не повторяет, поэтому тестируется без
модели, без MCP и без git.

Зачем хранилище вообще нужно. Прогон релиза идёт десятки секунд: два обращения к
модели на пачку коммитов, вызовы MCP, два прогона ``pytest``. Интерфейс при этом
перерисовывается и читает историю из другого потока, а выгрузка
(``POST /release/export``) — уже после прогона; память процесса такого не переживёт,
поэтому версия и тексты пишутся в БД, а история видна и после рестарта приложения.

Хранилище без состояния, как ``FileAssistantStore`` и ``SchedulerStore``: своего
синглтона на процесс ему не нужно, фабрика сессий по умолчанию берётся у дня
(``database.SessionLocal``), а тесты передают свою.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, List, Optional

from ..domain import release
from ..models.release import ReleaseRun
from . import database
from .release_rows import run_dict, run_dict_full

__all__ = ["ReleaseRunNotFoundError", "ReleaseStore"]


class ReleaseRunNotFoundError(Exception):
    """Запуска с таким id нет в БД (роутер отвечает 404)."""


class ReleaseStore:
    """Строки release_runs: запуски подготовки релиза и их тексты."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``FileAssistantStore``).

        Сессии короткие намеренно: между заведением запуска и его закрытием проходят
        вызовы модели, MCP и ``pytest``, а SQLite — один писатель; держать транзакцию
        открытой всё это время нельзя.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def create_run(self, *, from_tag: str, to_tag: str, version: str, status: str,
                   started_at: datetime) -> dict[str, Any]:
        """Заводит запуск и возвращает его запись (версия и тексты заполнятся позже)."""
        with self.session() as session:
            row = ReleaseRun(
                from_tag=from_tag,
                to_tag=to_tag,
                version=version,
                version_reason="",
                changelog=None,
                release_notes=None,
                checks_passed=False,
                files_modified=[],
                status=status,
                started_at=started_at,
            )
            session.add(row)
            session.commit()
            return run_dict(row)

    def update_run(self, run_id: int, *, status: str, finished_at: datetime,
                   version: Optional[str] = None, version_reason: Optional[str] = None,
                   changelog: Optional[str] = None,
                   release_notes: Optional[str] = None,
                   checks_passed: Optional[bool] = None,
                   files_modified: Optional[List[str]] = None) -> dict[str, Any]:
        """Закрывает запуск: статус, момент окончания и всё, что накопилось за прогон.

        Пишется одним обновлением, а не по частям: прогон завершён либо целиком, либо
        нет, и «наполовину закрытая» строка в истории была бы неотличима от
        продолжающегося прогона. ``None`` у поля означает «не трогать» — так
        закрытие после сбоя не стирает уже записанную версию.
        """
        with self.session() as session:
            row = self.run_row(session, run_id)
            row.status = status
            row.finished_at = finished_at
            if version is not None:
                row.version = str(version)
            if version_reason is not None:
                row.version_reason = str(version_reason)
            if changelog is not None:
                row.changelog = str(changelog)
            if release_notes is not None:
                row.release_notes = str(release_notes)
            if checks_passed is not None:
                row.checks_passed = bool(checks_passed)
            if files_modified is not None:
                row.files_modified = [str(path) for path in files_modified]
            session.commit()
            return run_dict(row)

    def run(self, run_id: int) -> Optional[dict[str, Any]]:
        """Запуск по id вместе с текстами разделов (``None`` — нет такого)."""
        with self.session() as session:
            row = self._find(session, run_id)
            return run_dict_full(row) if row is not None else None

    def run_row(self, session, run_id: int) -> ReleaseRun:
        """Строка запуска в уже открытой сессии или ``ReleaseRunNotFoundError``."""
        row = self._find(session, run_id)
        if row is None:
            raise ReleaseRunNotFoundError(f"Запуск подготовки релиза {run_id} не найден")
        return row

    def list_runs(self, limit: int = release.HISTORY_LIMIT) -> List[dict[str, Any]]:
        """Запуски от свежих к старым; тексты разделов в список не входят."""
        with self.session() as session:
            rows = (session.query(ReleaseRun)
                    .order_by(ReleaseRun.id.desc())
                    .limit(max(1, int(limit))).all())
            return [run_dict(row) for row in rows]

    def _find(self, session, run_id: int) -> Optional[ReleaseRun]:
        """Строка по id или ``None``."""
        return session.get(ReleaseRun, int(run_id))
