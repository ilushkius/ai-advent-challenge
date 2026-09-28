"""Pydantic-схемы API оркестрации (день 20).

Схемы повторяют форму словарей из хранилища и сервиса (``orchestration_rows.py``,
``services/orchestration_service.py``), поэтому роутер не переупаковывает данные, а
только объявляет контракт: запуск (``OrchestrationRunOut``), шаг
(``OrchestrationStepOut``), отчёт о запуске (``OrchestrationRunReportOut``) и отчёт
о шаге агента (``OrchestrationReportOut`` — поле ``orchestration`` ответа генерации).

``OrchestrationRunIn`` принимает план целиком: без поля ``plan`` оркестратор строит
его сам (моделью, а без ключа — эвристикой), поэтому «выполни это по серверам» —
это запрос с одной ``query``. В отличие от шага пайплайна, у шага оркестрации есть
``server_name``: по нему видно, какой сервер флота получил вызов.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core import config


class OrchestrationRunIn(BaseModel):
    """POST /orchestration/run — что выполнить и каким планом."""

    query: str = Field(
        ..., min_length=1, max_length=config.ORCH_QUERY_MAX,
        description="Реплика-запрос: по ней строится план и подставляются аргументы запуска",
    )
    background: bool = Field(
        True,
        description=(
            "true — запуск в фоновом потоке (статус опрашивается через "
            "GET /orchestration/runs/{id}), false — синхронно и сразу с отчётом о шагах"
        ),
    )
    plan: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "План шагов: name и steps (tool, args, необязательный guard). Без него "
            "план строит модель по каталогу флота, а при её недоступности — встроенный "
            "сценарий из домена"
        ),
    )
    initial_args: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Аргументы запуска: query, limit, filename, format. Незаданные берутся "
            "из умолчаний дня, поэтому {limit}/{filename} в плане не остаются пустыми"
        ),
    )


class OrchestrationDemoIn(BaseModel):
    """POST /orchestration/demo — запуск демонстрационного сценария одной репликой."""

    background: bool = Field(
        True,
        description=(
            "true — прогон в фоновом потоке (кнопка «🚀 Запустить демо-сценарий» "
            "сразу получает id и опрашивает шаги), false — синхронно"
        ),
    )
    initial_args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Переопределения аргументов запуска (query, limit, filename, format)",
    )


class OrchestrationStepOut(BaseModel):
    """Шаг запуска: сервер, инструмент, вход, выход, время, статус и текст ошибки."""

    id: int = Field(..., description="Номер строки журнала")
    run_id: int = Field(..., description="Запуск, к которому относится шаг")
    step_index: int = Field(..., description="Номер шага в плане (с нуля)")
    server_name: str = Field(
        ..., description="Сервер флота, получивший вызов (пусто — шаг не дошёл до сервера)"
    )
    tool_name: str = Field(..., description="Имя инструмента шага")
    input_args: Dict[str, Any] = Field(
        default_factory=dict, description="Аргументы вызова (ссылки плана уже разрешены)"
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
    def from_row(cls, row: Dict[str, Any]) -> "OrchestrationStepOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class OrchestrationRunOut(BaseModel):
    """Запуск оркестрации: запрос, план, статус, метки времени и серверы."""

    id: int = Field(..., description="Номер запуска")
    query: str = Field(..., description="Реплика-запрос запуска")
    plan: Dict[str, Any] = Field(
        default_factory=dict, description="План шагов целиком (name, steps, source)"
    )
    status: str = Field(
        ..., description="Статус запуска: running | completed | stopped | failed"
    )
    started_at: Optional[str] = Field(None, description="Когда запуск начался (ISO-8601, UTC)")
    finished_at: Optional[str] = Field(None, description="Когда завершился (None — идёт)")
    total_duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")
    servers_used: List[str] = Field(
        default_factory=list, description="Серверы, до которых дошёл прогон (по порядку)"
    )

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "OrchestrationRunOut":
        """Схема из словаря хранилища."""
        return cls(**row)


class OrchestrationStartOut(BaseModel):
    """Ответ запуска: он же первый ответ опроса для фонового прогона."""

    run_id: int = Field(..., description="Номер запуска (им опрашивается статус)")
    query: str = Field(..., description="Реплика-запрос")
    status: str = Field(..., description="Статус на момент ответа")
    plan: Dict[str, Any] = Field(
        default_factory=dict, description="План, который выполняется (с полем source)"
    )
    plan_source: str = Field(
        "", description="Откуда план: given (пришёл в запросе) | llm (предложила модель) | heuristic"
    )
    steps: List[OrchestrationStepOut] = Field(
        default_factory=list, description="Шаги: при background=false — все, при true — пусто"
    )
    count: int = Field(0, description="Сколько шагов в ответе")
    servers_used: List[str] = Field(default_factory=list, description="Серверы прогона")
    failed_at_step: Optional[int] = Field(
        None, description="Номер шага, на котором прогон остановился (None — не останавливался)"
    )
    message: str = Field("", description="Итог или сообщение условия перехода")
    error: Optional[str] = Field(None, description="Текст ошибки остановившего шага")
    total_duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")
    background: bool = Field(..., description="Выполняется ли прогон в фоне")


class OrchestrationRunReportOut(BaseModel):
    """GET /orchestration/runs/{id} — запуск, его шаги, серверы и итог."""

    run: OrchestrationRunOut = Field(..., description="Строка запуска")
    steps: List[OrchestrationStepOut] = Field(default_factory=list, description="Шаги по порядку")
    count: int = Field(0, description="Сколько шагов записано")
    servers_used: List[str] = Field(default_factory=list, description="Серверы прогона")
    failed_at_step: Optional[int] = Field(None, description="Номер шага с ошибкой")
    message: str = Field("", description="Итог: выполнена, остановлена досрочно, ошибка")
    error: Optional[str] = Field(None, description="Текст ошибки шага")


class OrchestrationRunsResponse(BaseModel):
    """GET /orchestration/runs — история запусков и статистика по журналу."""

    runs: List[OrchestrationRunOut] = Field(
        default_factory=list, description="Запуски, свежие первыми"
    )
    count: int = Field(0, description="Сколько запусков в ответе")
    stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Статистика: runs, steps, avg_step_ms, servers (calls, avg_ms), tools (calls)",
    )


class OrchestrationStepsResponse(BaseModel):
    """GET /orchestration/runs/{id}/steps — шаги одного запуска."""

    run_id: int = Field(..., description="Номер запуска")
    steps: List[OrchestrationStepOut] = Field(default_factory=list, description="Шаги по порядку")
    count: int = Field(0, description="Сколько шагов записано")


class OrchestrationReportOut(BaseModel):
    """Поле ``orchestration`` ответа генерации: запускалась ли оркестрация и чем кончилась."""

    detected: bool = Field(..., description="Распознала ли эвристика оркестрацию в реплике")
    run_id: Optional[int] = Field(None, description="Номер запуска (None — не запускалась)")
    status: str = Field("", description="Статус прогона")
    message: str = Field("", description="Итог прогона или сообщение условия перехода")
    plan_source: str = Field("", description="Откуда взялся план: given | llm | heuristic")
    servers_used: List[str] = Field(default_factory=list, description="Серверы, которых коснулся прогон")
    tools_used: List[str] = Field(default_factory=list, description="Инструменты шагов по порядку")
    steps: List[OrchestrationStepOut] = Field(default_factory=list, description="Шаги прогона")
    count: int = Field(0, description="Сколько шагов записано")
    failed_at_step: Optional[int] = Field(None, description="Номер шага с ошибкой")
    error: Optional[str] = Field(None, description="Текст ошибки шага")
    total_duration_ms: int = Field(0, description="Длительность прогона в миллисекундах")
    used_in_prompt: bool = Field(
        False, description="Ушёл ли результат прогона в системный промпт этого запроса"
    )
    added_tokens: int = Field(0, description="Сколько токенов добавил блок результата")
