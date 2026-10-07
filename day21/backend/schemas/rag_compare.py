"""Pydantic-схемы сравнения провайдеров RAG (день 28).

Строка сравнения несёт оба ответа целиком (``RagQueryOut`` дня 22/26 со своими
источниками, цитатами, временем, режимом и полем ``provider``) — отдельная «урезанная»
форма ответа завела бы второй контракт на те же данные и разошлась бы с ним при
первой же правке записи ответа.

Счётчики сводки те же, что считает ``backend/domain/rag_compare.summary``: значения по
умолчанию (нули и «равно») нужны затем, чтобы пустой прогон отдавал полную форму, а не
``null`` в половине полей.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..domain import rag_mode
from .rag import RagQueryOut

__all__ = ["RagCompareProvidersIn", "RagCompareProvidersOut", "RagProviderRowOut",
           "RagProviderSummaryOut"]


class RagCompareProvidersIn(BaseModel):
    """POST /rag/compare_providers — список вопросов на локальной и облачной модели."""

    questions: Optional[List[str]] = Field(
        None,
        description=(
            "Вопросы; пусто или null — десять контрольных вопросов демо "
            "(backend/data/demo_questions.json)"
        ),
    )
    top_k: int = Field(
        rag_mode.RAG_DEFAULT_TOP_K, ge=1, le=rag_mode.RAG_MAX_TOP_K,
        description="Сколько фрагментов корпуса идёт в контекст каждому провайдеру",
    )
    strategy: Optional[str] = Field(
        None,
        description=(
            "Стратегия поиска: rag_corpus_structural (по умолчанию) | "
            "rag_corpus_fixed"
        ),
    )


class RagProviderRowOut(BaseModel):
    """Строка сравнения: вопрос, ответ локальной модели, ответ облака и вердикт."""

    question: str = Field(..., description="Вопрос, который прогоняли дважды")
    local: RagQueryOut = Field(
        ..., description="Ответ локальной модели Ollama (provider=local)"
    )
    cloud: RagQueryOut = Field(
        ..., description="Ответ облака DeepSeek (provider=deepseek)"
    )
    verdict: str = Field(
        ..., description="Машинный вердикт строки: локально лучше | облако лучше | равно"
    )


class RagProviderSummaryOut(BaseModel):
    """Сводка прогона: счётчики сторон, среднее время и общий вердикт."""

    total: int = Field(0, description="Сколько вопросов в прогоне")
    local_avg_ms: int = Field(0, description="Среднее время ответа локальной модели")
    cloud_avg_ms: int = Field(0, description="Среднее время ответа облака")
    local_rag: int = Field(0, description="Ответов по корпусу у локальной модели")
    cloud_rag: int = Field(0, description="Ответов по корпусу у облака")
    local_dont_know: int = Field(0, description="Режимов «не знаю» у локальной модели")
    cloud_dont_know: int = Field(0, description="Режимов «не знаю» у облака")
    local_with_sources: int = Field(0, description="Строк с источниками у локальной модели")
    cloud_with_sources: int = Field(0, description="Строк с источниками у облака")
    local_verified: int = Field(0, description="Строк с подтверждёнными цитатами локально")
    cloud_verified: int = Field(0, description="Строк с подтверждёнными цитатами у облака")
    better_local: int = Field(0, description="Строк, где вердикт «локально лучше»")
    better_cloud: int = Field(0, description="Строк, где вердикт «облако лучше»")
    equal: int = Field(0, description="Строк, где вердикт «равно»")
    verdict: str = Field("", description="Общий вердикт прогона по большинству строк")


class RagCompareProvidersOut(BaseModel):
    """POST /rag/compare_providers — строки сравнения и сводка по ним."""

    rows: List[RagProviderRowOut] = Field(
        default_factory=list, description="По строке на каждый прогнанный вопрос"
    )
    summary: RagProviderSummaryOut = Field(
        default_factory=RagProviderSummaryOut, description="Сводка по всем строкам"
    )
