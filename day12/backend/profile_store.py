"""Профиль пользователя в SQLite (день 12): хранилище и CRUD.

Что это.
    День 12 добавляет персонализацию: у каждого пользователя есть профиль
    (таблица ``user_profiles``), который подключается к системному промпту
    КАЖДОГО запроса агента. Профиль не привязан к агенту жёстко: агент
    ссылается на ``user_id``, поэтому один профиль применяется ко всем агентам
    пользователя, а смена профиля в интерфейсе сразу влияет на следующий
    запрос (``Agent.reload_profile``).

Что здесь.
    * ``ProfileData`` — прочитанный профиль (неизменяемый dataclass): поля из
      БД плюс готовый ``ProfilePrompt`` (текст персонализации и разбивка по
      элементам) и однострочное описание для интерфейса;
    * ``ProfileStore`` — единственная точка доступа к таблице ``user_profiles``:
      чтение (``load``/``get``/``list_all``) и CRUD (``create``/``update``/
      ``delete``) с явными ошибками ``ProfileNotFoundError``/``ProfileExistsError``.

Границы.
    Модуль не знает ни про LLM, ни про FastAPI/Streamlit: он читает и пишет
    SQLite через переданную фабрику сессий (как ``MemoryManager`` для слоёв
    памяти). Валидация значений — в ``backend/profiles.py``, поэтому здесь
    только персистентность.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from typing import Any, Dict, List, Optional

from . import config, database
from .database import UserProfile
from .profiles import (
    DEFAULT_CONSTRAINTS, DEFAULT_PREFERENCES, ProfilePrompt, build_profile_prompt,
    describe_profile, instructions_text, normalize_constraints,
    normalize_instructions, normalize_preferences,
)


class ProfileNotFoundError(Exception):
    """Профиль пользователя отсутствует в БД (API отвечает 404)."""


class ProfileExistsError(Exception):
    """Профиль пользователя уже существует (POST отвечает 409)."""


@dataclass(frozen=True)
class ProfileData:
    """Профиль пользователя: данные из БД + производные поля.

    ``exists=False`` — профиля в БД нет: агент работает без персонализации
    (``prompt`` пустой), а API отвечает 404. Это не «пустой профиль из БД», а
    именно отсутствие настройки, поэтому флаг хранится явно.
    """

    user_id: str = config.DEFAULT_USER_ID
    name: str = ""
    preferences: Dict[str, Optional[str]] = field(
        default_factory=lambda: dict(DEFAULT_PREFERENCES)
    )
    constraints: Dict[str, Any] = field(
        default_factory=lambda: {
            "max_response_length": None, "forbidden_topics": [],
            "required_disclaimers": [],
        }
    )
    custom_instructions: str = ""
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    exists: bool = False

    @cached_property
    def instructions(self) -> List[str]:
        """Произвольные инструкции списком (по одной на строку текста)."""
        return normalize_instructions(self.custom_instructions)

    @cached_property
    def prompt(self) -> ProfilePrompt:
        """Готовый блок персонализации: текст + элементы для ответа API/UI."""
        return build_profile_prompt(
            name=self.name,
            preferences=self.preferences,
            constraints=self.constraints,
            custom_instructions=self.custom_instructions,
        )

    @cached_property
    def summary(self) -> str:
        """Однострочное описание профиля (селектор пользователя в UI, отчёт)."""
        return describe_profile(
            name=self.name,
            preferences=self.preferences,
            constraints=self.constraints,
            custom_instructions=self.custom_instructions,
        )

    @property
    def personalized(self) -> bool:
        """True, если профиль добавляет в системный промпт хотя бы один блок."""
        return self.prompt.personalized

    def as_dict(self) -> Dict[str, Any]:
        """Словарь для API/UI (поля БД + summary/personalized)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "preferences": dict(self.preferences),
            "constraints": {
                "max_response_length": self.constraints.get("max_response_length"),
                "forbidden_topics": list(self.constraints.get("forbidden_topics") or []),
                "required_disclaimers": list(
                    self.constraints.get("required_disclaimers") or []
                ),
            },
            "custom_instructions": self.custom_instructions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "personalized": self.personalized,
        }


