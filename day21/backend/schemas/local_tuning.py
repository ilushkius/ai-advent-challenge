"""Pydantic-схемы оптимизации локальной модели (день 29).

Отдельный модуль, а не дополнение ``llm.py``, по той же причине, что у
``rag_compare.py`` дня 28: у прогона профилей свой вход (профили, модели, ``top_k``,
стратегия), своя строка (вопрос с метриками качества, скорости и ресурсов) и своя
сводка с вердиктом пары «до/после». Положить это в схемы расходов значило бы смешать
два контракта — журнал облака и сравнение локальных вариантов.

Строка опирается на ``RagQueryOut``-подобные поля, но не дублирует их форму целиком:
источники (``RagSourceOut``) и цитаты (``RagQuoteOut``) берутся из ``rag.py`` как есть,
а всё остальное — посчитанные доменом ``local_tuning_eval`` значения, поэтому схема не
может разойтись с правилами вердикта и средних.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..domain import rag_mode
from .rag import RagQuoteOut, RagSourceOut

__all__ = ["LocalTuneIn", "LocalTuneOut", "LocalTunePairOut", "LocalTuneProfileOut",
           "LocalTuneRowOut", "LocalTuneSummaryOut", "LocalTuneVariantOut"]


class LocalTuneIn(BaseModel):
    """POST /llm/tune — прогон профилей на кейсе RAG."""

    questions: Optional[List[str]] = Field(
        None,
        description=(
            "Вопросы; пусто или null — десять контрольных вопросов демо "
            "(backend/data/demo_questions.json)"
        ),
    )
    profiles: List[str] = Field(
        default_factory=list,
        description=(
            "Профили настройки: baseline (как день 26) | tuned (после оптимизации). "
            "Пусто — оба в этом порядке; незнакомое имя — 400"
        ),
    )
    models: List[str] = Field(
        default_factory=list,
        description=(
            "Теги моделей Ollama (квант сравнивается так же); пусто — "
            "LOCAL_LLM_MODEL из конфига"
        ),
    )
    top_k: int = Field(
        rag_mode.RAG_DEFAULT_TOP_K, ge=1, le=rag_mode.RAG_MAX_TOP_K,
        description="Сколько фрагментов корпуса идёт в контекст (поиск не меняется)",
    )
    strategy: Optional[str] = Field(
        None,
        description=(
            "Стратегия поиска: rag_corpus_structural (по умолчанию) | rag_corpus_fixed"
        ),
    )


class LocalTuneProfileOut(BaseModel):
    """Параметры варианта: профиль, модель и то, чем он отличается от дня 26."""

    profile: str = Field(..., description="Имя профиля: baseline | tuned")
    label: str = Field("", description="Подпись профиля для интерфейса и отчёта")
    model: Optional[str] = Field(None, description="Тег модели Ollama (null — из конфига)")
    temperature: float = Field(..., description="Температура генерации")
    num_ctx: int = Field(..., description="Окно контекста Ollama (num_ctx)")
    max_tokens: Optional[int] = Field(
        None, description="Предел длины ответа (null — предел типа задачи, как в дне 26)"
    )
    system_prompt: Optional[str] = Field(
        None, description="Системный промпт профиля (null — промпт режима, как в дне 26)"
    )
    system_prompt_chars: int = Field(0, description="Длина системного промпта, символов")


class LocalTuneRowOut(BaseModel):
    """Строка прогона: вопрос, вердикт дня 24 и метрики качества, скорости и ресурсов."""

    question: str = Field(..., description="Вопрос, на который отвечала модель")
    profile: str = Field("", description="Профиль настройки строки")
    model: str = Field("", description="Модель, отвечавшая на вопрос")
    mode: str = Field("", description="rag | dont_know | error")
    verdict: str = Field(
        "", description="Вердикт строки по правилу дня 24 (совпадает, не знаю, ...)"
    )
    mode_match: bool = Field(True, description="Совпал ли режим с ожиданием вопроса")
    sources_found: bool = Field(False, description="Найден ли ожидаемый источник")
    quotes_verified: bool = Field(False, description="Подтверждены ли цитаты ответа")
    quote_count: int = Field(0, description="Сколько цитат пришло с ответом")
    confidence: float = Field(0.0, description="Уверенность ответа (0, 0.3 или 1.0)")
    grounding_ok: bool = Field(False, description="Есть ли опора на контекст")
    answer: str = Field("", description="Текст ответа модели")
    answer_chars: int = Field(0, description="Длина ответа, символов")
    prompt_tokens: int = Field(0, description="Токенов во входе")
    completion_tokens: int = Field(0, description="Токенов в ответе")
    duration_ms: int = Field(0, description="Время запроса целиком, мс")
    tokens_per_second: float = Field(0.0, description="Скорость генерации, токенов в секунду")
    load_ms: int = Field(0, description="Загрузка весов модели в память, мс")
    sources: List[RagSourceOut] = Field(
        default_factory=list, description="Использованные фрагменты корпуса"
    )
    quotes: List[RagQuoteOut] = Field(
        default_factory=list, description="Цитаты из использованных фрагментов"
    )
    expected_mode: str = Field("", description="Ожидаемый режим вопроса демо")
    expected_sources: List[str] = Field(
        default_factory=list, description="Ожидаемые источники вопроса демо"
    )
    warning: str = Field("", description="Предупреждение строки (откат, отказ модели)")


class LocalTuneSummaryOut(BaseModel):
    """Сводка варианта: счётчики качества, среднее время, скорость и суммарный вывод."""

    questions: int = Field(0, description="Сколько вопросов в варианте")
    verdict_ok: int = Field(0, description="Строк, совпавших с ожиданием")
    mode_match: int = Field(0, description="Строк с ожидаемым режимом")
    sources_found: int = Field(0, description="Строк с найденным ожидаемым источником")
    quotes_verified: int = Field(0, description="Строк с подтверждёнными цитатами")
    grounding_ok: int = Field(0, description="Строк с опорой на контекст")
    errors: int = Field(0, description="Строк со сбоем модели (mode=error)")
    avg_ms: int = Field(0, description="Среднее время ответа по строкам режима rag")
    avg_tokens_per_second: float = Field(0.0, description="Средняя скорость генерации")
    completion_tokens: int = Field(0, description="Суммарно токенов вывода")
    avg_answer_chars: float = Field(0.0, description="Средняя длина ответа, символов")


class LocalTuneVariantOut(BaseModel):
    """Вариант прогона «профиль × модель»: параметры, ресурсы, строки и их сводка."""

    params: LocalTuneProfileOut = Field(..., description="Параметры варианта")
    resources: dict = Field(
        default_factory=dict,
        description="Снимок GET /api/ps после прогона: vram_mb, gpu_percent, context_length",
    )
    rows: List[LocalTuneRowOut] = Field(
        default_factory=list, description="По строке на каждый прогнанный вопрос"
    )
    summary: LocalTuneSummaryOut = Field(
        default_factory=LocalTuneSummaryOut, description="Сводка варианта"
    )


class LocalTunePairOut(BaseModel):
    """Пара «baseline → tuned» одной модели: вердикт, разница качества и ускорение."""

    model: str = Field("", description="Модель пары")
    profile: str = Field("", description="Профиль второго варианта пары (обычно tuned)")
    baseline: str = Field("", description="Подпись варианта «до оптимизации»")
    other: str = Field("", description="Подпись варианта «после оптимизации»")
    verdict: str = Field(
        "", description="после оптимизации лучше | до оптимизации лучше | равно"
    )
    quality_delta: int = Field(0, description="Разница числа совпавших строк")
    speedup: float = Field(0.0, description="Во сколько раз быстрее (baseline/other)")


class LocalTuneOut(BaseModel):
    """POST /llm/tune — варианты прогона, пары с вердиктами и ресурсы до старта."""

    url: str = Field("", description="Адрес Ollama")
    model: str = Field("", description="Модель по умолчанию из конфига")
    ollama_version: str = Field("", description="Версия службы Ollama ('' — не сообщила)")
    active_profile: str = Field(
        "", description="Профиль локального провайдера по умолчанию ('' — день 26)"
    )
    profiles: List[LocalTuneProfileOut] = Field(
        default_factory=list, description="Параметры запрошенных профилей"
    )
    top_k: int = Field(rag_mode.RAG_DEFAULT_TOP_K, description="Фрагментов в контексте")
    strategy: Optional[str] = Field(None, description="Стратегия поиска прогона")
    variants: List[LocalTuneVariantOut] = Field(
        default_factory=list, description="По варианту на пару «профиль × модель»"
    )
    pairs: List[LocalTunePairOut] = Field(
        default_factory=list, description="Сравнение «до/после» по каждой модели"
    )
    ps_before: dict = Field(
        default_factory=dict, description="Снимок GET /api/ps до прогона"
    )
    total_ms: int = Field(0, description="Суммарное время ответов модели, мс")
    best: str = Field("", description="Подпись лучшего варианта прогона")
