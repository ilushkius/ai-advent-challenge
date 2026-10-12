"""Pydantic-схемы API ассистента разработчика (день 31).

Один файл на три эндпоинта раздела: вопрос ``/help`` (``POST /dev-assistant/help``),
каталог инструментов dev-сервера (``GET /dev-assistant/tools``) и git-контекст
(``GET /dev-assistant/git-context``). Поля ``answer``/``sources``/``mcp_tools_used``
описаны отдельными моделями, а не ``dict``: раздел интерфейса читает их по именам,
и схема — единственное место, где эти имена закреплены.

``provider`` уходит в запрос строкой, а не ``Literal``: список провайдеров живёт в
домене (``llm_provider.PROVIDERS``), и незнакомое имя — это 400 от службы с
перечнем доступных, а не 422 от Pydantic, который знал бы про них третьим местом.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..core import config


class DevAssistantHelpIn(BaseModel):
    """POST /dev-assistant/help — вопрос ассистенту разработчика."""

    question: str = Field(
        ..., min_length=1, max_length=config.INDEX_QUERY_MAX,
        description="Вопрос ассистенту; ведущий «/help» снимается",
    )
    provider: Optional[str] = Field(
        None, max_length=16,
        description=("Провайдер ответа: deepseek | local; по умолчанию deepseek "
                     "(LLM_PROVIDER). Незнакомое имя — 400"),
    )


class DevAssistantSourceOut(BaseModel):
    """Фрагмент документации, на который опирался ответ."""

    source: str = Field(..., description="Имя документа корпуса (напр. day21-docs-usage.md)")
    title: str = Field(..., description="Заголовок документа")
    section: str = Field("", description="Секция (заголовок раздела) фрагмента")
    chunk_id: str = Field("", description="Идентификатор чанка в индексе")
    score: float = Field(0.0, description="Балл, по которому фрагмент отобран")


class DevAssistantToolUseOut(BaseModel):
    """Один вызов MCP-инструмента в ответе: что вызвали и чем это кончилось."""

    tool: str = Field(..., description="Имя инструмента (напр. get_git_branch)")
    ok: bool = Field(True, description="Инструмент ответил без ошибки")
    duration_ms: int = Field(0, description="Сколько занял вызов, мс")
    error: str = Field("", description="Текст ошибки инструмента (пусто при успехе)")


class DevAssistantAnswerOut(BaseModel):
    """Ответ ассистента: текст, тип вопроса, источники и использованные инструменты."""

    question: str = Field(..., description="Нормализованный вопрос (без «/help»)")
    question_type: str = Field(..., description="Тип вопроса: docs | git | mixed")
    answer: str = Field(..., description="Ответ модели либо объяснение отказа")
    sources: List[DevAssistantSourceOut] = Field(
        [], description="Фрагменты документации, попавшие в контекст (может быть пусто)")
    mcp_tools_used: List[DevAssistantToolUseOut] = Field(
        [], description="Вызовы MCP-инструментов по плану вопроса")
    duration_ms: int = Field(0, description="Время ответа целиком, мс")
    provider: str = Field("deepseek", description="Провайдер, который отвечал")
    warnings: List[str] = Field(
        [], description="Отказы шагов: пустой индекс, недоступный MCP, сбой инструмента")


class DevAssistantToolOut(BaseModel):
    """Инструмент MCP-сервера разработки из его каталога."""

    name: str = Field(..., description="Имя инструмента")
    description: str = Field("", description="Описание для модели и человека")
    input_schema: dict = Field(default_factory=dict,
                               description="Схема аргументов инструмента")
    output_schema: dict = Field(default_factory=dict,
                               description="Схема результата инструмента")


class DevAssistantToolsOut(BaseModel):
    """Каталог инструментов dev-сервера; ошибка подключения приходит полем ``error``."""

    server: str = Field("dev_server", description="Имя сервера разработки")
    connected: bool = Field(False, description="Соединение с сервером открыто")
    count: int = Field(0, description="Сколько инструментов в каталоге")
    tools: List[DevAssistantToolOut] = Field([], description="Инструменты сервера")
    error: str = Field("", description="Причина отказа подключения (пусто при успехе)")


class DevAssistantGitContextOut(BaseModel):
    """Состояние репозитория: ветка, коммит и изменённые файлы."""

    branch: str = Field("", description="Имя текущей ветки")
    last_commit: str = Field("", description="Последний коммит одной строкой")
    modified_files: List[str] = Field([], description="Изменённые файлы от корня репозитория")
    clean: bool = Field(True, description="Рабочее дерево чисто")
    repo_root: str = Field("", description="Корень репозитория на диске")
    error: str = Field("", description="Причина отказа инструмента (пусто при успехе)")


__all__ = ["DevAssistantAnswerOut", "DevAssistantGitContextOut",
           "DevAssistantHelpIn", "DevAssistantSourceOut", "DevAssistantToolOut",
           "DevAssistantToolsOut", "DevAssistantToolUseOut"]
