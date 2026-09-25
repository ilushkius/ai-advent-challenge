"""План оркестрации: шаги, их аргументы и проверка конфигурации (день 20).

План — это ДАННЫЕ, как и пайплайн дня 19: список шагов, у каждого имя
MCP-инструмента, аргументы (со ссылками на выход предыдущих шагов) и
необязательное условие перехода. Отличие в том, что сервер для шага НЕ указан:
маршрутизацией занимается реестр флота (``find_tool_by_name``), поэтому один и тот
же шаг означает «любой сервер, который публикует такой инструмент», а инструменты
с уникальными именами (``search_web``, ``summarize``, ``save_to_file``) сами
раскладываются по своим серверам.

Ссылки в аргументах разрешает ТОТ ЖЕ механизм, что у пайплайна
(``pipeline_mapping.resolve_mapping``): ``{имя}`` — аргумент запуска,
``$steps.<i>.<путь>`` — поле выхода шага ``i``. Своих парсеров здесь нет: две
реализации подстановки разошлись бы на первой правке.

Условие шага (``guard``) — та же ссылка плюс оператор
(``non_empty``/``empty``/``equals``/``contains``). Невыполненное условие не делает
прогон ошибкой: оркестрация завершается досрочно со статусом ``stopped`` и
сообщением условия.

Модуль чистый: ``config`` и стандартная библиотека.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from ..core import config
from .pipeline_spec import GUARD_OPS

#: Имя плана по умолчанию (когда имя не задано ни планом, ни эвристикой).
DEFAULT_PLAN_NAME = "orchestration-chain"
#: Имя плана, собранного эвристикой: по нему в журнале видно, что модель не отвечала.
HEURISTIC_PLAN_NAME = "heuristic-chain"
#: Имя файла по умолчанию, когда из реплики не выводится ни одного слова.
DEFAULT_FILENAME = "orchestration"

#: Сообщения прогона: попадают в API, интерфейс, промпт и отчёт без маппинга.
MSG_RUNNING = "оркестрация выполняется"
MSG_COMPLETED = "оркестрация выполнена"
MSG_FAILED = "оркестрация остановлена: шаг завершился ошибкой"
MSG_STOPPED = "оркестрация завершена досрочно"

#: Статусы шага в журнале ``orchestration_steps``.
STEP_OK = "ok"
STEP_FAILED = "failed"
STEP_STOPPED = "stopped"

#: Коды причин отказа: контракт API (400 — план и запрос, 404 — запуск).
REASON_BAD_QUERY = "bad_query"
REASON_NOT_FOUND = "not_found"
REASON_BAD_PLAN = "bad_plan"

#: Реплика демонстрационного сценария: пять шагов по трём серверам.
DEMO_QUERY = ("найди последние посты пользователей, сделай сводку по темам, "
              "сохрани в файл и запиши в базу")

#: Имя файла и формат демо-сценария (аргументы запуска по умолчанию).
DEMO_FILENAME = "demo-scenario"
DEMO_FORMAT = "md"
DEMO_LIMIT = 5

#: Сколько шагов в демо-сценарии: 1 — поиск, 2 — сводка, 3 — ключевые слова,
#: 4 — файл, 5 — строка в базе. Ровно столько показывает прогресс интерфейса.
DEMO_STEP_COUNT = 5


class OrchestrationRejected(Exception):
    """План отклонён или запуск не найден (``reason_code`` — контракт API)."""

    def __init__(self, message: str, reason_code: str = REASON_BAD_PLAN) -> None:
        self.message = message
        self.reason_code = reason_code
        super().__init__(message)


#: Встроенный демо-сценарий: пять шагов по трём серверам. Сервер шага не указан —
#: его выбирает реестр по имени инструмента, поэтому сценарий не меняется при
#: переезде инструмента на другой сервер флота.
#:
#: Шаг 1 (поиск) идёт с ПУСТЫМ запросом: посты jsonplaceholder — английский lorem
#: ipsum, поэтому подстрочный фильтр по русской реплике дал бы ноль элементов, а
#: пустой запрос означает «без фильтра» — первые ``limit`` записей. Сама реплика
#: при этом не теряется: она уходит в заголовок строки базы (шаг 5) и в системный
#: блок результата для модели.
DEMO_PLAN: dict[str, Any] = {
    "name": "demo-scenario",
    "steps": [
        {"tool": "search_web",
         "args": {"query": "", "source": "posts", "limit": "{limit}"}},
        {"tool": "summarize",
         "args": {"items": "$steps.0.structured.items", "style": "short",
                  "max_length": 600}},
        {"tool": "extract_keywords",
         "args": {"text": "$steps.1.structured.summary_text", "limit": 7}},
        {"tool": "save_to_file",
         "args": {
             "content": ("Сводка:\n$steps.1.structured.summary_text\n\n"
                         "Ключевые слова: $steps.2.structured.joined"),
             "filename": "{filename}", "format": "{format}"}},
        {"tool": "save_to_db",
         "args": {"kind": "orchestration", "title": "{query}",
                  "content": "$steps.1.structured.summary_text",
                  "source": "search_web",
                  "metadata": {"file": "$steps.3.structured.filepath",
                               "keywords": "$steps.2.structured.joined"}}},
    ],
}


def demo_arguments(query: str = DEMO_QUERY) -> dict[str, Any]:
    """Аргументы запуска демо-сценария: запрос, предел выборки, имя файла, формат."""
    return {
        "query": query,
        "limit": DEMO_LIMIT,
        "filename": DEMO_FILENAME,
        "format": DEMO_FORMAT,
    }


def filename_for(query: str, fmt: str = DEMO_FORMAT) -> str:
    """Имя файла по реплике: «Про RAG» + ``md`` → ``про-rag.md``.

    Имя чистит инструмент ``save_to_file`` (путь и ``..`` запрещены там), здесь оно
    только приводится к машинному виду: пробелы и знаки — в дефис, регистр — нижний.
    Одна реализация на день: и запуск из чата, и запрос без аргументов, и тесты
    должны получать одно и то же имя файла.
    """
    stem = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", query or "").strip("-").lower()
    return f"{stem[:config.ORCH_NAME_MAX] or DEFAULT_FILENAME}.{fmt}"


def launch_arguments(query: str, extra: dict | None = None) -> dict[str, Any]:
    """Аргументы запуска с умолчаниями: переданные значения сильнее умолчаний.

    Заглушки ``{limit}``, ``{filename}``, ``{format}`` есть во встроенном сценарии,
    поэтому прогон без явных аргументов (``POST /orchestration/run`` с одной
    репликой) не должен падать на маппинге: незаполненная заглушка — ошибка
    конфигурации, а не то, что человек имел в виду, отправляя запрос. Имя файла
    выводится из реплики тем же способом, что у пайплайна дня 19.
    """
    args: dict[str, Any] = {
        "query": query,
        "limit": DEMO_LIMIT,
        "filename": filename_for(query),
        "format": DEMO_FORMAT,
    }
    args.update(extra or {})
    return args


def validate_plan(plan: dict | None) -> dict:
    """Проверяет план и возвращает его нормализованный вид (копию).

    Проверяется ровно то, без чего прогон неоднозначен: план — словарь с непустым
    списком шагов (не длиннее ``ORCH_STEPS_MAX``), у каждого шага есть непустое имя
    инструмента, ``args`` — словарь, ``guard`` — словарь с ``path`` и известным
    ``op``. Существование инструмента здесь не проверяется: неизвестный
    инструмент честно отвергается шагом прогона (``unknown_tool``) и виден в
    журнале шагов.
    """
    if plan is None:
        raise OrchestrationRejected(
            "План оркестрации не задан: пришлите объект с полем steps или не "
            "передавайте поле plan — тогда план построится сам"
        )
    if not isinstance(plan, dict):
        raise OrchestrationRejected("План оркестрации должен быть объектом")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise OrchestrationRejected("У плана должен быть непустой список шагов «steps»")
    if len(steps) > config.ORCH_STEPS_MAX:
        raise OrchestrationRejected(
            f"Шагов больше предела: {len(steps)} > {config.ORCH_STEPS_MAX}"
        )
    name = plan.get("name") or DEFAULT_PLAN_NAME
    if not isinstance(name, str) or len(name) > config.ORCH_NAME_MAX:
        raise OrchestrationRejected(
            f"Имя плана должно быть строкой не длиннее {config.ORCH_NAME_MAX} символов"
        )
    return {"name": name, "steps": [_validate_step(step, index)
                                    for index, step in enumerate(steps)]}


def _validate_step(step: Any, index: int) -> dict[str, Any]:
    """Один шаг: имя инструмента, аргументы-словарь и необязательное условие."""
    if not isinstance(step, dict):
        raise OrchestrationRejected(f"Шаг {index} должен быть объектом")
    tool = step.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        raise OrchestrationRejected(f"У шага {index} не указан инструмент «tool»")
    args = step.get("args", {})
    if not isinstance(args, dict):
        raise OrchestrationRejected(f"Аргументы шага {index} должны быть объектом «args»")
    # Копия, а не ссылка: нормализованный план не должен делить словари с исходной
    # конфигурацией — иначе правка аргументов прогона меняла бы DEMO_PLAN.
    result: dict[str, Any] = {"tool": tool.strip(),
                              "args": copy.deepcopy(dict(args))}
    guard = step.get("guard")
    if guard is not None:
        if not isinstance(guard, dict):
            raise OrchestrationRejected(f"Условие шага {index} должно быть объектом «guard»")
        path = guard.get("path")
        op = guard.get("op")
        if not isinstance(path, str) or not path:
            raise OrchestrationRejected(f"Условию шага {index} нужен путь «path»")
        if op not in GUARD_OPS:
            raise OrchestrationRejected(
                f"Условие «{op}» не поддержано. Допустимы: " + ", ".join(GUARD_OPS)
            )
        result["guard"] = copy.deepcopy(dict(guard))
    return result


def steps_for_prompt(plan: dict | None) -> str:
    """Короткое описание плана для лога и отчёта: «search_web → summarize → …»."""
    steps = (plan or {}).get("steps") or []
    return " → ".join(str(step.get("tool", "?")) for step in steps) or "—"
