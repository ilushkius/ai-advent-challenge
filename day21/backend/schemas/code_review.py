"""Pydantic-схемы API AI-ревью PR (день 32).

Один файл на два режима раздела: локальный (``POST /review/pr`` и
``GET /review/health``) и GitHub (``POST /review/github-pr`` и
``GET /review/github-health``). Запрос принимает и готовый ``diff`` со
списком ``changed_files``, и пару ``base``/``head`` — во втором случае diff добывает
служба через MCP-инструмент ``get_pr_diff``. Поэтому поля запроса необязательны все
сразу: правило «нужен diff или base и head» — предметное, его проверяет служба и
отвечает 400, а не Pydantic, который знал бы об этом контракте третьим местом.

Ответ разобран на отдельные модели, а не ``dict``: комментарий в PR и отчёт читают
поля по именам (``bugs``, ``architecture_issues``, ``recommendations``, ``risks``),
и схема — единственное место, где эти имена закреплены. ``provider`` уходит строкой,
как и у соседних разделов: список провайдеров живёт в домене
(``llm_provider.PROVIDERS``), и незнакомое имя — это 400 от службы с перечнем
доступных, а не 422 от Pydantic.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CodeReviewFindingOut(BaseModel):
    """Найденный баг: где, что не так и насколько срочно."""

    file: str = Field("", description="Путь файла от корня репозитория")
    line: str = Field("", description="Строка или диапазон строк (может быть пусто)")
    issue: str = Field("", description="Что именно не так")
    priority: str = Field("P3", description="Приоритет: P0 | P1 | P2 | P3")


class CodeReviewArchitectureOut(BaseModel):
    """Архитектурная проблема: нарушение слоёв и как его исправить."""

    file: str = Field("", description="Путь файла от корня репозитория")
    issue: str = Field("", description="В чём нарушение архитектуры")
    recommendation: str = Field("", description="Как исправить")
    priority: str = Field("P3", description="Приоритет: P0 | P1 | P2 | P3")


class CodeReviewRiskOut(BaseModel):
    """Риск изменения: чем оно грозит и насколько срочно это учитывать."""

    priority: str = Field("P3", description="Приоритет: P0 | P1 | P2 | P3")
    file: str = Field("", description="Путь файла от корня репозитория")
    risk: str = Field("", description="Чем грозит, если оставить как есть")


class CodeReviewSourceOut(BaseModel):
    """Фрагмент RAG-контекста, на который опиралось ревью."""

    source: str = Field(..., description="Имя документа корпуса (напр. day21-docs-api.md)")
    title: str = Field("", description="Заголовок документа")
    section: str = Field("", description="Секция (заголовок раздела) фрагмента")
    chunk_id: str = Field("", description="Идентификатор чанка в индексе")
    score: float = Field(0.0, description="Балл, по которому фрагмент отобран")
    vector_score: float = Field(0.0, description="Косинусная близость фрагмента")
    lexical_score: float = Field(0.0, description="Словесное совпадение с запросом")
    rerank_score: Optional[float] = Field(
        None, description="Балл реранкера (null, если реранкер не применялся)")


class CodeReviewToolUseOut(BaseModel):
    """Один вызов MCP-инструмента в ревью: что вызвали и чем это кончилось."""

    tool: str = Field(..., description="Имя инструмента (get_pr_diff или get_changed_files)")
    ok: bool = Field(True, description="Инструмент ответил без ошибки")
    duration_ms: int = Field(0, description="Сколько занял вызов, мс")
    error: str = Field("", description="Текст ошибки инструмента (пусто при успехе)")


class PrReviewIn(BaseModel):
    """POST /review/pr — запрос ревью: diff либо пара ref-ов плюс метка PR."""

    owner: str = Field("", max_length=120, description="Владелец репозитория (для метки)")
    repo: str = Field("", max_length=120, description="Имя репозитория (для метки)")
    pr_number: int = Field(0, ge=0, description="Номер PR (для метки; 0 — неизвестен)")
    base: str = Field("", max_length=200, description="Базовый ref (напр. main или day30)")
    head: str = Field("", max_length=200, description="Ref изменения (напр. day31)")
    diff: str = Field("", description="Готовый unified diff; пусто — служба добудет его через MCP")
    changed_files: List[str] = Field(
        [], description="Изменённые файлы (пусто — из MCP или из diff-а)")
    provider: str = Field("deepseek", max_length=16,
                          description="Провайдер ответа: deepseek | local; незнакомый — 400")
    pr_label: str = Field("", max_length=200,
                          description="Подпись ревью (пусто — собирается из ref-ов или PR)")


class PrReviewOut(BaseModel):
    """Ответ ревью: структура находок, источники контекста и предупреждения шагов."""

    review_text: str = Field(..., description="Ответ модели целиком")
    bugs: List[CodeReviewFindingOut] = Field([], description="Найденные баги")
    architecture_issues: List[CodeReviewArchitectureOut] = Field(
        [], description="Архитектурные проблемы")
    recommendations: List[str] = Field([], description="Рекомендации по улучшению")
    risks: List[CodeReviewRiskOut] = Field(
        [], description="Риски: отсортированы от P0 к P3")
    sources: List[CodeReviewSourceOut] = Field(
        [], description="Фрагменты RAG-контекста (документация и код изменённых файлов)")
    mcp_tools_used: List[CodeReviewToolUseOut] = Field(
        [], description="Вызовы MCP-инструментов (пусто, если diff пришёл в запросе)")
    changed_files: List[str] = Field([], description="Файлы, по которым шло ревью")
    duration_ms: int = Field(0, description="Время ревью целиком, мс")
    provider: str = Field("deepseek", description="Провайдер, который отвечал")
    warnings: List[str] = Field(
        [], description="Отказы шагов: обрезка diff-а, пустой индекс, файл вне корпуса")


class CodeReviewHealthOut(BaseModel):
    """Готовность службы ревью: провайдер, инструменты MCP и предел diff-а."""

    status: str = Field("ok", description="Состояние службы")
    service: str = Field("code-review", description="Имя службы")
    default_provider: str = Field("deepseek", description="Провайдер ответа по умолчанию")
    providers: List[str] = Field([], description="Доступные провайдеры")
    mcp_tools: List[str] = Field([], description="Инструменты MCP, которыми пользуется ревью")
    index_strategy: str = Field("", description="Стратегия поиска по корпусу RAG")
    max_diff_lines: int = Field(0, description="Предел diff-а в промпте, строк")
    report_path: str = Field("", description="Путь отчёта по умолчанию (от корня дня)")


class GitHubPrReviewIn(BaseModel):
    """POST /review/github-pr — ревью PR из GitHub: URL репозитория, номер и публикация."""

    repo_url: str = Field(..., max_length=300,
                          description="URL репозитория: https://github.com/owner/repo или "
                                      "git@github.com:owner/repo.git")
    pr_number: int = Field(..., ge=1, description="Номер PR (1 и больше)")
    provider: str = Field("deepseek", max_length=16,
                          description="Провайдер ответа: deepseek | local; незнакомый — 400")
    post_comment: bool = Field(False, description="Опубликовать ревью комментарием в PR "
                                                  "(нужен GITHUB_TOKEN с правом на запись)")


class GitHubMetaOut(BaseModel):
    """Происхождение ревью: репозиторий, номер PR, ссылка и размеры."""

    owner: str = Field("", description="Владелец репозитория")
    repo: str = Field("", description="Имя репозитория")
    pr_number: int = Field(0, description="Номер PR")
    pr_url: str = Field("", description="Ссылка на PR")
    changed_files_count: int = Field(0, description="Сколько файлов меняет PR")
    diff_lines: int = Field(0, description="Сколько строк в diff-е от GitHub")


class GitHubRateLimitOut(BaseModel):
    """Остаток анонимного или токенного лимита GitHub."""

    limit: int = Field(0, description="Лимит запросов в час")
    remaining: int = Field(0, description="Осталось запросов")
    used: int = Field(0, description="Израсходовано запросов")
    reset: int = Field(0, description="Unix-время сброса лимита (UTC)")


class GitHubPrReviewOut(PrReviewOut):
    """Ответ ревью из GitHub: всё как у PrReviewOut плюс PR, публикация и мета."""

    github_meta: GitHubMetaOut = Field(default_factory=GitHubMetaOut,
                                      description="Репозиторий, PR и размеры diff-а")
    pr_url: str = Field("", description="Ссылка на PR")
    posted: bool = Field(False, description="Комментарий опубликован в PR")
    comment_url: str = Field("", description="Ссылка на комментарий (пусто, если не публиковали)")


class GitHubHealthOut(BaseModel):
    """Готовность GitHub: доступность API, признак токена и остаток лимита."""

    status: str = Field("ok", description="ok | degraded")
    service: str = Field("github", description="Имя службы")
    api_base: str = Field("", description="Базовый адрес REST API")
    authenticated: bool = Field(False, description="Токен задан (окружение или day21/.env)")
    token: str = Field("", description="Маска токена (первые 4 символа и звёздочки)")
    rate_limit: GitHubRateLimitOut = Field(default_factory=GitHubRateLimitOut,
                                           description="Остаток лимита запросов")
    error: str = Field("", description="Причина отказа (пусто при status=ok)")


__all__ = ["CodeReviewArchitectureOut", "CodeReviewFindingOut", "CodeReviewHealthOut",
           "CodeReviewRiskOut", "CodeReviewSourceOut", "CodeReviewToolUseOut",
           "GitHubHealthOut", "GitHubMetaOut", "GitHubPrReviewIn", "GitHubPrReviewOut",
           "GitHubRateLimitOut", "PrReviewIn", "PrReviewOut"]
