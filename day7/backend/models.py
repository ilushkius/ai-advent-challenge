"""Pydantic-схемы API дня 7 (единое место моделей — конвенция дня 6).

Здесь описаны тела запросов/ответов эндпоинтов FastAPI. Отличие от дня 6:
история агента — это диалог (``MessageOut``), а не записи-попытки; поэтому у
агента ``message_count`` (вместо ``history_count``), а ``GenerateResponse``
содержит обновлённую историю ``messages``.
"""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from . import config


class AgentConfig(BaseModel):
    """Конфигурация нового агента (тело POST /agents).

    model по умолчанию — deepseek-chat; deepseek-reasoner допустима, но может
    игнорировать temperature (поведение провайдера, см. docs/api.md).
    """
    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Человекочитаемое имя агента",
    )
    model: str = Field(
        config.DEFAULT_MODEL, min_length=1, max_length=100,
        description="Модель DeepSeek (deepseek-chat | deepseek-reasoner)",
    )
    temperature: float = Field(
        config.DEFAULT_TEMPERATURE, ge=config.TEMPERATURE_MIN,
        le=config.TEMPERATURE_MAX, description="Температура генерации 0.0–2.0",
    )
    system_prompt: str = Field(
        default="", max_length=4000,
        description="Системный промпт (роль) агента; пустой — без system-сообщения",
    )
    max_tokens: int = Field(
        config.DEFAULT_MAX_TOKENS, ge=config.MAX_TOKENS_MIN,
        le=config.MAX_TOKENS_MAX,
        description="Максимум токенов в ответе (1–8192)",
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустое/пробельное имя."""
        value = value.strip()
        if not value:
            raise ValueError("имя агента не может быть пустым")
        return value


class AgentSummary(BaseModel):
    """Короткая запись об агенте для списка GET /agents.

    message_count — число реплик диалога: фронтенд показывает счётчики в
    боковой панели без отдельных запросов к истории каждого агента.
    """
    agent_id: str
    name: str
    model: str
    message_count: int = 0


class AgentInfo(AgentSummary):
    """Полная информация об агенте (GET /agents/{agent_id}, ответ на создание)."""
    temperature: float
    system_prompt: str
    max_tokens: int
    created_at: datetime


class GenerateRequest(BaseModel):
    """Тело POST /agents/{agent_id}/generate."""
    prompt: str = Field(
        ..., min_length=1, max_length=16000,
        description="Текст запроса к агенту",
    )

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустой/пробельный промпт."""
        value = value.strip()
        if not value:
            raise ValueError("промпт не может быть пустым")
        return value


class MessageOut(BaseModel):
    """Одно сообщение диалога агента (GET history и поле messages в ответе)."""
    id: int
    agent_id: str
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime


class GenerateResponse(BaseModel):
    """Результат генерации: метаданные попытки + обновлённая история.

    Поля response/error взаимоисключающие: при status="ok" заполнен response,
    при status="error" — error. messages — актуальный диалог агента ПОСЛЕ
    попытки (при сбое — неизменная история): фронтенд перерисовывает чат из
    этого списка.
    """
    agent_id: str
    status: str  # "ok" | "error"
    prompt: str
    response: Optional[str] = None
    error: Optional[str] = None
    model: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None  # prompt/completion/total_tokens
    duration_sec: Optional[float] = None
    timestamp: datetime
    messages: List[MessageOut] = Field(default_factory=list)
