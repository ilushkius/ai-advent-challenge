"""Pydantic-схемы API ассистента файлов (день 34).

Схемы описаны в своём модуле, а не в пакете ``..schemas``: ``schemas/__init__.py``
стоит на пределе 400 строк, и дни 30–33 сделали так же.

Что описывают формы:

- ``FileAssistantExecuteIn`` — запрос прогона: цель, провайдер, режим ``dry_run``;
- ``FileAssistantStepOut`` — шаг ПЛАНА и шаг ЖУРНАЛА одной формой: у шага плана
  заполнены ``step_index``/``tool``/``arguments``/``reason``, у шага журнала — ещё
  ``ok``/``status``/``duration_ms``/``error``/``result``. Одна форма на две роли
  выбрана намеренно: раздел интерфейса показывает обе таблицы одинаково, а «какие
  поля не заполнены у плана» видно по умолчаниям;
- ``FileAssistantRunOut`` — ответ ``POST /file-assistant/execute`` целиком: план,
  журнал, файлы, diff, сводка, время и статус;
- ``FileAssistantRunSummaryOut``/``FileAssistantHistoryOut`` — строка истории без
  ``diff`` и ``summary``: список запусков не должен тащить самые объёмные поля;
- ``FileAssistantDiffOut`` — ответ ``GET /file-assistant/diff/{run_id}``: diff и файлы
  одного запуска с временем начала и конца (длительность считается как их разность —
  производное значение не хранится, см. ``backend/models/file_assistant.py``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core import config


class FileAssistantExecuteIn(BaseModel):
    """POST /file-assistant/execute — цель прогона и его режим."""

    goal: str = Field(..., min_length=1, max_length=config.INDEX_QUERY_MAX,
                      description="Что нужно сделать с файлами проекта")
    #: Провайдер строкой, а не ``Literal``: список провайдеров живёт данными в
    #: ``domain.llm_provider``, и второй источник истины разошёлся бы с ним.
    provider: str = Field("deepseek", max_length=16,
                          description="Провайдер ответа: deepseek или local")
    dry_run: bool = Field(False, description="только план и предполагаемый diff, "
                                             "файлы не меняются")


class FileAssistantStepOut(BaseModel):
    """Шаг плана или шаг журнала: что вызвали, зачем и чем это кончилось."""

    step_index: int = Field(0, description="Номер шага в плане (с нуля)")
    tool: str = Field("", description="Имя инструмента файлового сервера")
    arguments: Dict[str, Any] = Field(default_factory=dict,
                                      description="Аргументы вызова")
    reason: str = Field("", description="Зачем этот шаг нужен")
    ok: bool = Field(True, description="Шаг не сломал прогон (у плана — True)")
    status: str = Field("ok", description="ok | failed | skipped")
    duration_ms: int = Field(0, description="Сколько занял вызов инструмента")
    error: str = Field("", description="Текст ошибки шага (пусто при успехе)")
    result: Optional[Dict[str, Any]] = Field(
        None, description="Усечённый результат шага для интерфейса (None — не выполнялся)")


class FileAssistantRunOut(BaseModel):
    """Ответ прогона: план, журнал шагов, файлы, diff, сводка и статус."""

    run_id: int = Field(0, description="Идентификатор запуска в истории")
    goal: str = Field("", description="Цель прогона, как её поняла служба")
    plan: List[FileAssistantStepOut] = Field(default_factory=list,
                                             description="План шагов от модели")
    steps_executed: List[FileAssistantStepOut] = Field(
        default_factory=list, description="Журнал: что реально выполнено")
    files_read: List[str] = Field(default_factory=list, description="Прочитанные файлы")
    files_modified: List[str] = Field(default_factory=list, description="Изменённые файлы")
    files_created: List[str] = Field(default_factory=list, description="Созданные файлы")
    diff: str = Field("", description="Unified diff изменений (в dry_run — предполагаемый)")
    summary: str = Field("", description="Сводка прогона от модели")
    duration_ms: int = Field(0, description="Сколько занял прогон целиком")
    provider: str = Field("", description="Провайдер ответа: deepseek или local")
    status: str = Field("", description="running | completed | failed | dry_run")
    dry_run: bool = Field(False, description="Прогон не менял файлы")


class FileAssistantRunSummaryOut(BaseModel):
    """Строка истории: запуск без ``diff`` и ``summary`` (их отдаёт отдельный эндпоинт)."""

    id: int = Field(0, description="Идентификатор запуска")
    goal: str = Field("", description="Цель прогона")
    status: str = Field("", description="running | completed | failed | dry_run")
    plan: List[FileAssistantStepOut] = Field(default_factory=list,
                                             description="План шагов прогона")
    steps: List[FileAssistantStepOut] = Field(default_factory=list,
                                              description="Журнал шагов прогона")
    files_read: List[str] = Field(default_factory=list, description="Прочитанные файлы")
    files_modified: List[str] = Field(default_factory=list, description="Изменённые файлы")
    files_created: List[str] = Field(default_factory=list, description="Созданные файлы")
    started_at: Optional[str] = Field(None, description="Начало прогона (ISO-8601 UTC)")
    finished_at: Optional[str] = Field(None, description="Конец прогона (ISO-8601 UTC)")


class FileAssistantHistoryOut(BaseModel):
    """GET /file-assistant/history — история запусков от свежих к старым."""

    count: int = Field(0, description="Сколько запусков вернулось")
    runs: List[FileAssistantRunSummaryOut] = Field(default_factory=list,
                                                    description="Строки истории")


class FileAssistantDiffOut(BaseModel):
    """GET /file-assistant/diff/{run_id} — diff и файлы одного запуска."""

    run_id: int = Field(0, description="Идентификатор запуска")
    status: str = Field("", description="Статус завершённого прогона")
    goal: str = Field("", description="Цель прогона")
    diff: str = Field("", description="Unified diff изменений прогона")
    files_read: List[str] = Field(default_factory=list, description="Прочитанные файлы")
    files_modified: List[str] = Field(default_factory=list, description="Изменённые файлы")
    files_created: List[str] = Field(default_factory=list, description="Созданные файлы")
    started_at: Optional[str] = Field(None, description="Начало прогона (ISO-8601 UTC)")
    finished_at: Optional[str] = Field(None, description="Конец прогона (ISO-8601 UTC)")


__all__ = ["FileAssistantDiffOut", "FileAssistantExecuteIn", "FileAssistantHistoryOut",
           "FileAssistantRunOut", "FileAssistantRunSummaryOut", "FileAssistantStepOut"]
