"""Правила плана ассистента файлов (день 34): разбор, валидация и вторая фаза.

План приходит от модели и потому не заслуживает доверия по умолчанию: он может быть
не JSON, ссылаться на несуществующий инструмент, обещать абсолютный путь или
``../../etc/passwd``, перепутать порядок шагов. Здесь живут все эти проверки — и
ровно они решают, что попадёт в исполнение.

Почему негодный план — исключение, а не ``None``. У планировщика оркестрации дня 20
наоборот (``orchestration_plan.parse_plan``): там отказ плана означает переход на
эвристику. Здесь эвристики нет, и отказ — это ОТВЕТ пользователю: роутер показывает
422 со списком проблем (`PlanRejected.problems`), чтобы причину было видно сразу.

Почему путевые аргументы проверяются строкой. Реальную проверку «путь внутри корня»
делает сервер (``mcp_servers/file_server/tools._resolve``) — у него есть рабочая
область, а у домена её нет. Домен отсеивает то, что видно без диска: абсолютный путь,
``..``, обратные слэши, диск ``C:``, пустую строку. Отказ в плане стоит одного
сообщения, отказ в инструменте — поднятого процесса.

Почему вторая фаза принимает шаги целиком. Разрешение аргументов (``parse_generate``)
подставляет вместо маркера ``$generate`` конкретные значения, и модели нужен не
только номер шага, но и путь с причиной: ``old_text`` для ``apply_patch`` берётся
ДОСЛОВНО из прочитанного содержимого, а путь — из результатов поиска. Частичный ответ
считается неудачей целиком: смешение «старых» и «новых» аргументов скрыло бы причину.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .file_assistant import (
    DIRECTORY_TOOLS,
    FILE_PLAN_MAX_STEPS,
    GENERATE_MARK,
    GENERATE_SYSTEM_PROMPT,
    MAX_PATH_CHARS,
    PlanRejected,
    REASON_BAD_ARGS,
    REASON_BAD_INDEX,
    REASON_BAD_PATH,
    REASON_EMPTY_PLAN,
    REASON_MISSING_DIRECTORY,
    REASON_MISSING_PATH,
    REASON_NOT_OBJECT,
    REASON_TOO_MANY_STEPS,
    REASON_UNKNOWN_TOOL,
    TOOLS,
    normalize_goal,
)
from .json_text import first_json_object

__all__ = ["build_generate_prompt", "needs_generation", "parse_generate",
           "parse_plan", "path_is_within", "path_problem", "plan_problems",
           "validate_plan"]


# ---------- проверки путей ----------
def path_problem(path: object) -> str:
    """Причина, по которой путь недопустим, или пустая строка.

    Проверка чисто строковая (реальную делает сервер по своей рабочей области):
    абсолютный путь, ``..`` в любой части, пустая строка, диск (``C:``), обратные
    слэши и путь длиннее ``MAX_PATH_CHARS`` не проходят.
    """
    text = str(path or "").strip()
    if not text:
        return "путь не задан"
    if len(text) > MAX_PATH_CHARS:
        return f"путь длиннее {MAX_PATH_CHARS} символов"
    if "\\" in text:
        return "обратные слэши в пути: используйте «/»"
    if text.startswith("/"):
        return "абсолютный путь"
    if len(text) > 1 and text[1] == ":":
        return "путь с именем диска"
    if ".." in text.split("/"):
        return "путь содержит «..»"
    return ""


def path_is_within(path: str) -> bool:
    """Допустим ли путь (обёртка над ``path_problem`` для тестов и раздела UI)."""
    return not path_problem(path)


# ---------- разбор и валидация плана ----------
def parse_plan(text: str) -> Optional[list]:
    """План из ответа модели: ``None`` — ответ не разобран как JSON.

    Негодный по правилам план — не ``None``, а ``PlanRejected`` с полным списком
    проблем: «модель ответила не тем» и «план нарушает правила» требуют разных
    действий (переспросить против показать причину), и различить их должен
    вызывающий, а не разбор.
    """
    payload = first_json_object(text or "")
    if payload is None:
        return None
    return validate_plan(payload, raw=str(text or ""))


def validate_plan(payload: object, raw: str = "") -> list:
    """Проверяет план и возвращает шаги; проблемы — ``PlanRejected``.

    Все проблемы собираются сразу: правки по одной заставляли бы гонять модель по
    кругу, а пользователь видел бы отказ столько раз, сколько в плане ошибок.
    """
    problems = plan_problems(payload)
    if problems:
        raise PlanRejected(problems, raw=raw)
    return [dict(step) for step in payload["steps"]]


def plan_problems(payload: object) -> list:
    """Список проблем плана (пустой список — план годен).

    Проверяется: объект ли это; есть ли непустой список ``steps``; не больше ли
    шагов, чем ``FILE_PLAN_MAX_STEPS``; идут ли ``step_index`` подряд с нуля; известен
    ли инструмент; объект ли ``arguments``; есть ли обязательный аргумент ``path``
    (или ``directory`` у поиска и списка) и проходит ли каждый путевой аргумент
    ``path_problem``.
    """
    if not isinstance(payload, dict):
        return [REASON_NOT_OBJECT.format(kind=type(payload).__name__)]
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return [REASON_EMPTY_PLAN]
    problems: list = []
    if len(steps) > FILE_PLAN_MAX_STEPS:
        problems.append(REASON_TOO_MANY_STEPS.format(limit=FILE_PLAN_MAX_STEPS,
                                                     count=len(steps)))
    for position, step in enumerate(steps):
        problems.extend(_step_problems(step, position))
    return problems


def _step_problems(step: Any, position: int) -> list:
    """Проблемы одного шага плана: номер, инструмент, аргументы и пути.

    Возврат на первой же проблеме шага намеренный: без известного инструмента
    проверять его аргументы нечем, и «шаг 2: неизвестный инструмент» полезнее, чем
    та же строка плюс три вывода о полях, которых у несуществующего инструмента нет.
    """
    if not isinstance(step, dict):
        return [REASON_NOT_OBJECT.format(kind=type(step).__name__)]
    try:
        index = int(step.get("step_index"))
    except (TypeError, ValueError):
        return [REASON_BAD_INDEX.format(index=position)]
    if index != position:
        return [REASON_BAD_INDEX.format(index=position)]
    tool = str(step.get("tool") or "")
    if tool not in TOOLS:
        return [REASON_UNKNOWN_TOOL.format(index=position, tool=tool)]
    arguments = step.get("arguments")
    if not isinstance(arguments, dict):
        return [REASON_BAD_ARGS.format(index=position)]
    problems = []
    if tool in DIRECTORY_TOOLS:
        if not str(arguments.get("directory") or ""):
            problems.append(REASON_MISSING_DIRECTORY.format(index=position, tool=tool))
    elif not str(arguments.get("path") or ""):
        problems.append(REASON_MISSING_PATH.format(index=position, tool=tool))
    for name in ("path", "directory"):
        if name in arguments:
            problem = path_problem(arguments[name])
            if problem:
                problems.append(REASON_BAD_PATH.format(
                    index=position, path=f"{arguments[name]} ({problem})"))
    return problems


def needs_generation(arguments: object) -> bool:
    """Есть ли в аргументах маркер ``$generate`` (рекурсивно по словарям и спискам).

    Маркером считается и значение вида ``$generate:…``: модель иногда уточняет его
    подсказкой, и такой аргумент всё равно требует второй фазы.
    """
    if isinstance(arguments, str):
        return arguments.startswith(GENERATE_MARK)
    if isinstance(arguments, dict):
        return any(needs_generation(item) for item in arguments.values())
    if isinstance(arguments, (list, tuple)):
        return any(needs_generation(item) for item in arguments)
    return False


# ---------- разрешение аргументов ----------
def build_generate_prompt(goal: str, steps: list, context: str) -> tuple[str, str]:
    """Сообщения второй фазы: цель, спорные шаги и журнал уже выполненных шагов.

    Шаги передаются целиком (с аргументами и причиной), а не одними номерами: модели
    нужен и путь, и то, зачем шаг делается, — иначе ``new_text`` не на что опереть.
    """
    payload = {"steps": [{"step_index": step.get("step_index"), "tool": step.get("tool"),
                          "arguments": step.get("arguments")} for step in steps]}
    user = "\n\n".join([
        f"Цель: {normalize_goal(goal)}",
        "Шаги, которым нужны конкретные аргументы:\n"
        + json.dumps(payload, ensure_ascii=False, indent=1),
        f"Журнал выполненных шагов:\n{context or 'шагов ещё нет'}",
    ])
    return GENERATE_SYSTEM_PROMPT, user


def parse_generate(text: str, indices: list) -> Optional[dict]:
    """Аргументы для запрошенных шагов: ``None`` — если хоть один не пришёл.

    Возвращается словарь ``{step_index: arguments}``; неполный ответ считается
    неудачей целиком (``None``), потому что частично заполненный план всё равно не
    исполнить.
    """
    payload = first_json_object(text or "")
    if payload is None:
        return None
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return None
    wanted = {int(index) for index in indices}
    found: dict = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        try:
            index = int(step.get("step_index"))
        except (TypeError, ValueError):
            continue
        arguments = step.get("arguments")
        if index in wanted and isinstance(arguments, dict) and arguments:
            found[index] = dict(arguments)
    return found if wanted <= set(found) else None
