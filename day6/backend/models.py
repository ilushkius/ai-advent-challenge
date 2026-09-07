"""Pydantic-схемы API дня 6 (единое место моделей — требование задачи).

Здесь описаны все тела запросов/ответов эндпоинтов FastAPI, включая
валидацию диапазонов (температура 0–2, max_tokens 1–8192 и т.п.).
"""
from datetime import datetime
from typing import Dict, Optional

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
        """Обрезает пробелы и отклоняет пустое/пробельное имя (иначе "   "
        прошло бы min_length=1 — пробелы считаются символами)."""
        value = value.strip()
        if not value:
            raise ValueError("имя агента не может быть пустым")
        return value


class AgentSummary(BaseModel):
    """Короткая запись об агенте для списка GET /agents."""
    agent_id: str
    name: str
    model: str


class AgentInfo(AgentSummary):
    """Полная информация об агенте (GET /agents/{agent_id} и ответ на создание)."""
    temperature: float
    system_prompt: str
    max_tokens: int
    created_at: datetime
    history_count: int


class GenerateRequest(BaseModel):
    """Тело POST /agents/{agent_id}/generate."""
    prompt: str = Field(
        ..., min_length=1, max_length=16000,
        description="Текст запроса к агенту",
    )

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        """Обрезает пробелы и отклоняет пустой/пробельный промпт (аналогично
        валидатору имени в AgentConfig)."""
        value = value.strip()
        if not value:
            raise ValueError("промпт не может быть пустым")
        return value


class GenerateResponse(BaseModel):
    """Результат попытки генерации (успех или структурированная ошибка).

    Поля response/error взаимоисключающие: при status="ok" заполнен response,
    при status="error" — error (понятное сообщение, без traceback).
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


class HistoryEntry(GenerateResponse):
    """Запись истории попыток агента (GET /agents/{agent_id}/history).

    Новые записи — в начале списка. Включает и успешные попытки, и ошибки.
    """
