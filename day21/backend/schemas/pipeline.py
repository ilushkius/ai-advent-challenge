"""Pydantic-схемы API пайплайна (день 19).

Схемы повторяют форму словарей из хранилища и сервиса (``pipeline_rows.py``,
``services/pipeline_service.py``), поэтому роутер не переупаковывает данные, а
только объявляет контракт: запуск (``PipelineRunOut``), шаг (``PipelineStepOut``),
отчёт о запуске (``PipelineRunReportOut``) и отчёт о шаге агента
(``PipelineReportOut`` — поле ``pipeline`` ответа генерации).

``PipelineRunIn`` принимает декларативную конфигурацию целиком: без поля
``pipeline`` выполняется встроенный пайплайн
(``domain/pipeline_spec.DEFAULT_PIPELINE``), поэтому «запусти как обычно» — это
запрос с одними ``initial_args``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineRunIn(BaseModel):
    """POST /pipelines/run — что запустить и с какими аргументами."""

    pipeline: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Декларативная конфигурация пайплайна: name и steps (tool, args, guard). "
            "Без неё — встроенный пайплайн search → summarize → save_to_file"
        ),
    )
    initial_args: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Начальные аргументы запуска: query, source, limit, style, max_length, "
            "filename, format"
        ),
    )
    background: bool = Field(
        True,
        description=(
            "true — запуск в фоновом потоке (статус опрашивается через "
            "GET /pipelines/runs/{id}), false — синхронно и сразу с отчётом о шагах"
        ),
    )


class PipelineStepOut(BaseModel):
    """Шаг запуска: инструмент, вход, выход, время, статус и текст ошибки."""

    id: int = Field(..., description="Номер строки журнала")
    run_id: int = Field(..., description="Запуск, к которому относится шаг")
    step_index: int = Field(..., description="Номер шага в конфигурации (с нуля)")
    tool_name: str = Field(..., description="Инструмент шага: search | summarize | save_to_file")
    input_args: Dict[str, Any] = Field(
        default_factory=dict, description="Аргументы вызова (ссылки пайплайна уже разрешены)"
    )
    output_result: Optional[Dict[str, Any]] = Field(
        None, description="Результат шага: structured, text, reason_code, is_error, duration_ms"
    )
    duration_ms: int = Field(0, description="Сколько миллисекунд занял шаг")
    status: str = Field(..., description="Статус шага: ok | failed | stopped")
    error_message: Optional[str] = Field(
        None, description="Почему шаг не выполнился (или сообщение условия перехода)"
    )

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "PipelineStepOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class PipelineRunOut(BaseModel):
    """Запуск пайплайна: имя конфигурации, статус, метки времени и длительность."""

    id: int = Field(..., description="Номер запуска")
    pipeline_name: str = Field(..., description="Имя конфигурации пайплайна")
    status: str = Field(
        ..., description="Статус запуска: running | completed | stopped | failed"
    )
    started_at: Optional[str] = Field(None, description="Когда запуск начался (ISO-8601, UTC)")
    finished_at: Optional[str] = Field(None, description="Когда завершился (None — идёт)")
    total_duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "PipelineRunOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class PipelineStartOut(BaseModel):
    """Ответ запуска: он же первый ответ опроса для фонового прогона."""

    run_id: int = Field(..., description="Номер запуска (им опрашивается статус)")
    pipeline_name: str = Field(..., description="Имя конфигурации пайплайна")
    status: str = Field(..., description="Статус на момент ответа")
    steps: List[PipelineStepOut] = Field(
        default_factory=list, description="Шаги: при background=false — все, при true — пусто"
    )
    count: int = Field(0, description="Сколько шагов в ответе")
    failed_at_step: Optional[int] = Field(
        None, description="Номер шага, на котором прогон остановился (None — не останавливался)"
    )
    message: str = Field("", description="Итог или сообщение условия перехода")
    error: Optional[str] = Field(None, description="Текст ошибки остановившего шага")
    total_duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")
    background: bool = Field(..., description="Выполняется ли прогон в фоне")


class PipelineRunReportOut(BaseModel):
    """GET /pipelines/runs/{id} — запуск, его шаги и итог."""

    run: PipelineRunOut = Field(..., description="Строка запуска")
    steps: List[PipelineStepOut] = Field(default_factory=list, description="Шаги по порядку")
    count: int = Field(0, description="Сколько шагов записано")
    failed_at_step: Optional[int] = Field(None, description="Номер шага с ошибкой")
    message: str = Field("", description="Итог: выполнен, остановлен досрочно, ошибка")
    error: Optional[str] = Field(None, description="Текст ошибки шага")


class PipelineRunsResponse(BaseModel):
    """GET /pipelines/runs — история запусков."""

    runs: List[PipelineRunOut] = Field(default_factory=list, description="Запуски, свежие первыми")
    count: int = Field(0, description="Сколько запусков в ответе")


class PipelineStepsResponse(BaseModel):
    """GET /pipelines/runs/{id}/steps — шаги одного запуска."""

    run_id: int = Field(..., description="Номер запуска")
    steps: List[PipelineStepOut] = Field(default_factory=list, description="Шаги по порядку")
    count: int = Field(0, description="Сколько шагов записано")


class PipelineReportOut(BaseModel):
    """Поле ``pipeline`` ответа генерации: запускался ли пайплайн и чем закончился."""

    detected: bool = Field(..., description="Распознала ли эвристика пайплайн в реплике")
    run_id: Optional[int] = Field(None, description="Номер запуска (None — не запускался)")
    status: str = Field("", description="Статус прогона")
    message: str = Field("", description="Итог прогона или сообщение условия перехода")
    failed_at_step: Optional[int] = Field(None, description="Номер шага с ошибкой")
    error: Optional[str] = Field(None, description="Текст ошибки шага")
    steps: List[PipelineStepOut] = Field(default_factory=list, description="Шаги прогона")
    count: int = Field(0, description="Сколько шагов записано")
    total_duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")
    used_in_prompt: bool = Field(
        False, description="Ушёл ли результат прогона в системный промпт этого запроса"
    )
    added_tokens: int = Field(0, description="Сколько токенов добавил блок результата")
