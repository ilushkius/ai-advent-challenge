"""Терпимый разбор JSON из ответа модели (день 34).

Модель отвечает JSON-объектом не всегда: она оборачивает его в ```json-блок,
добавляет пояснение до или после, а иногда и то и другое. Поэтому «взять первый
сбалансированный ``{...}``» — отдельное правило, и оно живёт здесь: им пользуются и
план шагов (``file_assistant.parse_plan``), и разрешение аргументов
(``file_assistant.parse_generate``), и планировщик оркестрации
(``orchestration_plan.parse_plan``, день 20).

Скобки считаются с учётом строк и экранирования: ``{`` внутри строкового значения не
должен сдвигать баланс, иначе план с текстом в аргументах («{"content": "}"}»)
разбирался бы неверно. Модуль чистый: ``json`` и стандартная библиотека, ни сети, ни
модели, ни БД.
"""
from __future__ import annotations

import json

__all__ = ["first_json_object"]


def first_json_object(text: str) -> dict | None:
    """Первый сбалансированный объект JSON в тексте (``None`` — не найден).

    Возвращается только объект: список или строка в корне ответа не план, и
    вызывающий код различает «модель ответила не тем» и «модель не ответила» сам.
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
