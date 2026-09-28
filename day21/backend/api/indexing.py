"""Роутер API дня 21: индексация документов и поиск по индексу.

Девять эндпоинтов — запуск, прогресс, статистика, поиск, очистка:

- ``POST /indexing/run`` — индексация документов одной стратегией;
- ``POST /indexing/demo`` — демонстрационный сценарий одной кнопкой: обе стратегии,
  пять тестовых запросов, метрики сравнения;
- ``GET /indexing/status`` — последний запуск (его опрашивает прогресс-бар);
- ``GET /indexing/stats`` — статистика обеих стратегий (для сравнения);
- ``GET /indexing/search`` — поиск по индексу (топ-k попаданий с метаданными);
- ``GET /indexing/chunks`` — примеры чанков стратегии;
- ``GET /indexing/runs`` — история запусков;
- ``GET /indexing/runs/{id}`` — отчёт о запуске вместе с метриками;
- ``POST /indexing/clear`` — очистка индекса стратегии (``all`` — обеих).

Контракт ошибок: неизвестная стратегия, пустой запрос поиска и отсутствие
документов — 400; несуществующий запуск — 404; поиск по пустому индексу — 409;
невалидное тело — 422 (Pydantic). Отказ приходит из сервиса данными
(``IndexingRejected.reason_code``) и переводится в код здесь, в одном месте.

Сбой модели эмбеддингов (нет сети, нет весов) НЕ отдаётся кодом 502: он приходит
строкой запуска со статусом ``failed`` и текстом ошибки — и при синхронном
``POST /indexing/demo`` тоже, потому что прогон создаёт строку запуска ДО работы и
обязан её закрывать.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core import config
from ..core import dependencies
from ..schemas import (
    IndexChunkListOut,
    IndexClearIn,
    IndexClearOut,
    IndexDemoIn,
    IndexRunIn,
    IndexRunReportOut,
    IndexRunsResponse,
    IndexSearchOut,
    IndexStartOut,
    IndexStatsResponse,
    IndexStatusOut,
)
from ..services.indexing_service import (
    REASON_BAD_QUERY,
    REASON_BAD_STRATEGY,
    REASON_INDEX_EMPTY,
    REASON_NO_DOCUMENTS,
    IndexingRejected,
)

router = APIRouter()

#: Коды причин, которые означают «запрос не выполним» (400), а не «не найдено» (404).
_BAD_REQUEST_REASONS = (REASON_BAD_STRATEGY, REASON_BAD_QUERY, REASON_NO_DOCUMENTS)


def _rejected(exc: IndexingRejected) -> HTTPException:
    """Переводит отказ индексации в HTTP-ошибку с его текстом."""
    if exc.reason_code in _BAD_REQUEST_REASONS:
        return HTTPException(status_code=400, detail=exc.message)
    if exc.reason_code == REASON_INDEX_EMPTY:
        return HTTPException(status_code=409, detail=exc.message)
    return HTTPException(status_code=404, detail=exc.message)


@router.post(
    "/indexing/run",
    response_model=IndexStartOut,
    summary="Индексировать документы одной стратегией",
    description=(
        "Режет документы папки `documents/` выбранной стратегией (`fixed` — окно по "
        "токенам с перекрытием, `structural` — по заголовкам markdown, секциям кода "
        "и абзацам), считает эмбеддинги и дописывает векторы в FAISS, а метаданные "
        "чанков — в таблицу `document_chunks`. Документы собираются из источников "
        "репозитория автоматически, если папки ещё нет. Повторный прогон ДОПИСЫВАЕТ "
        "индекс: чтобы перестроить его с нуля, сначала вызовите POST /indexing/clear. "
        "При `background=false` прогон идёт в этом же запросе и метрики возвращаются "
        "сразу; при `background=true` (по умолчанию) ответ содержит `run_id`, а "
        "прогресс читается через GET /indexing/status. Неизвестная стратегия — 400, "
        "нет документов — 400."
    ),
)
def run_indexing(body: IndexRunIn) -> IndexStartOut:
    """Индексирует документы одной стратегией (в фоне или синхронно)."""
    try:
        report = dependencies.get_indexing_service().start_run(
            body.strategy, background=body.background)
    except IndexingRejected as exc:
        raise _rejected(exc) from exc
    return IndexStartOut(**report)


@router.post(
    "/indexing/demo",
    summary="Запустить демо-индексацию одной кнопкой",
    description=(
        "Демонстрационный сценарий: собирает документы, строит оба индекса, "
        "выполняет пять тестовых запросов (`DEMO_QUERIES` домена с ожидаемыми "
        "источниками) на каждой стратегии и считает метрики сравнения — количество "
        "чанков, средний размер и разброс, покрытие документов, сохранение структуры, "
        "precision@k и recall@k, время индексации. Это тот же путь, что у кнопки "
        "«🚀 Запустить демо-индексацию»: реплика, запросы и набор документов берутся "
        "из домена, поэтому кнопка, CLI-прогон и тест запускают ровно один сценарий. "
        "По умолчанию прогон идёт фоном, а метрики появляются в "
        "GET /indexing/runs/{id}. Некорректные тестовые запросы — 400."
    ),
    response_model=IndexStartOut,
)
def run_demo(body: Optional[IndexDemoIn] = None) -> IndexStartOut:
    """Запускает демонстрационный сценарий индексации (в фоне или синхронно)."""
    payload = body or IndexDemoIn()
    try:
        report = dependencies.get_indexing_service().start_demo(
            background=payload.background)
    except IndexingRejected as exc:
        raise _rejected(exc) from exc
    return IndexStartOut(**report)


@router.get(
    "/indexing/status",
    response_model=IndexStatusOut,
    summary="Статус последнего прогона индексации",
    description=(
        "Последний запуск индексации: стратегия, этап (`loading` | `chunking` | "
        "`embedding` | `indexing` | `searching` | `comparing` | `completed` | "
        "`failed`), счётчики документов, чанков и эмбеддингов, метки времени и текст "
        "ошибки. По этому ответу интерфейс рисует прогресс-бар. Прогонов ещё не было "
        "— `run: null`."
    ),
)
def indexing_status() -> IndexStatusOut:
    """Статус последнего прогона (интерфейс опрашивает его во время работы)."""
    return IndexStatusOut(**dependencies.get_indexing_service().status())


@router.get(
    "/indexing/stats",
    response_model=IndexStatsResponse,
    summary="Статистика обеих стратегий",
    description=(
        "По каждой стратегии: число чанков, суммарный, средний, минимальный и "
        "максимальный размер чанка в токенах, разброс (σ), число документов и "
        "разбивка чанков по документам, число чанков с заголовком секции, "
        "гистограмма размеров и файл индекса с его объёмом. Индекс ещё не построен — "
        "нули без ошибки: интерфейсу нужна таблица и до первого прогона."
    ),
)
def indexing_stats() -> IndexStatsResponse:
    """Статистика обеих стратегий (то, что сравнивает отчёт)."""
    return IndexStatsResponse(**dependencies.get_indexing_service().stats())


@router.get(
    "/indexing/search",
    response_model=IndexSearchOut,
    summary="Поиск по индексу документов",
    description=(
        "Кодирует запрос моделью эмбеддингов и ищет ближайшие чанки по косинусной "
        "близости (векторы нормализованы, поэтому скалярное произведение равно "
        "косинусу). Каждое попадание содержит `rank`, `score`, `chunk_id`, `source`, "
        "`title`, `section`, `token_count`, границы в документе, полный `content` и "
        "короткий `preview`. `top_k` ограничен сверху `INDEX_MAX_TOP_K` (20). "
        "Пустой запрос — 400, неизвестная стратегия — 400, поиск по пустому индексу — "
        "409 (сначала выполните индексацию)."
    ),
)
def indexing_search(
    query: str,
    top_k: int = Query(config.INDEX_DEFAULT_TOP_K, ge=1, le=config.INDEX_MAX_TOP_K),
    strategy: str = config.INDEX_AGENT_STRATEGY,
) -> IndexSearchOut:
    """Поиск по индексу: попадания с метаданными чанка, по убыванию близости."""
    try:
        report = dependencies.get_indexing_service().search(query, top_k=top_k,
                                                            strategy=strategy)
    except IndexingRejected as exc:
        raise _rejected(exc) from exc
    return IndexSearchOut(**report)


@router.get(
    "/indexing/chunks",
    response_model=IndexChunkListOut,
    summary="Примеры чанков стратегии",
    description=(
        "Первые чанки стратегии из таблицы `document_chunks`: метаданные, текст и "
        "границы в исходном документе. Нужны интерфейсу и отчёту, чтобы показать, "
        "ЧЕМ отличаются стратегии на одном и том же документе. Неизвестная "
        "стратегия — 400."
    ),
)
def indexing_chunks(
    strategy: str = config.INDEX_AGENT_STRATEGY,
    limit: int = Query(config.INDEX_DEFAULT_LIMIT, ge=1),
) -> IndexChunkListOut:
    """Примеры чанков одной стратегии."""
    try:
        report = dependencies.get_indexing_service().chunks(strategy, limit=limit)
    except IndexingRejected as exc:
        raise _rejected(exc) from exc
    return IndexChunkListOut(**report)


@router.get(
    "/indexing/runs",
    response_model=IndexRunsResponse,
    summary="История запусков индексации",
    description=(
        "Запуски от свежих к старым: стратегия (`fixed` | `structural` | `demo`), "
        "этап/статус, счётчики, метки времени, длительности, метрики и текст ошибки. "
        "`limit` ограничивает число записей."
    ),
)
def indexing_runs(limit: int = Query(config.INDEX_RUNS_LIMIT, ge=1)) -> IndexRunsResponse:
    """История запусков индексации (свежие первыми)."""
    return IndexRunsResponse(**dependencies.get_indexing_service().runs(limit=limit))


@router.get(
    "/indexing/runs/{run_id}",
    response_model=IndexRunReportOut,
    summary="Отчёт о запуске индексации",
    description=(
        "Строка запуска и его метрики: документы, метрики обеих стратегий "
        "(`stats`, `coverage`, `structure`, `search`, `timing`), результаты пяти "
        "тестовых запросов и таблица сравнения. Несуществующий запуск — 404."
    ),
)
def indexing_run_report(run_id: int) -> IndexRunReportOut:
    """Отчёт о запуске: строка запуска и метрики."""
    try:
        return IndexRunReportOut(**dependencies.get_indexing_service().run(run_id))
    except IndexingRejected as exc:
        raise _rejected(exc) from exc


@router.post(
    "/indexing/clear",
    response_model=IndexClearOut,
    summary="Очистить индекс",
    description=(
        "Убирает индекс стратегии: векторы из памяти, файл `index/<стратегия>.index` "
        "и строки `document_chunks`. `strategy: \"all\"` очищает обе стратегии. "
        "Нужно перед переиндексацией изменённых документов: обычный прогон индекс "
        "ДОПИСЫВАЕТ, а не перестраивает. Неизвестная стратегия — 400."
    ),
)
def indexing_clear(body: IndexClearIn) -> IndexClearOut:
    """Очищает индекс одной стратегии или обеих."""
    try:
        return IndexClearOut(**dependencies.get_indexing_service().clear(body.strategy))
    except IndexingRejected as exc:
        raise _rejected(exc) from exc
