"""Декларативное описание пайплайна: шаги, условия перехода и проверка конфигурации.

Пайплайн — это ДАННЫЕ, а не код: список шагов, у каждого имя MCP-инструмента,
аргументы (со ссылками на результаты предыдущих шагов) и необязательное условие
перехода. Прогон (§``backend/services/pipeline.py``) читает эту структуру и
выполняет шаги по порядку, поэтому «что делает пайплайн» видно в одном словаре:
его можно прислать телом запроса, показать в интерфейсе и положить в отчёт.

Ссылки внутри аргументов разрешает ``pipeline_mapping.py``:

- ``{имя}`` — аргумент запуска (``{query}``, ``{source}``, ``{limit}``…);
- ``$steps.<i>.<путь>`` — поле выхода шага ``i`` (``$steps.0.structured.items``).

Условие шага (``guard``) — та же ссылка плюс оператор: ``non_empty``, ``empty``,
``equals``, ``contains``. Условие, которое не выполнилось, НЕ делает прогон
ошибкой: пайплайн завершается досрочно со статусом ``stopped`` и сообщением
условия (у встроенного пайплайна это «нет данных для обработки»).

Модуль чистый: только ``config`` и стандартная библиотека.
"""
from __future__ import annotations

from typing import Any

from ..core import config

#: Инструменты композиции — шагами пайплайна являются только они.
TOOL_SEARCH = "search"
TOOL_SUMMARIZE = "summarize"
TOOL_SAVE_TO_FILE = "save_to_file"
DEFAULT_TOOLS: tuple[str, ...] = (TOOL_SEARCH, TOOL_SUMMARIZE, TOOL_SAVE_TO_FILE)

#: Имя встроенного пайплайна (он же — пайплайн по умолчанию).
DEFAULT_PIPELINE_NAME = "search-summarize-save"

#: Операторы условия перехода.
GUARD_NON_EMPTY = "non_empty"
GUARD_EMPTY = "empty"
GUARD_EQUALS = "equals"
GUARD_CONTAINS = "contains"
GUARD_OPS: tuple[str, ...] = (GUARD_NON_EMPTY, GUARD_EMPTY, GUARD_EQUALS, GUARD_CONTAINS)
DEFAULT_GUARD_MESSAGE = "условие шага не выполнено"

#: Сообщения прогона: попадают в API, интерфейс и отчёт без маппинга.
MSG_RUNNING = "пайплайн выполняется"
MSG_COMPLETED = "пайплайн выполнен"
MSG_FAILED = "пайплайн остановлен: шаг завершился ошибкой"
MSG_STOPPED = "пайплайн завершён досрочно"
MSG_NO_DATA = "нет данных для обработки"

#: Статусы шага в журнале ``pipeline_steps``.
STEP_OK = "ok"
STEP_FAILED = "failed"
STEP_STOPPED = "stopped"

#: Коды причин отказа пайплайна: контракт API (400 — конфигурация, 404 — запуск).
REASON_BAD_CONFIG = "bad_config"
REASON_NOT_FOUND = "not_found"

#: Источник по умолчанию — заметки дня: прогон работает офлайн, без сети.
FILE_SOURCE_DEFAULT = "file:mcp_server/data/notes.md"

#: Варианты источника в интерфейсе: (значение, подпись).
PIPELINE_SOURCE_OPTIONS: tuple[tuple[str, str], ...] = (
    (FILE_SOURCE_DEFAULT, "файл дня: mcp_server/data/notes.md (заметки про RAG)"),
    ("posts", "jsonplaceholder: посты"),
    ("users", "jsonplaceholder: пользователи"),
    ("sqlite:pipeline_steps", "SQLite: шаги прошлых запусков"),
)


class PipelineRejected(Exception):
    """Пайплайн отклонён (негодная конфигурация или отсутствующий запуск)."""

    def __init__(self, message: str, reason_code: str = REASON_BAD_CONFIG) -> None:
        self.message = message
        self.reason_code = reason_code
        super().__init__(message)


