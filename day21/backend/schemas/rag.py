"""Pydantic-схемы API режима RAG (день 22).

Схемы повторяют форму словарей ``services/rag_service.py``: ответ с контекстом
корпуса и без него (``RagQueryOut``), сравнение двух ответов (``RagCompareOut``)
и состояние корпуса с лимитами (``RagConfigOut``). Роутер не переупаковывает
данные, а только объявляет контракт.

``strategy`` — имя namespace корпуса (``rag_corpus_structural`` |
``rag_corpus_fixed``), а ``top_k`` ограничен ``RAG_MAX_TOP_K``, а не
``INDEX_MAX_TOP_K``: у режима RAG свои лимиты контекста. Пустой ``question``
объявлен без ``min_length`` намеренно — отказ по пустому вопросу это осмысленный
ответ API (400 с кодом ``empty_query``), а не ошибка валидации (422). По той же
причине ``strategy`` объявлен без ``max_length``: ``INDEX_STRATEGY_MAX`` — предел
имён индексов дня 21, а имя корпуса длиннее (``rag_corpus_structural`` — 19
символов), и неизвестную стратегию отвергает сервис, отвечая 400.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..domain import rag_filter, rag_mode


class RagQueryIn(BaseModel):
    """POST /rag/query — ответ по корпусу (с RAG) или без него."""

    question: str = Field(
        ..., max_length=config.INDEX_QUERY_MAX,
        description="Вопрос к корпусу (пустой доходит до сервиса и получает 400)",
    )
    top_k: int = Field(
        rag_mode.RAG_DEFAULT_TOP_K, ge=1, le=rag_mode.RAG_MAX_TOP_K,
        description="Сколько фрагментов корпуса подмешать в контекст",
    )
    strategy: Optional[str] = Field(
        None,
        description=(
            "Стратегия поиска: rag_corpus_structural (по умолчанию) | rag_corpus_fixed. "
            "Без max_length намеренно: неизвестное имя — 400 от сервиса, а не 422"
        ),
    )
    use_rag: bool = Field(
        True,
        description="true — ответ с контекстом корпуса, false — тот же вопрос без контекста",
    )
    provider: Optional[str] = Field(
        None, max_length=16,
        description=(
            "Провайдер ответа: deepseek | local; по умолчанию — LLM_PROVIDER из "
            "конфига. Незнакомое имя — 400"
        ),
    )
    rewrite: bool = Field(
        False,
        description="Переформулировать запрос моделью перед поиском (день 23)",
    )
    rerank: bool = Field(
        False,
        description="Пересортировать кандидатов кросс-энкодером (день 23)",
    )
    min_score: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description=(
            "Порог отсечения: фрагменты ниже балла не попадают в контекст. "
            "С реранкером шкала [0, 1], без него — гибридный балл дня 22"
        ),
    )
    top_k_candidates: Optional[int] = Field(
        None, ge=1, le=rag_filter.RAG_MAX_CANDIDATES,
        description="Сколько кандидатов запросить у поиска (по умолчанию — пул дня 22)",
    )


class RagSourceOut(BaseModel):
    """Использованный фрагмент корпуса: откуда взят и насколько близок вопросу."""

    source: str = Field(..., description="Файл корпуса (имя документа-источника дня 21)")
    title: str = Field("", description="Заголовок документа")
    section: str = Field("", description="Заголовок раздела (пусто у стратегии fixed)")
    chunk_id: str = Field(..., description="Идентификатор чанка внутри стратегии")
    score: float = Field(..., description="Балл, по которому фрагмент отобран (больше — ближе)")
    vector_score: float = Field(0.0, description="Косинусная близость FAISS (день 23)")
    lexical_score: float = Field(0.0, description="Словесный вес фрагмента (день 22)")
    rerank_score: Optional[float] = Field(
        None, description="Балл кросс-энкодера реранкера (None — реранка не было)"
    )


class RagTokensOut(BaseModel):
    """Расход вызова модели: токены, кэш контекста и оценка стоимости."""

    model: str = Field(..., description="Модель, ответившая на вопрос")
    prompt_tokens: int = Field(0, description="Токенов во входе (промпт и контекст)")
    completion_tokens: int = Field(0, description="Токенов в ответе")
    cache_hit_tokens: int = Field(0, description="Токенов промпта из кэша контекста")
    cache_miss_tokens: int = Field(0, description="Токенов промпта, посчитанных заново")
    cache_hit_percent: float = Field(0.0, description="Доля попаданий в кэш, %")
    cost_estimate: float = Field(0.0, description="Оценка стоимости запроса, в валюте дня")


class RagQuoteOut(BaseModel):
    """Цитата из использованного фрагмента корпуса (день 24).

    Цитата берётся из чанка детерминированно — начало фрагмента до конца первого
    предложения, не длиннее 200 символов, — и не зависит от того, обернула ли
    модель текст в кавычки.
    """

    source: str = Field("", description="Файл корпуса, откуда взята цитата")
    section: str = Field("", description="Заголовок раздела (пусто у стратегии fixed)")
    chunk_id: str = Field(..., description="Идентификатор чанка внутри стратегии")
    quote: str = Field("", description="Текст цитаты — начало фрагмента")


class RagQueryOut(BaseModel):
    """Ответ режима RAG: режим, текст, источники, расход и оценка опоры."""

    mode: str = Field(
        ...,
        description=(
            "rag — ответ с контекстом корпуса, no_rag — без него, "
            "dont_know — контекста не хватило, модель не вызывалась (день 24)"
        ),
    )
    question: str = Field(..., description="Вопрос, на который отвечали")
    answer: str = Field(..., description="Текст ответа модели")
    provider: str = Field(
        "", description="Кто ответил: deepseek (облако) или local (Ollama по HTTP)"
    )
    fallback: bool = Field(
        False, description="true — вызов с RAG не удался и ответ дан без контекста"
    )
    warning: str = Field("", description="Предупреждение отката (пусто — отказов не было)")
    grounding: str = Field(
        "", description="Опора ответа на контекст (пусто в режиме без RAG)"
    )
    sources: List[RagSourceOut] = Field(
        default_factory=list, description="Чанки, попавшие в контекст, по убыванию близости"
    )
    quotes: List[RagQuoteOut] = Field(
        default_factory=list, description="Цитаты использованных фрагментов (день 24)"
    )
    confidence: float = Field(
        0.0,
        description="Уверенность: 1.0 с подтверждёнными цитатами, 0.3 без, 0.0 без RAG",
    )
    quotes_verified: bool = Field(
        False, description="true — ответ опирается хотя бы на одну цитату контекста"
    )
    chunks_used: int = Field(0, description="Сколько фрагментов ушло в промпт")
    context_tokens: int = Field(0, description="Размер блока контекста в токенах")
    duration_ms: int = Field(0, description="Сколько занял запрос целиком")
    tokens: Optional[RagTokensOut] = Field(None, description="Расход вызова (None — вызова не было)")
    query_used: str = Field("", description="Текст, по которому реально искали (день 23)")
    rewritten: bool = Field(False, description="true — запрос переформулирован моделью")
    reranked: bool = Field(False, description="true — порядок фрагментов дал кросс-энкодер")
    candidates: int = Field(0, description="Сколько фрагментов было ДО отсечения")
    kept: int = Field(0, description="Сколько фрагментов осталось ПОСЛЕ отсечения")
    min_score: Optional[float] = Field(None, description="Порог отсечения (None — без порога)")
    top_k_candidates: int = Field(0, description="Размер пула кандидатов поиска")
    rewrite_warning: str = Field("", description="Сбой переформулировки (пусто — её не было)")
    rerank_warning: str = Field("", description="Сбой реранкера (порядок как в дне 22)")
    filter_warning: str = Field("", description="Порог отбросил все фрагменты")


class RagCompareIn(BaseModel):
    """POST /rag/compare — один вопрос, два ответа: с контекстом корпуса и без."""

    question: str = Field(..., max_length=config.INDEX_QUERY_MAX, description="Вопрос к корпусу")
    top_k: int = Field(
        rag_mode.RAG_DEFAULT_TOP_K, ge=1, le=rag_mode.RAG_MAX_TOP_K,
        description="Сколько фрагментов корпуса подмешать в контекст",
    )
    strategy: Optional[str] = Field(
        None, description="Стратегия поиска: rag_corpus_structural (по умолчанию) | rag_corpus_fixed",
    )


class RagCompareOut(BaseModel):
    """Сравнение: ответ без RAG и ответ с RAG на один и тот же вопрос."""

    question: str = Field(..., description="Вопрос, на который отвечали дважды")
    no_rag: RagQueryOut = Field(..., description="Ответ без контекста (база сравнения)")
    rag: RagQueryOut = Field(..., description="Ответ с контекстом корпуса")


class RagModeOut(BaseModel):
    """Один режим отбора в сравнении: имя, подпись и полный результат ответа."""

    mode: str = Field(..., description="Имя режима: baseline | rewrite | rerank | rerank_filter")
    label: str = Field("", description="Человеческая подпись режима для интерфейса и отчёта")
    result: RagQueryOut = Field(..., description="Ответ со всеми метриками отбора")


class RagModesIn(BaseModel):
    """POST /rag/compare_modes — один вопрос, несколько режимов отбора подряд."""

    question: str = Field(..., max_length=config.INDEX_QUERY_MAX, description="Вопрос к корпусу")
    top_k: int = Field(
        rag_mode.RAG_DEFAULT_TOP_K, ge=1, le=rag_mode.RAG_MAX_TOP_K,
        description="Сколько фрагментов корпуса подмешать в контекст",
    )
    strategy: Optional[str] = Field(
        None, description="Стратегия поиска: rag_corpus_structural (по умолчанию) | rag_corpus_fixed",
    )
    modes: Optional[List[str]] = Field(
        None, description="Какие режимы сравнивать (по умолчанию — все четыре)",
    )
    min_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Порог отсечения поверх выбранных режимов",
    )
    top_k_candidates: Optional[int] = Field(
        None, ge=1, le=rag_filter.RAG_MAX_CANDIDATES,
        description="Сколько кандидатов запросить у поиска",
    )


class RagModesOut(BaseModel):
    """Сравнение режимов отбора на одном вопросе (день 23)."""

    question: str = Field(..., description="Вопрос, который прогоняли по режимам")
    modes: List[RagModeOut] = Field(
        default_factory=list, description="Результаты по режимам в порядке запроса"
    )


class RagDemoQuestionOut(BaseModel):
    """Один контрольный вопрос демо: текст, ожидание и ожидаемые источники."""

    question: str = Field(..., description="Текст вопроса")
    expectation: str = Field("", description="Словами: что ждём от ответа")
    expected_mode: str = Field("", description="Ожидаемый режим: rag | dont_know")
    expected_sources: List[str] = Field(
        default_factory=list, description="Слаги файлов корпуса, где лежит ответ"
    )


class RagDemoQuestionsOut(BaseModel):
    """GET /rag/demo-questions — список контрольных вопросов демо."""

    questions: List[RagDemoQuestionOut] = Field(
        default_factory=list, description="Вопросы демо в порядке из файла"
    )


class RagDemoIn(BaseModel):
    """Прогон одного вопроса демо; пустой вопрос — прогнать все."""

    question: Optional[str] = Field(
        None, description="Вопрос из списка демо (None — прогнать все вопросы)"
    )


class RagDemoRowOut(BaseModel):
    """Строка таблицы демо: вопрос, ожидание, ответ, источники, цитаты и вердикт."""

    question: str = Field(..., description="Текст вопроса")
    expectation: str = Field("", description="Ожидание словами")
    expected_mode: str = Field("", description="Ожидаемый режим")
    mode: str = Field(..., description="Фактический режим: rag | no_rag | dont_know")
    top_score: float = Field(0.0, description="Косинус лучшего источника (0 — источников нет)")
    answer: str = Field("", description="Текст ответа")
    sources: List[RagSourceOut] = Field(
        default_factory=list, description="Использованные фрагменты"
    )
    quotes: List[RagQuoteOut] = Field(default_factory=list, description="Цитаты фрагментов")
    confidence: float = Field(0.0, description="Уверенность ответа")
    quotes_verified: bool = Field(False, description="Подтверждают ли цитаты ответ")
    sources_expected: bool = Field(
        False, description="Найден ли хотя бы один ожидаемый источник"
    )
    verdict: str = Field("", description="Итог строки словами (совпадает, расхождение и т. п.)")


class RagDemoSummaryOut(BaseModel):
    """Сводка демо: распределение по режимам, источникам, цитатам и вердиктам."""

    total: int = Field(0, description="Всего строк")
    rag: int = Field(0, description="Строк в режиме rag")
    no_rag: int = Field(0, description="Строк в режиме no_rag")
    dont_know: int = Field(0, description="Строк в режиме dont_know")
    with_sources: int = Field(0, description="Ответов с источниками")
    with_quotes: int = Field(0, description="Ответов с цитатами")
    verified: int = Field(0, description="Ответов с подтверждёнными цитатами")
    mismatches: int = Field(0, description="Строк, разошедшихся с ожиданием")


class RagDemoOut(BaseModel):
    """POST /rag/demo-run — строки прогона и сводка по ним."""

    rows: List[RagDemoRowOut] = Field(default_factory=list, description="Строки прогона")
    summary: RagDemoSummaryOut = Field(
        default_factory=RagDemoSummaryOut, description="Сводка по строкам"
    )


class RagCorpusOut(BaseModel):
    """Состояние корпуса: папка, объём в страницах и готовность к отчёту."""
    corpus_dir: str = Field(..., description="Папка собранного корпуса")
    documents: int = Field(0, description="Сколько документов в корпусе")
    chars: int = Field(0, description="Суммарный объём корпуса в символах")
    pages: int = Field(0, description="Объём корпуса в страницах по 1800 символов")
    min_pages: int = Field(0, description="Минимум страниц, при котором корпус считается полным")
    subdir: str = Field("", description="Подкаталог внутри documents/")
    ready: bool = Field(False, description="Хватает ли корпуса для отчёта сравнения")


class RagIndexOut(BaseModel):
    """Индекс одной стратегии корпуса: сколько чанков лежит в хранилище."""

    strategy: str = Field(..., description="Имя namespace корпуса")
    chunks: int = Field(0, description="Сколько чанков проиндексировано")


class RagConfigOut(BaseModel):
    """GET /rag/config — готовность режима, индексы корпуса и лимиты."""

    ready: bool = Field(..., description="Есть ли корпус и хотя бы один индекс")
    corpus: RagCorpusOut = Field(..., description="Состояние корпуса")
    indexes: List[RagIndexOut] = Field(
        default_factory=list, description="Чанки по стратегиям корпуса"
    )
    chunks_total: int = Field(0, description="Чанков во всех индексах корпуса")
    strategies: List[str] = Field(
        default_factory=list, description="Стратегии корпуса по порядку применения"
    )
    default_strategy: str = Field(..., description="Стратегия поиска по умолчанию")
    top_k_default: int = Field(..., description="Сколько фрагментов берётся по умолчанию")
    top_k_max: int = Field(..., description="Верхняя граница top_k")
    context_max_tokens: int = Field(..., description="Бюджет блока контекста в промпте")
    chunk_max_chars: int = Field(..., description="Предел длины одного фрагмента в символах")
    modes: List[dict] = Field(
        default_factory=list, description="Каталог режимов отбора: имя, подпись и ручки"
    )
    rerank_model: str = Field("", description="Модель кросс-энкодера реранкера")
    min_score_default: float = Field(0.0, description="Порог отсечения по умолчанию")
    candidates_max: int = Field(0, description="Верхняя граница top_k_candidates")
    relevance_threshold: float = Field(
        0.0, description="Порог релевантности: ниже него ответ уходит в режим «не знаю»"
    )


__all__ = [
    "RagCompareIn",
    "RagCompareOut",
    "RagConfigOut",
    "RagCorpusOut",
    "RagDemoIn",
    "RagDemoOut",
    "RagDemoQuestionOut",
    "RagDemoQuestionsOut",
    "RagDemoRowOut",
    "RagDemoSummaryOut",
    "RagIndexOut",
    "RagModeOut",
    "RagModesIn",
    "RagModesOut",
    "RagQueryIn",
    "RagQueryOut",
    "RagQuoteOut",
    "RagSourceOut",
    "RagTokensOut",
]
