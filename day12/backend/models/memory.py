"""Схемы API дня 12: три слоя памяти агента.

Перенесено из монолитного ``backend/models.py`` без изменения полей.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from .. import config
from ..memory import AVAILABLE_CATEGORIES


class MemoryLayerInfo(BaseModel):
    """Один слой памяти в отчёте генерации: использован ли и сколько токенов."""
    layer: str
    used: bool = False
    entries: int = 0
    tokens: int = 0
    details: str = ""


class MemoryInfo(BaseModel):
    """Разбивка контекста по слоям памяти (поле memory в GenerateResponse).

    ``total_tokens`` — сумма токенов трёх слоёв (конспект сюда не входит: это
    сжатие краткосрочного слоя, см. ``token_metrics.summary_tokens``).
    """
    session_id: str
    task_id: str = config.DEFAULT_TASK_ID
    layers: List[MemoryLayerInfo] = Field(default_factory=list)
    short_term_tokens: int = 0
    working_tokens: int = 0
    long_term_tokens: int = 0
    total_tokens: int = 0
    keywords: List[str] = Field(default_factory=list)


class ShortTermMessageIn(BaseModel):
    """Тело POST /agents/{id}/memory/short-term — добавить реплику в сессию."""
    role: str = Field(..., description="user | assistant | system")
    content: str = Field(..., min_length=1, max_length=config.MEMORY_VALUE_MAX)
    session_id: Optional[str] = Field(
        None, description="Сессия; None — текущая сессия агента",
    )

    @field_validator("role")
    @classmethod
    def _role_known(cls, value: str) -> str:
        if value not in ("user", "assistant", "system"):
            raise ValueError(
                "роль должна быть одной из: user, assistant, system"
            )
        return value


class ShortTermMessageOut(BaseModel):
    """Одна реплика краткосрочной памяти (таблица short_term_messages)."""
    id: int
    agent_id: str
    session_id: str
    role: str
    content: str
    created_at: datetime


class ShortTermOut(BaseModel):
    """Реплики краткосрочного слоя сессии (GET /memory/short-term)."""
    agent_id: str
    session_id: str
    messages: List[ShortTermMessageOut] = Field(default_factory=list)


class ShortTermClearOut(BaseModel):
    """Результат очистки краткосрочного слоя (DELETE /memory/short-term)."""
    agent_id: str
    session_id: str
    deleted: int = 0


class WorkingEntryIn(BaseModel):
    """Тело POST /agents/{id}/memory/working — upsert записи рабочей памяти."""
    key: str = Field(..., min_length=1, max_length=config.MEMORY_KEY_MAX)
    value: str = Field(..., min_length=1, max_length=config.MEMORY_VALUE_MAX)
    task_id: Optional[str] = Field(
        None, max_length=config.TASK_ID_MAX,
        description="Задача; None — активная задача агента",
    )


class WorkingEntryOut(BaseModel):
    """Одна запись рабочей памяти (таблица working_memory)."""
    id: int
    agent_id: str
    task_id: str
    key: str
    value: str
    updated_at: datetime


class WorkingMemoryOut(BaseModel):
    """Записи рабочей памяти задачи + список задач (GET /memory/working)."""
    agent_id: str
    task_id: str = config.DEFAULT_TASK_ID
    entries: List[WorkingEntryOut] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)


class LongTermEntryIn(BaseModel):
    """Тело POST /agents/{id}/memory/long-term — upsert долговременной записи."""
    category: str = Field(..., description="profile | preference | decision | knowledge")
    key: str = Field(..., min_length=1, max_length=config.MEMORY_KEY_MAX)
    value: str = Field(..., min_length=1, max_length=config.MEMORY_VALUE_MAX)
    confidence: float = Field(
        1.0, ge=config.CONFIDENCE_MIN, le=config.CONFIDENCE_MAX,
        description="Уверенность в записи: 0.0–1.0 (по умолчанию 1.0)",
    )

    @field_validator("category")
    @classmethod
    def _category_known(cls, value: str) -> str:
        if value not in AVAILABLE_CATEGORIES:
            raise ValueError(
                f"неизвестная категория {value!r}; допустимые: "
                f"{', '.join(AVAILABLE_CATEGORIES)}"
            )
        return value


class LongTermEntryOut(BaseModel):
    """Одна запись долговременной памяти (таблица long_term_memory)."""
    id: int
    agent_id: str
    category: str
    key: str
    value: str
    confidence: float = 1.0
    updated_at: datetime


class LongTermMemoryOut(BaseModel):
    """Записи долговременной памяти + список категорий (GET /memory/long-term)."""
    agent_id: str
    category: Optional[str] = None
    entries: List[LongTermEntryOut] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)


class LongTermDeleteOut(BaseModel):
    """Результат удаления записи долговременной памяти."""
    status: str = "deleted"
    agent_id: str
    entry_id: int


class SessionOut(BaseModel):
    """Результат POST /agents/{id}/memory/session (новая сессия)."""
    agent_id: str
    previous_session_id: str
    session_id: str
    deleted_messages: int = 0


class TaskSetRequest(BaseModel):
    """Тело PUT /agents/{id}/memory/task — переключить активную задачу."""
    task_id: str = Field(..., min_length=1, max_length=config.TASK_ID_MAX)


class TaskOut(BaseModel):
    """Активная задача агента и число записей её рабочей памяти."""
    agent_id: str
    task_id: str = config.DEFAULT_TASK_ID
    entries: int = 0
