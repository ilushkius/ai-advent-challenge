"""Схемы API дня 14: профиль пользователя и его вклад в системный промпт.

Валидация значений профиля не дублируется: схемы вызывают ``backend/profiles.py``
(``normalize_preferences``/``normalize_constraints``/``normalize_instructions``),
поэтому неизвестный tone или выход за границы constraints — это 422 с текстом из
одного места. Перенесено из монолитного ``backend/models.py`` без изменения поля.
"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import (
    BaseModel, ConfigDict, Field, field_validator, model_validator,
)

from ..core import config
from ..domain.profiles import (
    ProfileValueError, normalize_constraints, normalize_instructions,
    normalize_preferences,
)


class UserPreferences(BaseModel):
    """Поле preferences профиля: стиль и формат ответов.

    Все поля необязательные: ``None`` = «пользователь не настраивал», в промпт
    такой блок не попадает. Значения проверяются ``profiles``.
    """
    model_config = ConfigDict(extra="forbid")

    tone: Optional[str] = Field(
        None, description="формальный | дружелюбный | технический"
    )
    verbosity: Optional[str] = Field(
        None, description="кратко | подробно | сбалансировано"
    )
    language: Optional[str] = Field(None, description="русский | английский")
    format: Optional[str] = Field(
        None, description="markdown | plain text | структурированный"
    )

    @model_validator(mode="after")
    def _known_values(self) -> "UserPreferences":
        try:
            normalize_preferences(self.model_dump())
        except ProfileValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class UserConstraints(BaseModel):
    """Поле constraints профиля: ограничения ответа.

    ``max_response_length`` — предел длины ответа в символах,
    ``forbidden_topics`` — темы, которые агенту запрещено обсуждать,
    ``required_disclaimers`` — обязательные вставки в каждый ответ.
    """
    model_config = ConfigDict(extra="forbid")

    max_response_length: Optional[int] = Field(
        None, description=(
            f"Предел длины ответа в символах "
            f"({config.MAX_RESPONSE_LENGTH_MIN}–"
            f"{config.MAX_RESPONSE_LENGTH_MAX}); None — без ограничения"
        ),
    )
    forbidden_topics: List[str] = Field(
        default_factory=list,
        description=f"Запрещённые темы (до {config.FORBIDDEN_TOPICS_MAX})",
    )
    required_disclaimers: List[str] = Field(
        default_factory=list,
        description=(
            f"Обязательные дисклеймеры (до {config.DISCLAIMERS_MAX})"
        ),
    )

    @model_validator(mode="after")
    def _valid_constraints(self) -> "UserConstraints":
        try:
            normalize_constraints(self.model_dump())
        except ProfileValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class UserProfileIn(BaseModel):
    """Тело POST/PUT /users/{user_id}/profile (данные профиля).

    Тело описывает профиль целиком (PUT — замена, POST — создание): поля,
    которые не переданы, получают значения по умолчанию («не настроено»).
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        "", max_length=config.PROFILE_NAME_MAX,
        description="Имя для обращения (пустое — без обращения по имени)",
    )
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    constraints: UserConstraints = Field(default_factory=UserConstraints)
    custom_instructions: str = Field(
        "", max_length=config.CUSTOM_INSTRUCTIONS_MAX,
        description=(
            "Произвольные инструкции, одна на строку, например: «Обращайся ко "
            "мне по имени» или «При запросе \"напиши фичу\" спавни агентов в "
            "порядке: аналитик, разработчик, тестировщик»"
        ),
    )

    @field_validator("custom_instructions")
    @classmethod
    def _instructions_valid(cls, value: str) -> str:
        """Проверяет инструкции тем же нормализатором, что и агент."""
        try:
            normalize_instructions(value)
        except ProfileValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


class UserProfileOut(BaseModel):
    """Профиль пользователя (ответы /users и /users/{user_id}/profile)."""
    id: int
    user_id: str
    name: str = ""
    preferences: Dict[str, Optional[str]] = Field(default_factory=dict)
    constraints: Dict[str, object] = Field(default_factory=dict)
    custom_instructions: str = ""
    created_at: datetime
    updated_at: datetime
    # Производные поля (в БД не хранятся): однострочное описание для селектора
    # и признак «профиль реально что-то добавляет в промпт».
    summary: str = ""
    personalized: bool = False
    # Только у ответа PUT: сколько живых агентов получили новые настройки.
    applied_to_agents: int = 0


class UserProfileDeleteOut(BaseModel):
    """Результат DELETE /users/{user_id}/profile."""
    status: str = "deleted"
    user_id: str


class ProfileElementOut(BaseModel):
    """Один элемент профиля, попавший в системный промпт запроса."""
    field: str
    label: str
    value: str
    text: str


class AppliedProfileOut(BaseModel):
    """Какой профиль применён к запросу и что он добавил в системный промпт.

    Разбивка по элементам: ``elements`` — только те поля, которые реально дали
    блок промпта (пустые настройки пропускаются), ``prompt_block`` — весь текст
    профиля, ``personalized`` — False, если профиля нет или он пуст,
    ``system_prompt`` — системное сообщение агента без блоков памяти текущего
    запроса.
    """
    user_id: str
    name: str = ""
    personalized: bool = False
    summary: str = ""
    elements: List[ProfileElementOut] = Field(default_factory=list)
    prompt_block: str = ""
    system_prompt: str = ""
    # Список произвольных инструкций (по одной на строку поля
    # custom_instructions в профиле) — то, что реально ушло в промпт.
    instructions: List[str] = Field(default_factory=list)
