"""Тестовые запросы демонстрации индексации и их проверка (день 21).

Чтобы «сравнить стратегии» было не только по объёмам, нужен ground truth: пять
запросов и ожидаемые источники ответа (имена файлов в ``documents/``). Запросы —
данные, а не код: их читают прогон (``indexing_service``), отчёт, интерфейс и тесты,
поэтому список живёт в одном месте и проверяется ``validate_queries``.

Запросы сформулированы по документам репозитория и разнесены по разным дням: так
видно, что поиск различает темы, а не возвращает один и тот же топ. Ожидаемые
источники — те, где тема раскрыта (README дня и профильный модуль), поэтому
precision/recall считаются осмысленно, а не по случайным совпадениям.

Модуль чистый: ``dataclasses``, ``config`` и сосед по слою ``document_sources``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .document_sources import DOCUMENT_SOURCES, source_slug

__all__ = ["DEMO_QUERIES", "TestQuery", "queries_as_dicts", "validate_queries"]


@dataclass(frozen=True)
class TestQuery:
    """Тестовый запрос: текст, ожидаемые документы и пояснение для отчёта."""

    query: str
    expected_sources: tuple[str, ...]
    note: str


#: Пять запросов демо-сценария (ground truth — имена файлов в ``documents/``).
DEMO_QUERIES: tuple[TestQuery, ...] = (
    TestQuery(
        query="оркестрация флота MCP-серверов и маршрутизация вызова по имени инструмента",
        expected_sources=("day20-readme.md", "day20-docs-architecture.md"),
        note="тема дня 20: флот из трёх серверов, реестр, маршрутизация по инструменту",
    ),
    TestQuery(
        query="стейт-машина сжатия контекста: состояния, события и политика сжатия",
        expected_sources=("day9-backend-context_fsm.py", "day9-backend-context_policy.py"),
        note="тема дня 9: ContextState/ContextEvent и чистая политика «когда сжимать»",
    ),
    TestQuery(
        query="контролируемые переходы состояния задачи и guard-условия на флаги согласования",
        expected_sources=("day15-readme.md", "day15-backend-domain-task_state_machine.py"),
        note="тема дня 15: граф ALLOWED_TRANSITIONS и guard-условия этапов",
    ),
    TestQuery(
        query="планировщик фоновых задач APScheduler и восстановление задач после перезапуска",
        expected_sources=("day18-readme.md",),
        note="тема дня 18: APScheduler, таблица scheduled_tasks и sync_from_db",
    ),
    TestQuery(
        query="декларативный пайплайн MCP-инструментов и маппинг данных между шагами",
        expected_sources=("day19-readme.md", "day20-backend-domain-pipeline_mapping.py"),
        note="тема дней 19–20: шаги как данные и ссылки $steps.<i>.<путь>",
    ),
)


def validate_queries() -> list[str]:
    """Проверяет тестовые запросы; пустой список — всё в порядке.

    Ловится ровно то, что ломает демонстрацию: пустой текст запроса и ожидаемый
    источник, которого нет среди документов (опечатка в slug'е давала бы вечный
    recall 0, и это выглядело бы как плохая стратегия, а не как ошибка данных).
    """
    errors: list[str] = []
    known = {source_slug(source.path) for source in DOCUMENT_SOURCES}
    for index, item in enumerate(DEMO_QUERIES):
        if not item.query.strip():
            errors.append(f"запрос №{index + 1}: пустой текст")
        if not item.expected_sources:
            errors.append(f"запрос №{index + 1}: не указаны ожидаемые источники")
        for expected in item.expected_sources:
            if expected not in known:
                errors.append(
                    f"запрос №{index + 1}: ожидаемый источник {expected} не входит "
                    f"в DOCUMENT_SOURCES"
                )
    return errors


def queries_as_dicts() -> list[dict[str, Any]]:
    """Запросы словарями — для схем API, интерфейса и отчёта."""
    return [
        {
            "query": item.query,
            "expected_sources": list(item.expected_sources),
            "note": item.note,
        }
        for item in DEMO_QUERIES
    ]
