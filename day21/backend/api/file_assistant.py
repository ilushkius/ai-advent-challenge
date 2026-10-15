"""Роутер API: ассистент файлов (день 34) — ``/file-assistant/*``.

Три эндпоинта, по одному на вопрос раздела интерфейса:

- ``POST /file-assistant/execute`` — прогон цели. ``400`` — пустая цель или незнакомый
  провайдер (``ValueError`` службы); ``422`` — план негоден, в ``detail`` лежат
  ``problems`` (что именно не так) и ``raw`` (сырой ответ модели); ``500`` — модель
  недоступна или MCP-сервер файлов не поднялся: прогон без плана показывать нечего;
- ``GET /file-assistant/history`` — история запусков, всегда ``200``: пусто — это
  ``count: 0``, а не ошибка;
- ``GET /file-assistant/diff/{run_id}`` — diff одного запуска; ``404`` — такого запуска
  нет (``FileAssistantRunNotFoundError`` хранилища).

Схемы берутся из своего модуля (``..schemas.file_assistant``), а не из пакета
``..schemas``: ``schemas/__init__.py`` стоит на пределе 400 строк, и дни 30–33 сделали
так же. Служба — через ``backend.core.dependencies``, то есть по атрибуту
``backend.api.main`` в момент вызова: тесты подменяют одну точку
(``main.get_file_assistant_service``), и подмену видят и роутер, и ``lifespan``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..domain.file_assistant import HISTORY_LIMIT, PlanRejected
from ..schemas.file_assistant import (
    FileAssistantDiffOut,
    FileAssistantExecuteIn,
    FileAssistantHistoryOut,
    FileAssistantRunOut,
)
from ..services.file_assistant_service import FileAssistantError
from ..services.file_mcp import FileMCPError
from ..storage.file_assistant_store import FileAssistantRunNotFoundError

router = APIRouter()


def _error(exc: Exception) -> HTTPException:
    """Доменное исключение дня 34 в HTTP-ответ: 400 — запрос, 500 — сбой прогона."""
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/file-assistant/execute", response_model=FileAssistantRunOut)
def execute_goal(payload: FileAssistantExecuteIn) -> FileAssistantRunOut:
    """Прогон цели ассистентом файлов: план, шаги, diff и сводка.

    Требует ``DEEPSEEK_API_KEY`` (или запущенной Ollama для ``provider="local"``):
    прогон начинается с плана шагов, и без модели исполнять нечего.

    Коды: ``400`` — цель пуста или провайдер неизвестен; ``422`` — план не разобран
    или нарушает правила (в ``detail`` — ``problems`` и ``raw``); ``500`` — сбой
    вызова модели или MCP-сервера файлов.
    """
    service = dependencies.get_file_assistant_service()
    try:
        result = service.execute_goal(payload.goal, payload.provider, payload.dry_run)
    except PlanRejected as exc:
        raise HTTPException(status_code=422, detail={"problems": exc.problems,
                                                    "raw": exc.raw}) from exc
    except (FileAssistantError, FileMCPError, ValueError) as exc:
        raise _error(exc) from exc
    return FileAssistantRunOut(**result)


@router.get("/file-assistant/history", response_model=FileAssistantHistoryOut)
def read_history(limit: int = HISTORY_LIMIT) -> FileAssistantHistoryOut:
    """История запусков от свежих к старым (всегда 200, ``diff`` в список не входит)."""
    return FileAssistantHistoryOut(**dependencies.get_file_assistant_service().history(limit))


@router.get("/file-assistant/diff/{run_id}", response_model=FileAssistantDiffOut)
def read_diff(run_id: int) -> FileAssistantDiffOut:
    """Diff и файлы одного запуска (404 — запуска с таким id нет)."""
    try:
        result = dependencies.get_file_assistant_service().diff_of(run_id)
    except FileAssistantRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileAssistantDiffOut(**result)
