"""Маппинг данных между шагами пайплайна: ссылки ``$steps.``, ``{имя}`` и условия.

Здесь решается, «передаются ли данные между инструментами»: аргументы шага — это
шаблон, в котором ссылки заменяются значениями. Правила разрешения:

1. строка РОВНО вида ``$steps.<i>.<путь>`` → значение по пути, как есть (список
   остаётся списком: ``items`` следующего шага — это настоящий массив, а не JSON
   строкой);
2. иначе каждая подстрока ``$steps....`` внутри строки заменяется строковым
   представлением значения, затем подставляются ``{имя}``;
3. ``{имя}`` ровно целиком занимает строку → значение аргумента запуска как есть
   (число остаётся числом, список — списком);
4. иначе ``{имя}`` подставляются через ``str(value)``;
5. не строка — как есть (словари и списки обходятся рекурсивно, поэтому можно
   писать ``{"items": "$steps.0.structured.items"}`` внутри вложенной структуры).

``evaluate_guard`` отвечает на вопрос «идти ли дальше»: четыре оператора
(``non_empty``, ``empty``, ``equals``, ``contains``) и сообщение условия, которое
попадает в итог прогона. Отсутствующий путь или незаполненная заглушка — явная
ошибка ``PipelineMappingError``: молча подставить пустую строку значило бы
отправить инструменту мусор вместо данных.

Модуль чистый: конфигурация и стандартная библиотека, никаких HTTP и БД.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .pipeline_spec import (
    DEFAULT_GUARD_MESSAGE,
    GUARD_CONTAINS,
    GUARD_EMPTY,
    GUARD_EQUALS,
    GUARD_NON_EMPTY,
    GUARD_OPS,
)

#: Префикс ссылки на результат шага.
STEPS_PREFIX = "$steps."

#: Ссылка внутри строки: ``$steps.0.structured.items`` (сегменты через точку).
_STEP_REF_RE = re.compile(r"\$steps\.[A-Za-z0-9_.]+")

#: Заглушка аргумента запуска: ``{query}``, ``{limit}``.
_ARG_RE = re.compile(r"\{(\w+)\}")


class PipelineMappingError(ValueError):
    """Поле шага не найдено в аргументах запуска или в результатах предыдущих шагов."""


def resolve_mapping(spec: Any, context: Mapping[str, Any]) -> Any:
    """Разрешает шаблон аргументов шага в конкретные значения.

    ``context`` — ``{"initial": {...аргументы запуска...}, "steps": [<выход шага 0>, …]}``.
    """
    if isinstance(spec, Mapping):
        return {key: resolve_mapping(value, context) for key, value in spec.items()}
    if isinstance(spec, (list, tuple)):
        return [resolve_mapping(value, context) for value in spec]
    if isinstance(spec, str):
        return _resolve_string(spec, context)
    return spec


def _resolve_string(value: str, context: Mapping[str, Any]) -> Any:
    """Строка шаблона: одиночная ссылка — как есть, иначе — подстановка в текст."""
    exact = _exact_step_ref(value)
    if exact is not None:
        return resolve_path(exact, context)
    text = value
    for ref in _STEP_REF_RE.findall(text):
        text = text.replace(ref, str(resolve_path(ref, context)))
    initial = context.get("initial") or {}
    whole = _ARG_RE.fullmatch(text)
    if whole is not None:
        if whole.group(1) not in initial:
            raise PipelineMappingError(
                f"Аргумент запуска «{whole.group(1)}» не передан"
            )
        return initial[whole.group(1)]

    def _substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in initial:
            raise PipelineMappingError(f"Аргумент запуска «{name}» не передан")
        return str(initial[name])

    return _ARG_RE.sub(_substitute, text)


def _exact_step_ref(value: str) -> str | None:
    """Строка целиком является ссылкой ``$steps....`` (без текста вокруг)."""
    stripped = value.strip()
    if stripped.startswith(STEPS_PREFIX) and _STEP_REF_RE.fullmatch(stripped):
        return stripped
    return None


def resolve_path(path: str, context: Mapping[str, Any]) -> Any:
    """Значение по пути ``$steps.<i>.<сегменты>`` (числовой сегмент — индекс списка)."""
    if not path.startswith(STEPS_PREFIX):
        raise PipelineMappingError(f"Путь «{path}» не найден в результатах шагов")
    segments = path[len(STEPS_PREFIX):].split(".")
    if not segments or not segments[0].isdigit():
        raise PipelineMappingError(f"Путь «{path}» не найден в результатах шагов")
    steps = context.get("steps") or []
    index = int(segments[0])
    if index >= len(steps):
        raise PipelineMappingError(f"Путь «{path}» не найден в результатах шагов")
    current: Any = steps[index]
    for segment in segments[1:]:
        current = _dig(current, segment)
        if current is _MISSING:
            raise PipelineMappingError(f"Путь «{path}» не найден в результатах шагов")
    return current


_MISSING = object()


def _dig(value: Any, segment: str) -> Any:
    """Шаг по пути: число — индекс списка, иначе ключ словаря."""
    if isinstance(value, Mapping):
        return value.get(segment, _MISSING)
    if isinstance(value, (list, tuple)):
        if segment.isdigit() and int(segment) < len(value):
            return value[int(segment)]
        return _MISSING
    return _MISSING


def evaluate_guard(guard: Mapping[str, Any],
                   context: Mapping[str, Any]) -> tuple[bool, str]:
    """Проверяет условие шага: ``(выполнено, сообщение)``.

    Сообщение — текст из условия или ``DEFAULT_GUARD_MESSAGE``: оно попадает в
    итог прогона (``message``) и в поле ``error_message`` самого шага.
    """
    path = guard.get("path")
    op = guard.get("op")
    message = guard.get("message") or DEFAULT_GUARD_MESSAGE
    if op not in GUARD_OPS:
        raise PipelineMappingError(
            f"Условие «{op}» не поддержано. Допустимы: " + ", ".join(GUARD_OPS)
        )
    if not isinstance(path, str) or not path:
        raise PipelineMappingError("Условию нужен путь «path»")
    value = resolve_path(path, context)
    if op == GUARD_NON_EMPTY:
        return bool(_non_empty(value)), message
    if op == GUARD_EMPTY:
        return (not _non_empty(value)), message
    if op == GUARD_EQUALS:
        if "value" not in guard:
            raise PipelineMappingError("Условию equals нужен ключ «value»")
        return value == guard["value"], message
    return _contains(value, guard.get("value")), message


def _non_empty(value: Any) -> bool:
    """Непустое значение: непустые список, словарь, строка; ``None`` — пустое."""
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) > 0
    return True


def _contains(value: Any, needle: Any) -> bool:
    """Вхождение: подстрока в строке или элемент в списке."""
    if isinstance(value, str):
        return str(needle) in value
    if isinstance(value, (list, tuple, set)):
        return needle in value
    if isinstance(value, Mapping):
        return needle in value
    return False
