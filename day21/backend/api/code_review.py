"""Роутер API: AI-ревью PR (день 32) — ``/review/pr``, ``/review/health``,
``/review/github-pr`` и ``/review/github-health``.

Первый эндпоинт принимает либо готовый ``diff`` со списком файлов, либо пару
``base``/``head``: во втором случае diff и имена файлов приходят из MCP-инструментов
dev-сервера (``get_pr_diff``, ``get_changed_files``). Дальше служба подтягивает
контекст корпуса RAG (документация проекта и код изменённых файлов), зовёт модель по
JSON-контракту и отдаёт структуру: баги, архитектурные проблемы, рекомендации и риски
P0–P3. Второй эндпоинт — готовность службы: провайдер по умолчанию, инструменты,
предел diff-а; он не ходит ни в MCP, ни в индекс.

Третий эндпоинт — тот же ревью, но diff и список файлов берутся из GitHub REST API по
URL репозитория и номеру PR, а по флагу ``post_comment`` готовое ревью публикуется
комментарием в PR; четвёртый — готовность GitHub (доступность API, признак токена,
остаток лимита).

Пути абсолютные (префиксов у роутеров дня нет), служба берётся вызовом
``dependencies.get_code_review_service()`` — не прямым импортом: тесты подменяют её
одной строкой в ``backend.api.main``.

Коды ответов: 400 — нет diff-а и нет пары ``base``/``head``, пустой полученный diff,
незнакомый провайдер, негодный URL репозитория, не найденные репозиторий или PR,
исчерпанный rate limit GitHub; 422 — невалидное тело запроса; 502 — MCP-сервер
разработки не поднялся, и diff не добыть (GitHub-путь 502 не отдаёт).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import dependencies
# Схемы берутся из своего модуля, а не из пакета ``..schemas``: ``schemas/__init__.py``
# стоит на пределе 400 строк, и дни 30–31 сделали так же.
from ..schemas.code_review import (CodeReviewHealthOut, GitHubHealthOut, GitHubPrReviewIn,
                                   GitHubPrReviewOut, PrReviewIn, PrReviewOut)
from ..services.code_review_service import CodeReviewError
from ..services.github_client import GitHubError
from ..services.rag_errors import RAGUpstreamError

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    """Доменное исключение ревью в HTTP-ответ: 400 — запрос или GitHub, 502 — сбой MCP."""
    if isinstance(exc, (ValueError, GitHubError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.post(
    "/review/pr",
    response_model=PrReviewOut,
    summary="AI-ревью изменений PR",
    description=(
        "Принимает diff и список изменённых файлов (или пару ``base``/``head`` — тогда "
        "и то и другое возвращает MCP-сервер разработки). Подтягивает контекст: "
        "фрагменты документации проекта и кода изменённых файлов из RAG-индекса корпуса, "
        "diff обрезается до 2000 строк. Модель отвечает по JSON-контракту, ответ "
        "разбирается в баги, архитектурные проблемы, рекомендации и риски P0–P3. "
        "400: нет diff-а и нет ref-ов, пустой diff или незнакомый провайдер. "
        "502: MCP-сервер не поднялся, и diff не добыть."
    ),
)
def review_pr(payload: PrReviewIn) -> PrReviewOut:
    """Ревью PR: структура находок, источники RAG и предупреждения шагов."""
    service = dependencies.get_code_review_service()
    try:
        result = service.review_pr(payload.model_dump(), payload.provider)
    except (ValueError, CodeReviewError, RAGUpstreamError) as exc:
        raise _http_error(exc) from exc
    return PrReviewOut(**result)


@router.post(
    "/review/github-pr",
    response_model=GitHubPrReviewOut,
    summary="AI-ревью PR из GitHub по URL и номеру",
    description=(
        "Ревью реального PR: ``repo_url`` и ``pr_number`` обязательны, diff и список "
        "изменённых файлов берутся из GitHub REST API, контекст — из корпуса RAG "
        "(документация проекта и код изменённых файлов). Флаг ``post_comment=true`` "
        "публикует готовое ревью комментарием в PR (нужен ``GITHUB_TOKEN`` с правом на "
        "запись). 400: негодный URL репозитория, репозиторий или PR не найдены, "
        "исчерпан rate limit GitHub, незнакомый провайдер, пустой diff. 502: прочие "
        "отказы MCP-пути. Отказ публикации комментария не отменяет ревью: ответ "
        "приходит с 200, ``posted=false`` и предупреждением в ``warnings``."
    ),
)
def review_github_pr(payload: GitHubPrReviewIn) -> GitHubPrReviewOut:
    """Ревью реального PR: diff и файлы из GitHub REST API, публикация по флагу."""
    service = dependencies.get_code_review_service()
    try:
        result = service.review_github_pr(payload.repo_url, payload.pr_number,
                                         payload.provider, payload.post_comment)
    except (ValueError, GitHubError, CodeReviewError, RAGUpstreamError) as exc:
        raise _http_error(exc) from exc
    return GitHubPrReviewOut(**result)


@router.get(
    "/review/health",
    response_model=CodeReviewHealthOut,
    summary="Готовность службы AI-ревью",
    description=(
        "Отдаёт конфигурацию службы ревью: провайдер ответа по умолчанию, список "
        "доступных провайдеров, инструменты MCP, которыми ревью пользуется, стратегию "
        "поиска по корпусу и предел diff-а в промпте. Всегда 200: MCP и индекс здесь не "
        "трогаются — эндпоинт нужен для мониторинга и проверки перед запросом ревью."
    ),
)
def review_health() -> CodeReviewHealthOut:
    """Готовность сервиса ревью: провайдер, инструменты MCP, предел diff-а."""
    return CodeReviewHealthOut(**dependencies.get_code_review_service().health())


@router.get(
    "/review/github-health",
    response_model=GitHubHealthOut,
    summary="Готовность GitHub-режима ревью",
    description=(
        "Ходит в ``GET /rate_limit``: доступность API, есть ли токен (маска), сколько "
        "запросов осталось. Всегда 200: недоступность GitHub отдаётся "
        "``status=\"degraded\"`` и полем ``error``."
    ),
)
def review_github_health() -> GitHubHealthOut:
    """Доступность GitHub API, признак токена и остаток лимита (всегда 200)."""
    return GitHubHealthOut(**dependencies.get_code_review_service().github_health())
