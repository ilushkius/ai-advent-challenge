"""Построение плана оркестрации: каталог инструментов, промпт и разбор ответа.

План шагов может предложить модель DeepSeek — и тогда «какие инструменты с каких
серверов вызвать и в каком порядке» решает она, читая КАТАЛОГ ФЛОТА (имя сервера,
инструменты, описания, ``input_schema``). Здесь живёт всё, что для этого нужно, и
ничего, что требует сети: сам вызов модели — в
``backend/services/orchestration_planner.py``, поэтому разбор и промпт тестируются
офлайн.

Три вещи в модуле:

- ``catalog_text`` — каталог флота текстом, сгруппированный по серверам: модель
  должна видеть, ЧЕЙ инструмент она выбирает (требование дня);
- ``build_plan_prompt`` — системное сообщение с правилами и примером ответа плюс
  запрос пользователя и каталог;
- ``parse_plan`` — разбор ответа: первый ``{...}``-блок, JSON, ``validate_plan``;
  любая неудача — ``None`` (не исключение), потому что это лишь один из способов
  получить план, и план-фолбэк у оркестратора всегда есть.

``heuristic_plan`` — план без модели: шаги встроенного сценария, отфильтрованные по
доступным именам инструментов (с перенумерацией ссылок ``$steps.<i>``). Так демо и
тесты работают без ключа DeepSeek.

Модуль чистый: ``json``, ``re`` и стандартная библиотека.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .mcp_tools import MCPFleetTool
from .orchestration_spec import (
    HEURISTIC_PLAN_NAME,
    DEMO_PLAN,
    REASON_BAD_QUERY,
    OrchestrationRejected,
    validate_plan,
)

#: Системная инструкция планировщика. Ключевая фраза дня — про выбор инструментов
#: с РАЗНЫХ серверов и их порядок; она же проверяется тестом.
PLANNER_SYSTEM_PROMPT = (
    "Ты — планировщик вызовов MCP-инструментов. Определи, какие инструменты с "
    "каких серверов нужно вызвать и в каком порядке, чтобы выполнить запрос "
    "пользователя. Серверы и их инструменты перечислены в каталоге ниже: "
    "инструмент принадлежит тому серверу, под именем которого он записан.\n"
    "Правила:\n"
    "1. Отвечай ТОЛЬКО объектом JSON, без пояснений и без markdown-обёртки.\n"
    "2. Формат: {\"name\": \"<короткое имя плана>\", \"steps\": [{\"tool\": "
    "\"<имя инструмента>\", \"args\": {<аргументы>}}]}.\n"
    "3. Используй только те инструменты, что есть в каталоге; порядок шагов — "
    "порядок исполнения.\n"
    "4. Данные между шагами передавай ссылками: \"$steps.<номер шага с нуля>."
    "<путь поля результата>\" (например \"$steps.0.structured.items\"), а "
    "аргументы запуска — заглушками вида \"{query}\".\n"
    "5. Не выдумывай инструменты, которых нет в каталоге, и не вызывай один "
    "инструмент дважды без необходимости."
)

#: Подсказка-пример ответа (уходит в пользовательское сообщение).
PLAN_JSON_HINT = (
    'Пример ответа: {"name": "demo", "steps": ['
    '{"tool": "search_web", "args": {"query": "{query}", "source": "posts", '
    '"limit": "{limit}"}}, '
    '{"tool": "summarize", "args": {"items": "$steps.0.structured.items", '
    '"style": "short"}}]}'
)

#: Ссылка на выход шага внутри аргументов плана.
_STEP_REF_RE = re.compile(r"\$steps\.(\d+)\.")


def catalog_text(tools: Sequence[MCPFleetTool]) -> str:
    """Каталог флота текстом: сервер, затем его инструменты с описанием и схемой."""
    if not tools:
        return "Каталог пуст: ни один сервер флота не публикует инструментов."
    grouped: dict[str, list[MCPFleetTool]] = {}
    for item in tools:
        grouped.setdefault(item.server, []).append(item)
    lines: list[str] = []
    for server, items in grouped.items():
        lines.append(f"Сервер {server} (инструментов: {len(items)}):")
        for item in items:
            lines.append(f"- {item.name}: {item.description or 'без описания'}")
            schema = item.tool.input_schema
            if schema:
                lines.append(f"  аргументы: {json.dumps(schema, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines).strip()


def build_plan_prompt(query: str, tools: Sequence[MCPFleetTool]) -> list[dict[str, str]]:
    """Сообщения для модели: правила и каталог — в системе, запрос — в пользователе."""
    user = (
        f"Запрос пользователя: {query}\n\n"
        f"Каталог серверов и инструментов:\n{catalog_text(tools)}\n\n"
        f"{PLAN_JSON_HINT}"
    )
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_plan(text: str) -> dict | None:
    """План из ответа модели: ``None``, если ответ не разобран или негоден.

    Разбор намеренно терпимый: модель может обернуть JSON в markdown или добавить
    пояснение после него. Берётся первый сбалансированный ``{...}``-блок, из него
    читается JSON и проверяется ``validate_plan`` — негодный план равен отсутствию
    плана (оркестратор перейдёт на эвристику и запишет это в журнал).
    """
    payload = _first_json_object(text or "")
    if payload is None:
        return None
    try:
        plan = validate_plan(payload)
    except OrchestrationRejected:
        return None
    return plan


def _first_json_object(text: str) -> dict | None:
    """Первый сбалансированный объект JSON в тексте (``None`` — не найден).

    Скобки считаются с учётом строк и экранирования: ``{`` внутри строкового
    значения не должен сдвигать баланс, иначе план с текстом в аргументах
    («{"content": "}"}») разбирался бы неверно.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start:index + 1]
                    try:
                        parsed = json.loads(chunk)
                    except ValueError:
                        break
                    return parsed if isinstance(parsed, dict) else None
        start = text.find("{", start + 1)
    return None


