"""Pydantic-схемы API подготовки релиза (день 35).

Схемы описаны в своём модуле, а не в пакете ``..schemas``: ``schemas/__init__.py``
стоит на пределе 400 строк, и дни 30–34 сделали так же.

Что описывают формы:

- ``ReleasePrepareIn`` — запрос прогона: диапазон тегов, версия (``auto`` или
  ``X.Y.Z``), провайдер и режим ``dry_run``;
- ``ReleasePrepareOut`` — ответ ``POST /release/prepare`` целиком: версия с причиной
  выбора, списки модели, готовый раздел CHANGELOG, заметки о релизе, проверки
  готовности, план правки файлов и предпросмотр diff-а. Одна форма на ``dry_run`` и
  реальный прогон намеренно: различает их ``status`` и ``files_modified``, а не состав
  полей — иначе интерфейс разбирал бы два разных ответа;
- ``ChangelogOut`` — раздел CHANGELOG в разобранном виде (пять групп, счётчик
  свёрнутого и готовый текст): раздел интерфейса показывает и то, и другое;
- ``ChecksOut``/``CheckCommandOut`` — проверки готовности: признак тестов, процент
  покрытия, наличие файлов и хвост вывода каждой команды (разбирать его в интерфейсе
  заново не нужно);
- ``FileChangeOut`` — одна строка плана правки: путь, инструмент, признак пропуска и
  текст ошибки, если запись не удалась;
- ``ReleaseTagsOut``/``ReleaseMetricsOut`` — читающие эндпоинты без модели;
- ``ReleaseHealthOut`` — результат проверок без MCP (доступен и до первого релиза);
- ``ReleaseRunSummaryOut``/``ReleaseHistoryOut`` — строка истории без текстов разделов
  и сами запуски от свежих к старым;
- ``ReleaseExportIn`` — выгрузка: номер запуска и что именно скачивать.

Тела файлов выгрузки (``CHANGELOG.md``, ``RELEASE_NOTES.md``) схемой не описываются:
``POST /release/export`` отвечает файлом или ZIP-архивом, а не JSON.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ReleasePrepareIn(BaseModel):
    """POST /release/prepare — диапазон тегов, версия, провайдер и режим."""
    from_tag: str = Field("day1", description="Тег начала диапазона (неизвестный — корень истории)")
    to_tag: str = Field("HEAD", description="Тег конца диапазона (неизвестный — HEAD)")
    version: str = Field("auto", description="Версия X.Y.Z или auto: тип изменения определяет модель")
    provider: str = Field("deepseek", description="Провайдер ответа: deepseek или local")
    dry_run: bool = Field(False, description="Предпросмотр: файлы не записываются")


class ChangelogOut(BaseModel):
    """Раздел CHANGELOG: группы пунктов, счётчики и готовый текст раздела."""
    added: List[str] = Field(default_factory=list, description="Пункты группы Added")
    changed: List[str] = Field(default_factory=list, description="Пункты группы Changed")
    fixed: List[str] = Field(default_factory=list, description="Пункты группы Fixed")
    removed: List[str] = Field(default_factory=list, description="Пункты группы Removed")
    breaking: List[str] = Field(default_factory=list, description="Пункты группы Breaking")
    minor_count: int = Field(0, description="Сколько коммитов свёрнуто в строку Minor changes")
    dropped_count: int = Field(0, description="Сколько пунктов модели не влезло в предел 20")
    section: str = Field("", description="Готовый markdown-раздел для CHANGELOG.md")


class CheckCommandOut(BaseModel):
    """Одна команда проверки готовности: что запускали, чем кончилось и сколько заняло."""
    name: str = Field(..., description="Имя проверки: tests или coverage")
    command: str = Field(..., description="Команда целиком")
    returncode: int = Field(0, description="Код возврата (0 — успех, -1 — не запустилась)")
    duration_ms: int = Field(0, description="Сколько заняла команда, мс")
    tail: str = Field("", description="Хвост вывода команды (последние 400 символов)")


class ChecksOut(BaseModel):
    """Проверки готовности релиза: тесты, покрытие, файлы документации."""
    tests_passed: bool = Field(False, description="Быстрый набор тестов прошёл")
    coverage_percent: float = Field(0.0, description="Покрытие backend из pytest-cov, проценты")
    readme_exists: bool = Field(False, description="Корневой README.md на месте")
    docs_exists: bool = Field(False, description="day21/docs/architecture.md на месте")
    passed: bool = Field(False, description="Все проверки пройдены")
    notes: List[str] = Field(default_factory=list, description="Заметки проверок")
    files: Dict[str, Any] = Field(default_factory=dict, description="Проверенные пути и их наличие")
    commands: List[CheckCommandOut] = Field(default_factory=list, description="Выполненные команды")


class FileChangeOut(BaseModel):
    """Одна строка плана правки: чем меняется файл релиза."""
    path: str = Field(..., description="Путь от корня репозитория")
    tool: str = Field(..., description="Инструмент записи: apply_patch или write_file")
    skipped: bool = Field(False, description="Правка пропущена (раздел уже есть или файла нет)")
    ok: bool = Field(False, description="Файл записан этим прогоном")
    error: str = Field("", description="Текст ошибки записи (пусто при успехе)")
    note: str = Field("", description="Причина пропуска правки")


class ReleasePrepareOut(BaseModel):
    """Ответ прогона: версия, раздел CHANGELOG, проверки, план правки и предпросмотр."""
    run_id: int = Field(..., description="Номер запуска в истории релизов")
    from_tag: str = Field(..., description="Запрошенный тег начала диапазона")
    to_tag: str = Field(..., description="Запрошенный тег конца диапазона")
    from_label: str = Field("", description="Подпись начала: тега нет — сказано прямо")
    to_label: str = Field("", description="Подпись конца диапазона")
    version: str = Field(..., description="Итоговая версия релиза")
    version_reason: str = Field("", description="Почему выбрана именно эта версия")
    version_bump: str = Field("", description="Тип изменения: major, minor или patch")
    breaking_changes: List[str] = Field(default_factory=list, description="Несовместимые изменения от модели")
    features: List[str] = Field(default_factory=list, description="Новая функциональность от модели")
    fixes: List[str] = Field(default_factory=list, description="Исправления от модели")
    changelog: ChangelogOut = Field(..., description="Раздел CHANGELOG в разобранном виде")
    release_notes: str = Field("", description="Текст заметок о релизе")
    checks: ChecksOut = Field(..., description="Проверки готовности прогона")
    checks_passed: bool = Field(False, description="Проверки пройдены")
    files_to_modify: List[FileChangeOut] = Field(default_factory=list, description="План правки файлов")
    diff_preview: Dict[str, str] = Field(default_factory=dict, description="Diff правки по пути файла")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Метрики проекта")
    notes: List[str] = Field(default_factory=list, description="Заметки прогона: пропуски и отказы")
    commits_count: int = Field(0, description="Сколько коммитов в диапазоне")
    changed_files: List[str] = Field(default_factory=list, description="Файлы, изменённые в диапазоне")
    duration_ms: int = Field(0, description="Сколько занял прогон, мс")
    provider: str = Field("", description="Провайдер ответа")
    status: str = Field("", description="Статус прогона: completed, failed или dry_run")
    dry_run: bool = Field(False, description="Прогон не менял файлы")


class ReleaseTagsOut(BaseModel):
    """GET /release/tags — теги репозитория для селекторов раздела."""
    count: int = Field(0, description="Сколько тегов")
    tags: List[Dict[str, Any]] = Field(default_factory=list, description="Теги: имя, дата и коммит")


class ReleaseHealthOut(BaseModel):
    """GET /release/health — проверки готовности без MCP и без модели."""
    checks: ChecksOut = Field(..., description="Результат проверок готовности")
    checks_passed: bool = Field(False, description="Проверки пройдены")


class ReleaseMetricsOut(BaseModel):
    """GET /release/metrics — метрики проекта инструментом git-истории."""
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Метрики проекта")


class ReleaseRunSummaryOut(BaseModel):
    """Строка истории релизов: запуск без текстов разделов."""
    id: int = Field(..., description="Номер запуска")
    from_tag: str = Field(..., description="Тег начала диапазона")
    to_tag: str = Field(..., description="Тег конца диапазона")
    version: str = Field(..., description="Версия запуска")
    version_reason: str = Field("", description="Причина выбора версии")
    checks_passed: bool = Field(False, description="Проверки прошли на момент запуска")
    files_modified: List[str] = Field(default_factory=list, description="Записанные файлы")
    status: str = Field(..., description="Статус: running, completed, failed или dry_run")
    started_at: Any = Field(None, description="Начало прогона (ISO-8601 UTC)")
    finished_at: Any = Field(None, description="Конец прогона (ISO-8601 UTC)")


class ReleaseHistoryOut(BaseModel):
    """GET /release/history — релизы от свежих к старым."""
    count: int = Field(0, description="Сколько запусков вернулось")
    runs: List[ReleaseRunSummaryOut] = Field(default_factory=list, description="Строки истории")


class ReleaseExportIn(BaseModel):
    """POST /release/export — что скачивать и от какого запуска."""
    run_id: int = Field(..., description="Номер запуска из истории релизов")
    file: str = Field("both", description="Что выгружать: both (ZIP), changelog или release_notes")


__all__ = ["ChangelogOut", "CheckCommandOut", "ChecksOut", "FileChangeOut",
           "ReleaseExportIn", "ReleaseHealthOut", "ReleaseHistoryOut",
           "ReleaseMetricsOut", "ReleasePrepareIn", "ReleasePrepareOut",
           "ReleaseRunSummaryOut", "ReleaseTagsOut"]
