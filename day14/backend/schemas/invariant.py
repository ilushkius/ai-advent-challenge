"""Схемы API дня 14: инварианты проекта и результат проверки текста.

Валидация категорий и важности не дублируется: схемы вызывают
``category_from_value`` / ``severity_from_value`` из
``backend/domain/invariant_values.py``, поэтому значение вне Enum — это 422, а не
«тихое» правило-призрак в БД. Границы длин берутся из ``core.config``: те же
константы использует ORM-таблица ``invariants``, поэтому схема и БД не разойдутся.

Результат проверки (``InvariantCheckOut``) собирается сервисом
``InvariantChecker`` и попадает и в ответ ``POST /invariants/check``, и в поле
``invariants`` ответа генерации.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ..core import config
from ..domain.invariant_values import (
    AVAILABLE_CATEGORIES,
    AVAILABLE_SEVERITIES,
    InvariantValueError,
    category_from_value,
    severity_from_value,
)


class InvariantIn(BaseModel):
    """Тело POST /invariants — создать инвариант проекта."""

    name: str = Field(
        ..., min_length=1, max_length=config.INVARIANT_NAME_MAX,
        description="Имя правила (уникально: по нему правило называют в отказе)",
    )
    description: str = Field(
        ..., min_length=1, max_length=config.INVARIANT_DESCRIPTION_MAX,
        description="Формулировка правила; детерминированные правила читают её",
    )
    category: str = Field(
        ..., description=f"Категория: {' | '.join(AVAILABLE_CATEGORIES)}",
    )
    severity: str = Field(
        ..., description=f"Важность: {' | '.join(AVAILABLE_SEVERITIES)}",
    )

    @field_validator("category")
    @classmethod
    def _category_known(cls, value: str) -> str:
        try:
            category_from_value(value)
        except InvariantValueError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("severity")
    @classmethod
    def _severity_known(cls, value: str) -> str:
        try:
            severity_from_value(value)
        except InvariantValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


class InvariantUpdateIn(BaseModel):
    """Тело PUT /invariants/{id} — меняются только переданные поля.

    Значение проверяется, только если поле передано: ``None`` означает «не
    трогать», а не «стереть». Так ``{"is_active": false}`` из интерфейса не
    требует присылать всё тело правила.
    """

    name: Optional[str] = Field(
        None, min_length=1, max_length=config.INVARIANT_NAME_MAX,
    )
    description: Optional[str] = Field(
        None, min_length=1, max_length=config.INVARIANT_DESCRIPTION_MAX,
    )
    category: Optional[str] = None
    severity: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("category")
    @classmethod
    def _category_known(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            category_from_value(value)
        except InvariantValueError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("severity")
    @classmethod
    def _severity_known(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        try:
            severity_from_value(value)
        except InvariantValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


class InvariantOut(BaseModel):
    """Инвариант (ответ всех эндпоинтов /invariants)."""

    id: int
    name: str
    description: str
    category: str
    severity: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InvariantViolationOut(BaseModel):
    """Одно нарушение инварианта в отчёте проверки."""

    name: str
    category: str
    severity: str
    reason: str
    source: str = Field(..., description="deterministic | llm")


class InvariantCheckIn(BaseModel):
    """Тело POST /invariants/check — проверить текст на инварианты."""

    text: str = Field(..., min_length=1, max_length=8000,
                      description="Текст на проверку (реплика или предложение)")
    use_llm: bool = Field(
        True, description="Звать LLM, когда детерминированные правила молчат",
    )


class InvariantCheckOut(BaseModel):
    """Результат проверки текста на инварианты."""

    checked: List[str] = Field(
        default_factory=list,
        description="Имена активных инвариантов, против которых проверяли текст",
    )
    llm_used: bool = False
    verdict: str = Field("allowed", description="allowed | warning | refusal")
    violations: List[InvariantViolationOut] = Field(default_factory=list)
    note: str = Field("", description="Почему LLM-проверка не выполнена (если не выполнена)")
