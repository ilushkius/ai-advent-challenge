"""Pydantic-схемы API индексации документов (день 21).

Схемы повторяют форму словарей из хранилища и сервиса (``index_rows.py``,
``services/indexing_service.py``), поэтому роутер не переупаковывает данные, а
только объявляет контракт: запуск прогона (``IndexRunOut``), его отчёт с метриками
(``IndexRunReportOut``), статистика двух стратегий (``IndexStatsResponse``),
попадания поиска (``IndexSearchOut``) и отчёт о шаге агента (``IndexingReportOut`` —
поле ``indexing`` ответа генерации).

``strategy`` везде — значение ``ChunkStrategy`` строкой ("fixed" | "structural"),
а в ``IndexClearIn`` допускается ещё и "all" («очистить обе»).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core import config


class IndexRunIn(BaseModel):
    """POST /indexing/run — проиндексировать документы одной стратегией."""

    strategy: str = Field(
        ..., max_length=config.INDEX_STRATEGY_MAX,
        description="Стратегия чанкинга: fixed (окно по токенам) | structural (по структуре)",
    )
    background: bool = Field(
        True,
        description=(
            "true — прогон в фоновом потоке (статус опрашивается через "
            "GET /indexing/status), false — синхронно, с метриками в ответе"
        ),
    )


class IndexDemoIn(BaseModel):
    """POST /indexing/demo — демо-сценарий одной кнопкой: обе стратегии и сравнение."""

    background: bool = Field(
        True,
        description=(
            "true — прогон в фоновом потоке (кнопка «🚀 Запустить демо-индексацию» "
            "сразу получает id и опрашивает прогресс), false — синхронно"
        ),
    )


class IndexChunkOut(BaseModel):
    """Чанк документа: метаданные, текст и границы в исходном файле."""

    id: int = Field(..., description="Номер строки в document_chunks")
    source: str = Field(..., description="Имя файла-документа в documents/")
    title: str = Field(..., description="Заголовок документа")
    section: str = Field("", description="Заголовок раздела (пусто у стратегии fixed)")
    chunk_id: str = Field(..., description="Идентификатор чанка внутри стратегии")
    strategy: str = Field(..., description="Стратегия чанкинга")
    content: str = Field(..., description="Текст чанка")
    token_count: int = Field(0, description="Размер чанка в токенах")
    embedding_id: int = Field(0, description="Id вектора в FAISS (равен id строки)")
    start_char: int = Field(0, description="Начало чанка в тексте документа")
    end_char: int = Field(0, description="Конец чанка в тексте документа")
    section_level: int = Field(0, description="Уровень заголовка секции (0 — преамбула)")
    created_at: Optional[str] = Field(None, description="Когда чанк записан (ISO-8601, UTC)")

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "IndexChunkOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class IndexChunkListOut(BaseModel):
    """GET /indexing/chunks — примеры чанков одной стратегии."""

    strategy: str = Field(..., description="Стратегия выборки")
    chunks: List[IndexChunkOut] = Field(default_factory=list, description="Чанки по порядку")
    count: int = Field(0, description="Сколько чанков в ответе")


class IndexStatsOut(BaseModel):
    """Статистика одной стратегии: объёмы чанков, покрытие и файл индекса."""

    strategy: str = Field(..., description="Стратегия чанкинга")
    chunks: int = Field(0, description="Сколько чанков в индексе")
    tokens_total: int = Field(0, description="Суммарный размер чанков в токенах")
    tokens_avg: float = Field(0.0, description="Средний размер чанка в токенах")
    tokens_min: int = Field(0, description="Минимальный размер чанка")
    tokens_max: int = Field(0, description="Максимальный размер чанка")
    tokens_std: float = Field(0.0, description="Разброс размеров чанков (σ)")
    documents: int = Field(0, description="Сколько документов попало в индекс")
    sources: Dict[str, int] = Field(
        default_factory=dict, description="Сколько чанков пришло из каждого документа"
    )
    with_section: int = Field(0, description="Чанков с непустой секцией (метрика структуры)")
    index_vectors: int = Field(
        0, description="Сколько векторов в FAISS (должно совпадать с `chunks`)"
    )
    histogram: Dict[str, int] = Field(
        default_factory=dict, description="Распределение размеров по бакетам токенов"
    )
    index_file: Optional[str] = Field(None, description="Путь к файлу FAISS")
    index_bytes: int = Field(0, description="Размер файла индекса в байтах")


class IndexStatsResponse(BaseModel):
    """GET /indexing/stats — статистика обеих стратегий сразу (для сравнения)."""

    fixed: IndexStatsOut = Field(..., description="Статистика стратегии fixed")
    structural: IndexStatsOut = Field(..., description="Статистика стратегии structural")


class IndexStartOut(BaseModel):
    """Ответ запуска прогона: он же первый ответ опроса для фонового прогона."""

    run_id: int = Field(..., description="Номер запуска (им опрашивается прогресс)")
    strategy: str = Field(..., description="Стратегия прогона: fixed | structural | demo")
    status: str = Field(..., description="Статус на момент ответа")
    background: bool = Field(..., description="Выполняется ли прогон в фоне")
    metrics: Optional[Dict[str, Any]] = Field(
        None, description="Метрики: при background=false — сразу, при true — позже в отчёте"
    )
    error: Optional[str] = Field(None, description="Текст ошибки, если прогон упал")


class IndexRunOut(BaseModel):
    """Запуск индексации: стратегия, статус, счётчики, время, метрики и ошибка."""

    id: int = Field(..., description="Номер запуска")
    strategy: str = Field(..., description="Стратегия прогона: fixed | structural | demo")
    status: str = Field(
        ..., description="Этап/статус: loading | chunking | embedding | indexing | … | completed | failed"
    )
    documents_total: int = Field(0, description="Сколько документов найдено")
    documents_done: int = Field(0, description="Сколько документов обработано")
    chunks_fixed: int = Field(0, description="Сколько чанков дал fixed-чанкинг")
    chunks_structural: int = Field(0, description="Сколько чанков дал structural-чанкинг")
    embeddings_total: int = Field(0, description="Сколько эмбеддингов нужно посчитать")
    embeddings_done: int = Field(0, description="Сколько эмбеддингов посчитано")
    started_at: Optional[str] = Field(None, description="Когда прогон начался (ISO-8601, UTC)")
    finished_at: Optional[str] = Field(None, description="Когда завершился (None — идёт)")
    duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")
    embed_duration_ms: int = Field(0, description="Сколько заняли эмбеддинги")
    index_duration_ms: int = Field(0, description="Сколько заняла запись в индекс")
    metrics: Optional[Dict[str, Any]] = Field(
        None, description="Метрики сравнения стратегий (документы, запросы, статистика, время)"
    )
    error: Optional[str] = Field(None, description="Текст ошибки, если прогон упал")

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "IndexRunOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class IndexRunReportOut(BaseModel):
    """GET /indexing/runs/{id} — запуск и его метрики в одном ответе."""

    run: IndexRunOut = Field(..., description="Строка запуска")
    metrics: Dict[str, Any] = Field(
        default_factory=dict, description="Метрики прогона (пусто — метрик нет или прогон идёт)"
    )


class IndexRunsResponse(BaseModel):
    """GET /indexing/runs — история запусков индексации."""

    runs: List[IndexRunOut] = Field(default_factory=list, description="Запуски, свежие первыми")
    count: int = Field(0, description="Сколько запусков в ответе")


class IndexStatusOut(BaseModel):
    """GET /indexing/status — последний запуск (None — прогонов ещё не было)."""

    run: Optional[IndexRunOut] = Field(None, description="Последний запуск или None")


class IndexClearIn(BaseModel):
    """POST /indexing/clear — очистить индекс стратегии (или обеих)."""

    strategy: str = Field(
        ..., max_length=config.INDEX_STRATEGY_MAX,
        description="Что очистить: fixed | structural | all (обе стратегии)",
    )


class IndexClearOut(BaseModel):
    """Результат очистки: что очищено и сколько строк убрано."""

    strategy: str = Field(..., description="Что очищали")
    removed: Dict[str, int] = Field(
        default_factory=dict, description="Сколько чанков удалено по каждой стратегии"
    )


class IndexSearchOut(BaseModel):
    """GET /indexing/search — попадания поиска по индексу."""

    query: str = Field(..., description="Запрос поиска")
    strategy: str = Field(..., description="Стратегия, по которой искали")
    top_k: int = Field(..., description="Сколько попаданий запрошено")
    count: int = Field(0, description="Сколько попаданий вернулось")
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Попадания по убыванию близости: rank, chunk_id, source, title, section, "
            "strategy, score, token_count, start_char, end_char, content, preview"
        ),
    )


class IndexingReportOut(BaseModel):
    """Поле ``indexing`` ответа генерации: искал ли агент по индексу и что нашёл."""

    detected: bool = Field(..., description="Использовался ли индекс в этом ходе")
    strategy: Optional[str] = Field(None, description="Стратегия поиска (None — поиска не было)")
    hits: int = Field(0, description="Сколько фрагментов нашлось")
    used_in_prompt: bool = Field(
        False, description="Ушёл ли блок с фрагментами в системный промпт"
    )
    added_tokens: int = Field(0, description="Сколько токенов добавил блок")
    sources: List[str] = Field(
        default_factory=list, description="Документы, из которых взяты фрагменты"
    )
    error: Optional[str] = Field(None, description="Текст ошибки поиска (None — без сбоев)")
