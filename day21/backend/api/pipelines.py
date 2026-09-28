"""Роутер API дня 19: декларативный пайплайн MCP-инструментов.

Пять эндпоинтов — запуск и история:

- ``POST /pipelines/run`` — запуск (``background=false`` — синхронно, с шагами в
  ответе; ``true`` — сразу ``running``, дальше статус опрашивается);
- ``GET /pipelines/runs`` — история запусков (фильтр ``status``, предел ``limit``);
- ``GET /pipelines/runs/{id}`` — отчёт о запуске: статус, шаги, итог, ошибка;
- ``GET /pipelines/runs/{id}/steps`` — только шаги (для интерфейса прогресса);
- ``DELETE /pipelines/runs/{id}`` — удалить запуск вместе с шагами.

Контракт ошибок: негодная конфигурация пайплайна (не тот тип, пустые шаги, шагов
больше предела, неизвестное условие) и неизвестный статус в фильтре — 400;
несуществующий запуск — 404; невалидное тело — 422 (Pydantic). Отказ приходит из
домена данными (``PipelineRejected.reason_code``) и переводится в код здесь.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..core import config
from ..core import dependencies
from ..domain.pipeline_spec import REASON_BAD_CONFIG, PipelineRejected
from ..schemas import (
    PipelineRunIn,
    PipelineRunReportOut,
    PipelineRunsResponse,
    PipelineStartOut,
    PipelineStepsResponse,
)

router = APIRouter()


def _rejected(exc: PipelineRejected) -> HTTPException:
    """Переводит отказ пайплайна в HTTP-ошибку с его текстом."""
    code = 400 if exc.reason_code == REASON_BAD_CONFIG else 404
    return HTTPException(status_code=code, detail=exc.message)


@router.post(
    "/pipelines/run",
    response_model=PipelineStartOut,
    summary="Запустить пайплайн MCP-инструментов",
    description=(
        "Запускает декларативный пайплайн: шаги описаны данными (`pipeline`), "
        "аргументы запуска — `initial_args` (query, source, limit, style, "
        "max_length, filename, format). Без поля `pipeline` выполняется встроенный "
        "пайплайн search → summarize → save_to_file. При `background=false` шаги "
        "выполняются в этом же запросе и весь отчёт возвращается сразу; при "
        "`background=true` прогон идёт в фоновом потоке, ответ приходит со "
        "статусом `running`, а прогресс читается через GET /pipelines/runs/{id}. "
        "Негодная конфигурация — 400."
    ),
)
def run_pipeline(body: PipelineRunIn) -> PipelineStartOut:
    """Запускает пайплайн (в фоне или синхронно) и возвращает отчёт запуска."""
    service = dependencies.get_pipeline_service()
    try:
        report = service.start_pipeline(
            body.pipeline, body.initial_args, background=body.background
        )
    except PipelineRejected as exc:
        raise _rejected(exc) from exc
    return PipelineStartOut(**report)


@router.get(
    "/pipelines/runs",
    response_model=PipelineRunsResponse,
    summary="История запусков пайплайна",
    description=(
        "Запуски от свежих к старым: номер, имя конфигурации, статус "
        "(`running` | `completed` | `stopped` | `failed`), метки времени и "
        "длительность. Необязательный `status` фильтрует по статусу "
        "(неизвестный статус — 400), `limit` ограничивает число записей."
    ),
)
def list_runs(status: Optional[str] = None, limit: int = config.PIPELINE_RUNS_LIMIT):
    """История запусков пайплайна (свежие первыми)."""
    service = dependencies.get_pipeline_service()
    if status and status not in service.statuses():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Неизвестный статус запуска «{status}»; допустимы: "
                + ", ".join(sorted(service.statuses()))
            ),
        )
    return PipelineRunsResponse(**service.list_runs(status=status, limit=limit))


@router.get(
    "/pipelines/runs/{run_id}",
    response_model=PipelineRunReportOut,
    summary="Отчёт о запуске пайплайна",
    description=(
        "Строка запуска, его шаги по порядку и итог: `message` (выполнен, "
        "остановлен досрочно с сообщением условия, ошибка), `failed_at_step` и "
        "`error` — номер и текст шага, который остановил прогон. Несуществующий "
        "запуск — 404."
    ),
)
def run_report(run_id: int):
    """Отчёт о запуске: статус, шаги, итог и причина остановки."""
    try:
        return dependencies.get_pipeline_service().report(run_id)
    except PipelineRejected as exc:
        raise _rejected(exc) from exc


@router.get(
    "/pipelines/runs/{run_id}/steps",
    response_model=PipelineStepsResponse,
    summary="Шаги запуска пайплайна",
    description=(
        "Шаги одного запуска по возрастанию номера: инструмент, аргументы вызова, "
        "результат, время выполнения, статус (`ok` | `failed` | `stopped`) и текст "
        "ошибки. Несуществующий запуск — 404."
    ),
)
def run_steps(run_id: int):
    """Шаги одного запуска (порядок выполнения)."""
    try:
        return dependencies.get_pipeline_service().steps(run_id)
    except PipelineRejected as exc:
        raise _rejected(exc) from exc


@router.delete(
    "/pipelines/runs/{run_id}",
    summary="Удалить запуск пайплайна",
    description=(
        "Удаляет запуск вместе с его шагами (каскад) и возвращает "
        "`{\"status\": \"deleted\", \"run_id\": …}`. Несуществующий запуск — 404."
    ),
)
def delete_run(run_id: int):
    """Удаляет запуск и его шаги."""
    try:
        return dependencies.get_pipeline_service().delete_run(run_id)
    except PipelineRejected as exc:
        raise _rejected(exc) from exc
