"""Хранилище инвариантов в SQLite (день 14): ``InvariantManager``.

Что это.
    Единственное место дня, которое открывает сессии и трогает таблицу
    ``invariants``: чтение списка (все/по категории, только активные), создание,
    правка, включение-выключение, удаление и проекция ORM-строки в словарь для
    API и UI. Список читается заново на каждый запрос агента, поэтому правка
    инвариантов видна со следующего хода — без перезапуска процесса.

Почему отдельный модуль.
    Правила проверки живут в домене (``backend/domain/invariant_rules.py``),
    оркестрация проверки — в сервисе
    (``backend/services/invariant_checker.py``), а здесь только хранение. Тот же
    разрез, что ``task_store.py`` / ``task_state.py`` в дне 13: хранилище
    тестируется без правил, правила — без БД.

Стиль ошибок — как в дне 13: неизвестный id → ``InvariantNotFoundError``
(API отвечает 404), занятое имя → ``InvariantExistsError`` (API отвечает 409),
неизвестная категория или важность → ``InvariantValueError`` из домена
(API отвечает 422). «Тихих» заглушек нет: неизвестное значение не превращается
в значение по умолчанию.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.exc import IntegrityError

from shared.logging_utils import get_logger

from . import database
from ..domain.invariant_values import (
    category_from_value,
    severity_from_value,
)
from ..models.invariant import Invariant

__all__ = ["InvariantExistsError", "InvariantManager", "InvariantNotFoundError"]

logger = get_logger(__name__)

# Поля, которые можно менять через ``update_invariant``; всё остальное в ``data``
# игнорируется, чтобы тело PUT не могло переписать ``id`` или метки времени.
UPDATABLE_FIELDS = ("name", "description", "category", "severity", "is_active")


class InvariantNotFoundError(Exception):
    """Инвариант отсутствует в БД (API отвечает 404)."""


class InvariantExistsError(Exception):
    """Инвариант с таким именем уже есть (имя уникально, API отвечает 409)."""


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Приводит метку времени к UTC-aware (как ``task_store._as_utc``).

    Пишем aware-значения, а SQLite возвращает naive: без нормализации один и тот
    же инвариант отдавался бы в API то с ``+00:00``, то без него.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class InvariantManager:
    """CRUD инвариантов: единственная точка работы с таблицей ``invariants``."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def session(self):
        """Короткая сессия SQLAlchemy на операцию (как в ``TaskStateStore``)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- чтение ---
    def invariant_row(self, session, invariant_id: int) -> Invariant:
        """Строка инварианта в уже открытой сессии или ``InvariantNotFoundError``."""
        row = (
            session.query(Invariant)
            .filter(Invariant.id == invariant_id)
            .first()
        )
        if row is None:
            raise InvariantNotFoundError(f"Инвариант {invariant_id} не найден")
        return row

    def invariant_dict(self, row: Invariant) -> dict:
        """ORM-строка → словарь для API/UI (поля те же, что в ``InvariantOut``)."""
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "category": row.category,
            "severity": row.severity,
            "is_active": bool(row.is_active),
            "created_at": _as_utc(row.created_at),
            "updated_at": _as_utc(row.updated_at),
        }

    def get_invariant(self, invariant_id: int) -> Optional[dict]:
        """Инвариант по id или ``None``, если такого нет."""
        with self.session() as session:
            row = (
                session.query(Invariant)
                .filter(Invariant.id == invariant_id)
                .first()
            )
            return self.invariant_dict(row) if row is not None else None

    def get_all_invariants(self, active_only: bool = True) -> List[dict]:
        """Инварианты по алфавиту имён; ``active_only`` — только включённые.

        По умолчанию отдаются только активные: именно этот список уходит в
        системный промпт агента и в проверку. Выключенные видны в интерфейсе и в
        API по ``active_only=false``.
        """
        with self.session() as session:
            query = session.query(Invariant)
            if active_only:
                query = query.filter(Invariant.is_active.is_(True))
            rows = query.order_by(Invariant.name.asc()).all()
            return [self.invariant_dict(row) for row in rows]

    def get_invariants_by_category(self, category: str) -> List[dict]:
        """Инварианты одной категории (и активные, и выключенные) по алфавиту.

        Категория проверяется доменом: неизвестная — ``InvariantValueError``, а не
        пустой список (пустой список означал бы «таких правил нет», а не «опечатка
        в запросе»).
        """
        category_from_value(category)
        with self.session() as session:
            rows = (
                session.query(Invariant)
                .filter(Invariant.category == category)
                .order_by(Invariant.name.asc())
                .all()
            )
            return [self.invariant_dict(row) for row in rows]

    # --- запись ---
    def add_invariant(self, name: str, description: str, category: str,
                      severity: str) -> dict:
        """Создаёт активный инвариант; занятое имя или невалидные значения — ошибка."""
        category_from_value(category)
        severity_from_value(severity)
        now = datetime.now(timezone.utc)
        with self.session() as session:
            self._ensure_name_free(session, name)
            row = Invariant(
                name=name, description=description, category=category,
                severity=severity, is_active=True, created_at=now, updated_at=now,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:  # защита от гонки двух запросов
                session.rollback()
                raise InvariantExistsError(f"Инвариант «{name}» уже существует") from exc
            logger.debug("Инвариант %r создан: %s / %s", name, category, severity)
            return self.invariant_dict(row)

    def update_invariant(self, invariant_id: int, data: dict) -> dict:
        """Меняет переданные поля инварианта и возвращает новое состояние.

        Пустой ``data`` (или только неизвестные ключи) — возврат текущего
        состояния без записи: PUT без изменений не должен двигать ``updated_at``.
        """
        changes = {
            key: value for key, value in (data or {}).items()
            if key in UPDATABLE_FIELDS and value is not None
        }
        if "category" in changes:
            category_from_value(changes["category"])
        if "severity" in changes:
            severity_from_value(changes["severity"])

        with self.session() as session:
            row = self.invariant_row(session, invariant_id)
            if not changes:
                return self.invariant_dict(row)
            if "name" in changes and changes["name"] != row.name:
                self._ensure_name_free(session, changes["name"])
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise InvariantExistsError(
                    f"Инвариант «{changes.get('name')}» уже существует"
                ) from exc
            logger.debug(
                "Инвариант %s обновлён: %s", invariant_id, ", ".join(sorted(changes))
            )
            return self.invariant_dict(row)

    def deactivate_invariant(self, invariant_id: int) -> dict:
        """Выключает инвариант: он уходит из промпта и из проверки, строка остаётся."""
        return self._set_active(invariant_id, False)

    def activate_invariant(self, invariant_id: int) -> dict:
        """Включает инвариант обратно (правило снова действует со следующего хода)."""
        return self._set_active(invariant_id, True)

    def delete_invariant(self, invariant_id: int) -> bool:
        """Удаляет инвариант; ``False`` — инварианта с таким id не было."""
        with self.session() as session:
            row = (
                session.query(Invariant)
                .filter(Invariant.id == invariant_id)
                .first()
            )
            if row is None:
                return False
            name = row.name
            session.delete(row)
            session.commit()
            logger.debug("Инвариант %s (%r) удалён", invariant_id, name)
            return True

    # --- внутреннее ---
    def _set_active(self, invariant_id: int, is_active: bool) -> dict:
        """Общий путь включения и выключения: меняется только флаг и ``updated_at``."""
        with self.session() as session:
            row = self.invariant_row(session, invariant_id)
            row.is_active = is_active
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            logger.debug(
                "Инвариант %s %s", invariant_id,
                "включён" if is_active else "выключен",
            )
            return self.invariant_dict(row)

    def _ensure_name_free(self, session, name: str) -> None:
        """Имя уникально: занятое имя — ``InvariantExistsError`` (API отвечает 409)."""
        existing = (
            session.query(Invariant)
            .filter(Invariant.name == name)
            .first()
        )
        if existing is not None:
            raise InvariantExistsError(f"Инвариант «{name}» уже существует")
