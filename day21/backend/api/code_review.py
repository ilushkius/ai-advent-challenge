"""Роутер API: AI-ревью PR (день 32) — ``/review/pr`` и ``/review/health``.

Первый эндпоинт принимает либо готовый ``diff`` со списком файлов, либо пару
``base``/``head``: во втором случае diff и имена файлов приходят из MCP-инструментов
dev-сервера (``get_pr_diff``, ``get_changed_files``). Дальше служба подтягивает
контекст корпуса RAG (документация проекта и код изменённых файлов), зовёт модель по
JSON-контракту и отдаёт структуру: баги, архитектурные проблемы, рекомендации и риски
P0–P3. Второй эндпоинт — готовность службы: провайдер по умолчанию, инструменты,
предел diff-а; он не ходит ни в MCP, ни в индекс.

Пути абсолютные (префиксов у роутеров дня нет), служба берётся вызовом
``dependencies.get_code_review_service()`` — не прямым импортом: тесты подменяют её
одной строкой в ``backend.api.main``.

Коды ответов: 400 — нет diff-а и нет пары ``base``/``head``, пустой полученный diff
или незнакомый провайдер; 422 — невалидное тело запроса; 502 — MCP-сервер разработки
не поднялся, и diff не добыть.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import dependencies
# Схемы берутся из своего модуля, а не из пакета ``..schemas``: ``schemas/__init__.py``
# стоит на пределе 400 строк, и дни 30–31 сделали так же.
from ..schemas.code_review import CodeReviewHealthOut, PrReviewIn, PrReviewOut
from ..services.code_review_service import CodeReviewError
from ..services.rag_errors import RAGUpstreamError

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    """Доменное исключение ревью в HTTP-ответ: 400 — запрос, 502 — сбой MCP."""
    if isinstance(exc, ValueError):
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
