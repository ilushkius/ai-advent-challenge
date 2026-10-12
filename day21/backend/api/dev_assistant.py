"""Роутер API: ассистент разработчика (день 31) — ``/help``, инструменты, git-контекст.

Три эндпоинта одного раздела: вопрос по документации и репозиторию, каталог
инструментов dev-сервера и состояние git. Пути абсолютные (префиксов у роутеров дня
нет), служба берётся через ``dependencies.get_dev_assistant_service()`` — не прямой
импорт: тесты подменяют её одной строкой в ``backend.api.main``.

Коды ответов: 400 — пустой вопрос (после снятия «/help») или незнакомый провайдер,
502 — сбой модели, когда ни один источник не собрал контекст. Панели раздела
(``tools``, ``git-context``) отвечают 200 всегда: недоступный MCP-сервер — это
строка ``error`` в теле, а не отказ страницы.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import dependencies
# Схемы берутся из своего модуля, а не из пакета ``..schemas``: ``schemas/__init__.py``
# стоит на пределе 400 строк, и день 30 сделал так же для ``schemas/remote_llm.py``.
from ..schemas.dev_assistant import (
    DevAssistantAnswerOut,
    DevAssistantGitContextOut,
    DevAssistantHelpIn,
    DevAssistantToolsOut,
)
from ..services.rag_errors import RAGUpstreamError

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    """Доменное исключение ассистента в HTTP-ответ: 400 — запрос, 502 — сбой модели."""
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.post(
    "/dev-assistant/help",
    response_model=DevAssistantAnswerOut,
    summary="Ответ ассистента разработчика (/help)",
    description=(
        "Собирает контекст вопроса из двух источников: фрагменты документации "
        "проекта (RAG-индекс корпуса) и ответы инструментов MCP-сервера разработки "
        "(ветка, коммит, изменённые файлы, diff, структура). Тип вопроса (docs, git, "
        "mixed) выбирает, нужны ли инструменты. Ответ содержит источники, вызовы "
        "инструментов и предупреждения отказов; недоступная модель возвращается "
        "честным текстом в поле answer, 502 — только когда ни одного блока контекста "
        "собрать не удалось. 400: пустой вопрос или незнакомый провайдер."
    ),
)
def ask_help(payload: DevAssistantHelpIn) -> DevAssistantAnswerOut:
    """Ответ на вопрос ``/help``: текст, источники RAG и использованные MCP-инструменты."""
    service = dependencies.get_dev_assistant_service()
    try:
        result = service.handle_help(payload.question, payload.provider)
    except (ValueError, RAGUpstreamError) as exc:
        raise _http_error(exc) from exc
    return DevAssistantAnswerOut(**result)


@router.get(
    "/dev-assistant/tools",
    response_model=DevAssistantToolsOut,
    summary="Инструменты MCP-сервера разработки",
    description=(
        "Каталог четырёх инструментов сервера ``mcp_servers/dev_server`` с их "
        "схемами аргументов и результата. Пустой каталог с заполненным полем "
        "``error`` означает, что сервер не поднялся: раздел показывает причину."
    ),
)
def read_tools() -> DevAssistantToolsOut:
    """Каталог инструментов dev-сервера (всегда 200, причина отказа — в поле error)."""
    service = dependencies.get_dev_assistant_service()
    return DevAssistantToolsOut(**service.tools())


@router.get(
    "/dev-assistant/git-context",
    response_model=DevAssistantGitContextOut,
    summary="Ветка, коммит и изменённые файлы (MCP)",
    description=(
        "Вызывает ``get_git_branch`` сервера разработки напрямую — панель «🌱 Git» "
        "раздела видит состояние репозитория, не задавая вопрос модели. Всегда 200: "
        "недоступный сервер заполняет поле ``error``, а поля состояния остаются "
        "пустыми."
    ),
)
def read_git_context() -> DevAssistantGitContextOut:
    """Состояние репозитория по инструменту ``get_git_branch`` (всегда 200)."""
    service = dependencies.get_dev_assistant_service()
    return DevAssistantGitContextOut(**service.git_context())
