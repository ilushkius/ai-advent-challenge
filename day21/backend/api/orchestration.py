"""Роутер API дня 20: оркестрация MCP-серверов.

Шесть эндпоинтов — запуск, история, статистика и удаление:

- ``POST /orchestration/run`` — запуск по реплике (``background=false`` — синхронно,
  с шагами в ответе; ``true`` — сразу ``running``, дальше статус опрашивается);
- ``POST /orchestration/demo`` — демонстрационный сценарий одной кнопкой: пять
  шагов по трём серверам, реплика и план берутся из домена;
- ``GET /orchestration/runs`` — история запусков (фильтр ``status``, предел
  ``limit``) плюс статистика по журналу шагов;
- ``GET /orchestration/runs/{id}`` — отчёт о запуске: статус, шаги, серверы, итог;
- ``GET /orchestration/runs/{id}/steps`` — только шаги (для прогресса в интерфейсе);
- ``DELETE /orchestration/runs/{id}`` — удалить запуск вместе с шагами.

Контракт ошибок: негодный план (не тот тип, пустые шаги, шагов больше предела,
неизвестное условие), невыполнимый сценарий (флот не публикует нужных инструментов)
и неизвестный статус в фильтре — 400; несуществующий запуск — 404; невалидное тело
— 422 (Pydantic). Отказ приходит из домена данными
(``OrchestrationRejected.reason_code``) и переводится в код здесь.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..core import config
from ..core import dependencies
from ..domain.orchestration_spec import (
    REASON_BAD_PLAN,
    REASON_BAD_QUERY,
    OrchestrationRejected,
)
from ..schemas import (
    OrchestrationDemoIn,
    OrchestrationRunIn,
    OrchestrationRunReportOut,
    OrchestrationRunsResponse,
    OrchestrationStartOut,
    OrchestrationStepsResponse,
)

router = APIRouter()

#: Коды причин, которые означают «запрос не выполним» (400), а не «не найдено» (404).
_BAD_REQUEST_REASONS = (REASON_BAD_PLAN, REASON_BAD_QUERY)


def _rejected(exc: OrchestrationRejected) -> HTTPException:
    """Переводит отказ оркестрации в HTTP-ошибку с его текстом."""
    code = 400 if exc.reason_code in _BAD_REQUEST_REASONS else 404
    return HTTPException(status_code=code, detail=exc.message)


@router.post(
    "/orchestration/run",
    response_model=OrchestrationStartOut,
    summary="Запустить оркестрацию MCP-серверов",
    description=(
        "Выполняет план шагов по флоту MCP-серверов. Без поля `plan` план строит "
        "модель DeepSeek по каталогу флота («какие инструменты с каких серверов "
        "вызвать и в каком порядке»), а если ключа нет или ответ не разобран — "
        "встроенный сценарий, отфильтрованный по доступным инструментам "
        "(`plan_source` в ответе показывает, откуда взялся план). Сервер каждого "
        "шага выбирается по имени инструмента и подключается динамически. "
        "Аргументы запуска (`query`, `limit`, `filename`, `format`) незаданные "
        "берутся из умолчаний дня. При `background=false` шаги выполняются в этом "
        "же запросе и весь отчёт возвращается сразу; при `background=true` прогон "
        "идёт в фоновом потоке, а прогресс читается через "
        "GET /orchestration/runs/{id}. Негодный план — 400."
    ),
)
def run_orchestration(body: OrchestrationRunIn) -> OrchestrationStartOut:
    """Запускает оркестрацию (в фоне или синхронно) и возвращает отчёт запуска."""
    service = dependencies.get_orchestration_service()
    try:
        report = service.start_run(
            body.query, plan=body.plan, initial_args=body.initial_args,
            background=body.background,
        )
    except OrchestrationRejected as exc:
        raise _rejected(exc) from exc
    return OrchestrationStartOut(**report)


@router.post(
    "/orchestration/demo",
    response_model=OrchestrationStartOut,
    summary="Запустить демо-сценарий оркестрации",
    description=(
        "Запускает встроенный сценарий: поиск данных на `search_server`, сводка и "
        "ключевые слова на `data_server`, файл и строка в базе на `storage_server` — "
        "пять шагов по трём серверам. План и реплика берутся из домена, поэтому "
        "кнопка «🚀 Запустить демо-сценарий» в интерфейсе, CLI-прогон и тест "
        "запускают ровно один и тот же сценарий. По умолчанию прогон идёт фоном: "
        "ответ сразу содержит `run_id`, а шаги появляются в "
        "GET /orchestration/runs/{id}. Пустой флот — 400: план демо-сценария "
        "валиден всегда, поэтому отказ приходит до создания запуска, а не падением "
        "первого шага."
    ),
)
def run_demo(body: Optional[OrchestrationDemoIn] = None) -> OrchestrationStartOut:
    """Запускает демонстрационный сценарий (в фоне или синхронно)."""
    payload = body or OrchestrationDemoIn()
    service = dependencies.get_orchestration_service()
    try:
        report = service.start_demo(background=payload.background,
                                    initial_args=payload.initial_args)
    except OrchestrationRejected as exc:
        raise _rejected(exc) from exc
    return OrchestrationStartOut(**report)


@router.get(
    "/orchestration/runs",
    response_model=OrchestrationRunsResponse,
    summary="История запусков оркестрации",
    description=(
        "Запуски от свежих к старым: номер, реплика, план, статус (`running` | "
        "`completed` | `stopped` | `failed`), метки времени, длительность и серверы. "
        "Необязательный `status` фильтрует по статусу (неизвестный статус — 400), "
        "`limit` ограничивает число записей. В ответе есть `stats`: число запусков и "
        "шагов, среднее время шага, вызовы по серверам и инструментам."
    ),
)
def list_runs(status: Optional[str] = None, limit: int = config.ORCH_RUNS_LIMIT):
    """История запусков оркестрации (свежие первыми) плюс статистика."""
    service = dependencies.get_orchestration_service()
    if status and status not in service.statuses():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Неизвестный статус запуска «{status}»; допустимы: "
                + ", ".join(sorted(service.statuses()))
            ),
        )
    return OrchestrationRunsResponse(**service.list_runs(status=status, limit=limit))


@router.get(
    "/orchestration/runs/{run_id}",
    response_model=OrchestrationRunReportOut,
    summary="Отчёт о запуске оркестрации",
    description=(
        "Строка запуска, его шаги по порядку (с сервером и инструментом каждого "
        "шага) и итог: `message` (выполнена, остановлена досрочно с сообщением "
        "условия, ошибка), `failed_at_step` и `error` — номер и текст шага, который "
        "остановил прогон, `servers_used` — серверы, которых коснулся прогон. "
        "Несуществующий запуск — 404."
    ),
)
def run_report(run_id: int):
    """Отчёт о запуске: статус, шаги, серверы, итог и причина остановки."""
    try:
        return dependencies.get_orchestration_service().report(run_id)
    except OrchestrationRejected as exc:
        raise _rejected(exc) from exc


@router.get(
    "/orchestration/runs/{run_id}/steps",
    response_model=OrchestrationStepsResponse,
    summary="Шаги запуска оркестрации",
    description=(
        "Шаги одного запуска по возрастанию номера: сервер, инструмент, аргументы "
        "вызова, результат, время выполнения, статус (`ok` | `failed` | `stopped`) и "
        "текст ошибки. Несуществующий запуск — 404."
    ),
)
def run_steps(run_id: int):
    """Шаги одного запуска (порядок выполнения)."""
    try:
        return dependencies.get_orchestration_service().steps(run_id)
    except OrchestrationRejected as exc:
        raise _rejected(exc) from exc


@router.delete(
    "/orchestration/runs/{run_id}",
    summary="Удалить запуск оркестрации",
    description=(
        "Удаляет запуск вместе с его шагами (каскад) и возвращает "
        "`{\"status\": \"deleted\", \"run_id\": …}`. Несуществующий запуск — 404."
    ),
)
def delete_run(run_id: int):
    """Удаляет запуск и его шаги."""
    try:
        return dependencies.get_orchestration_service().delete_run(run_id)
    except OrchestrationRejected as exc:
        raise _rejected(exc) from exc