#: Встроенный пайплайн: поиск → сводка → файл. Условие на втором шаге —
#: «нашли хоть что-нибудь»: пустой поиск останавливает прогон досрочно.
DEFAULT_PIPELINE: dict[str, Any] = {
    "name": DEFAULT_PIPELINE_NAME,
    "steps": [
        {
            "tool": TOOL_SEARCH,
            "args": {"query": "{query}", "source": "{source}", "limit": "{limit}"},
        },
        {
            "tool": TOOL_SUMMARIZE,
            "guard": {"path": "$steps.0.structured.items", "op": GUARD_NON_EMPTY,
                      "message": MSG_NO_DATA},
            "args": {"items": "$steps.0.structured.items", "style": "{style}",
                     "max_length": "{max_length}"},
        },
        {
            "tool": TOOL_SAVE_TO_FILE,
            "args": {"content": "$steps.1.structured.summary_text",
                     "filename": "{filename}", "format": "{format}"},
        },
    ],
}


def validate_pipeline(pipeline_config: dict | None) -> dict:
    """Проверяет декларативную конфигурацию и возвращает её нормализованный вид.

    Проверяется ровно то, без чего прогон неоднозначен: конфигурация — словарь с
    непустым списком шагов (не длиннее ``PIPELINE_STEPS_MAX``), у каждого шага есть
    непустое имя инструмента, ``args`` — словарь, ``guard`` — словарь с ``path`` и
    известным ``op``. Неизвестный инструмент не проверяется здесь: он честно
    отвергается шагом прогона (``unknown_tool``), и это видно в журнале шагов.
    """
    if pipeline_config is None:
        raise PipelineRejected(
            "Конфигурация пайплайна не задана: пришлите объект с полем steps "
            "или не передавайте поле pipeline — тогда выполнится встроенный пайплайн"
        )
    if not isinstance(pipeline_config, dict):
        raise PipelineRejected("Конфигурация пайплайна должна быть объектом")
    steps = pipeline_config.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PipelineRejected("У пайплайна должен быть непустой список шагов «steps»")
    if len(steps) > config.PIPELINE_STEPS_MAX:
        raise PipelineRejected(
            f"Шагов больше предела: {len(steps)} > {config.PIPELINE_STEPS_MAX}"
        )
    name = pipeline_config.get("name") or DEFAULT_PIPELINE_NAME
    if not isinstance(name, str) or len(name) > config.PIPELINE_NAME_MAX:
        raise PipelineRejected(
            f"Имя пайплайна должно быть строкой не длиннее {config.PIPELINE_NAME_MAX} символов"
        )
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        normalized.append(_validate_step(step, index))
    return {"name": name, "steps": normalized}


def _validate_step(step: Any, index: int) -> dict[str, Any]:
    """Один шаг: имя инструмента, аргументы-словарь и условие-словарь."""
    if not isinstance(step, dict):
        raise PipelineRejected(f"Шаг {index} должен быть объектом")
    tool = step.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        raise PipelineRejected(f"У шага {index} не указан инструмент «tool»")
    args = step.get("args", {})
    if not isinstance(args, dict):
        raise PipelineRejected(f"Аргументы шага {index} должны быть объектом «args»")
    # Копия, а не ссылка: нормализованный вид не должен делить словари с исходной
    # конфигурацией — иначе правка аргументов прогона меняла бы DEFAULT_PIPELINE.
    result: dict[str, Any] = {"tool": tool.strip(), "args": dict(args)}
    guard = step.get("guard")
    if guard is not None:
        if not isinstance(guard, dict):
            raise PipelineRejected(f"Условие шага {index} должно быть объектом «guard»")
        path = guard.get("path")
        op = guard.get("op")
        if not isinstance(path, str) or not path:
            raise PipelineRejected(f"Условию шага {index} нужен путь «path»")
        if op not in GUARD_OPS:
            raise PipelineRejected(
                f"Условие «{op}» не поддержано. Допустимы: " + ", ".join(GUARD_OPS)
            )
        result["guard"] = dict(guard)
    return result