def heuristic_plan(query: str, tool_names: Sequence[str]) -> dict:
    """План без модели: шаги демо-сценария, выполнимые доступными инструментами.

    Шаг выпадает, если его инструмента нет в каталоге флота ИЛИ если выпал шаг, на
    выход которого он ссылается (``$steps.<i>``): ссылка на несуществующий шаг
    сломала бы прогон ошибкой маппинга. Оставшиеся ссылки перенумеровываются по
    новым позициям, поэтому «цепочка из двух шагов» из середины сценария работает
    так же, как полная.
    """
    available = set(tool_names)
    kept: list[dict[str, Any]] = []
    old_to_new: dict[int, int] = {}
    for index, step in enumerate(DEMO_PLAN["steps"]):
        if step["tool"] not in available:
            continue
        args = step.get("args") or {}
        refs = _step_refs(args)
        if any(ref not in old_to_new for ref in refs):
            continue
        old_to_new[index] = len(kept)
        kept.append({"tool": step["tool"], "args": _remap(args, old_to_new)})
    if not kept:
        raise OrchestrationRejected(
            "Ни один шаг сценария не выполним: флот не публикует нужных инструментов",
            REASON_BAD_QUERY,
        )
    return {"name": HEURISTIC_PLAN_NAME, "steps": kept}


def _step_refs(value: Any) -> set[int]:
    """Номера шагов, на выход которых ссылаются аргументы (рекурсивно)."""
    if isinstance(value, Mapping):
        found: set[int] = set()
        for item in value.values():
            found |= _step_refs(item)
        return found
    if isinstance(value, (list, tuple)):
        found = set()
        for item in value:
            found |= _step_refs(item)
        return found
    if isinstance(value, str):
        return {int(number) for number in _STEP_REF_RE.findall(value)}
    return set()


def _remap(value: Any, old_to_new: Mapping[int, int]) -> Any:
    """Перенумеровывает ссылки ``$steps.<i>`` по карте сохранившихся шагов."""
    if isinstance(value, Mapping):
        return {key: _remap(item, old_to_new) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap(item, old_to_new) for item in value]
    if isinstance(value, str):
        return _STEP_REF_RE.sub(
            lambda match: f"$steps.{old_to_new[int(match.group(1))]}.",
            value,
        )
    return value