def empty_profile(user_id: str = config.DEFAULT_USER_ID) -> ProfileData:
    """Профиль-заглушка для пользователя без записи в БД (без персонализации)."""
    return ProfileData(user_id=user_id)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Приводит метку времени к UTC-aware.

    Пишем в БД aware-значения (``datetime.now(timezone.utc)``), а SQLite
    возвращает их naive: без нормализации один и тот же профиль отдавался бы в
    API то с ``+00:00``, то без него. Считаем naive-значение UTC — так же, как
    его и записали.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _from_row(row: UserProfile) -> ProfileData:
    """ORM-строка ``user_profiles`` → ``ProfileData`` (с нормализацией полей)."""
    return ProfileData(
        user_id=row.user_id,
        name=row.name or "",
        preferences=normalize_preferences(row.preferences),
        constraints=normalize_constraints(row.constraints),
        custom_instructions=row.custom_instructions or "",
        id=row.id,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
        exists=True,
    )


def _clean_user_id(user_id: str) -> str:
    """Идентификатор пользователя без пробелов по краям (границы — в схемах)."""
    value = (user_id or "").strip()
    if not value:
        raise ValueError("user_id не может быть пустым")
    if len(value) > config.USER_ID_MAX:
        raise ValueError(f"user_id длиннее {config.USER_ID_MAX} символов")
    return value


class ProfileStore:
    """CRUD профилей пользователей в таблице ``user_profiles``.

    Фабрика сессий передаётся в конструктор (как в ``MemoryManager``): приложение
    использует ``database.SessionLocal``, офлайн-тесты — фабрику на временной БД.
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    @contextmanager
    def _session(self):
        """Короткая сессия SQLAlchemy на операцию (потокобезопасно)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # --- чтение ---
    def load(self, user_id: str) -> ProfileData:
        """Профиль пользователя; если записи нет — пустой профиль (без ошибки).

        Используется агентом при инициализации и при каждом обновлении профиля:
        отсутствие профиля — штатная ситуация «персонализация не настроена».
        """
        return self.get(user_id) or empty_profile(_clean_user_id(user_id))

    def get(self, user_id: str) -> Optional[ProfileData]:
        """Профиль пользователя или None, если записи нет."""
        user_id = _clean_user_id(user_id)
        with self._session() as session:
            row = (
                session.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .first()
            )
            return _from_row(row) if row is not None else None

    def list_all(self) -> List[ProfileData]:
        """Все профили по возрастанию ``user_id`` (стабильный порядок для UI)."""
        with self._session() as session:
            rows = (
                session.query(UserProfile)
                .order_by(UserProfile.user_id.asc())
                .all()
            )
            return [_from_row(row) for row in rows]

    # --- запись ---
    def create(self, user_id: str, name: str = "",
               preferences: Optional[Dict[str, Any]] = None,
               constraints: Optional[Dict[str, Any]] = None,
               custom_instructions: Any = "") -> ProfileData:
        """Создаёт профиль пользователя (``ProfileExistsError``, если есть)."""
        user_id = _clean_user_id(user_id)
        prefs = normalize_preferences(preferences)
        cons = normalize_constraints(constraints)
        text = instructions_text(normalize_instructions(custom_instructions))
        now = datetime.now(timezone.utc)
        with self._session() as session:
            exists = (
                session.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .first()
            )
            if exists is not None:
                raise ProfileExistsError(
                    f"Профиль пользователя {user_id} уже существует"
                )
            row = UserProfile(
                user_id=user_id, name=(name or "").strip(), preferences=prefs,
                constraints=cons, custom_instructions=text,
                created_at=now, updated_at=now,
            )
            session.add(row)
            session.commit()
            return _from_row(row)

    def update(self, user_id: str, name: str = "",
               preferences: Optional[Dict[str, Any]] = None,
               constraints: Optional[Dict[str, Any]] = None,
               custom_instructions: Any = "") -> ProfileData:
        """Заменяет настройки существующего профиля (иначе ``ProfileNotFoundError``).

        ``created_at`` сохраняется, ``updated_at`` обновляется: по нему видно,
        когда профиль меняли в последний раз.
        """
        user_id = _clean_user_id(user_id)
        prefs = normalize_preferences(preferences)
        cons = normalize_constraints(constraints)
        text = instructions_text(normalize_instructions(custom_instructions))
        with self._session() as session:
            row = (
                session.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .first()
            )
            if row is None:
                raise ProfileNotFoundError(
                    f"Профиль пользователя {user_id} не найден"
                )
            row.name = (name or "").strip()
            row.preferences = prefs
            row.constraints = cons
            row.custom_instructions = text
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            return _from_row(row)

    def delete(self, user_id: str) -> bool:
        """Удаляет профиль; False — записи не было."""
        user_id = _clean_user_id(user_id)
        with self._session() as session:
            deleted = (
                session.query(UserProfile)
                .filter(UserProfile.user_id == user_id)
                .delete()
            )
            session.commit()
        return bool(deleted)
