"""Журнал, предполагаемый diff и вердикт прогона (день 34).

Три вещи, которые нужны после исполнения плана:

- ``render_step_context`` — журнал шагов текстом: он уходит в промпт разрешения
  аргументов и в промпт сводки, а в отчёте прогона по нему восстанавливают, что
  именно делал ассистент;
- ``presumed_diff`` — diff БЕЗ обращения к диску: в режиме ``dry_run`` файлы не
  меняются, но пользователь должен увидеть, что было бы записано, и сравнить это со
  своими ожиданиями ДО правки;
- ``verdict`` — одна строка о том, чем подтверждён результат: сбоем шага, провалом
  прогона, отсутствием изменения или достигнутой целью.

Дифы в обоих случаях — формат ``unified_diff`` (тот же, что у ``git diff`` и у
инструмента ``get_file_diff``), поэтому предполагаемый и настоящий diff читаются
глазами одинаково. Отличие только в шапке: у настоящего её рисует git.

Тела правок и содержимое файлов сюда не логируются и нигде не кэшируются: функция
считает результат по переданным аргументам и возвращает текст.
"""
from __future__ import annotations

import difflib
import json
from typing import Any

from .file_assistant import (
    CONTEXT_STEP_CHARS,
    MAX_CONTEXT_CHARS,
    NO_PRESUMED_DIFF,
    STATUS_FAILED,
    TOOL_APPLY_PATCH,
    TOOL_WRITE_FILE,
    VERDICT_DONE,
    VERDICT_DRY_RUN,
    VERDICT_EXPECTED_MISSING,
    VERDICT_RUN_FAILED,
    VERDICT_STEP_FAILED,
)

__all__ = ["presumed_diff", "render_step_context", "verdict"]


def render_step_context(steps: list, limit: int = MAX_CONTEXT_CHARS) -> str:
    """Журнал шагов текстом для промпта и отчёта: статус, время, аргументы, результат.

    Аргументы и результат усекаются до ``CONTEXT_STEP_CHARS`` на шаг, общий текст — до
    ``limit``: ``read_file`` длинного файла иначе вытеснил бы из промпта всё
    остальное, включая шаги, о которых модели и надо судить.
    """
    blocks = []
    for step in steps:
        block = "\n".join([
            f"[{step.get('step_index')}] {step.get('tool')}: {step.get('status')}, "
            f"{int(step.get('duration_ms') or 0)} мс",
            f"причина: {step.get('reason') or '—'}",
            f"аргументы: {_short(_json(step.get('arguments')), CONTEXT_STEP_CHARS)}",
            f"результат: {_short(_json(step.get('result')), CONTEXT_STEP_CHARS)}",
        ])
        if step.get("error"):
            block += f"\nошибка: {step['error']}"
        blocks.append(block)
    text = "\n\n".join(blocks)
    return text if len(text) <= limit else text[:limit] + "\n… (журнал усечён)"


def presumed_diff(path: str, current: str, tool: str, arguments: dict) -> str:
    """Предполагаемый diff правки без обращения к диску (режим ``dry_run`` и тесты).

    Три случая, ровно как у настоящих инструментов: ``write_file`` с ``overwrite``
    сравнивает текущее содержимое с новым, ``write_file`` с ``append`` — с
    дописанным вариантом (с добавленным переводом строки, как делает сервер),
    ``apply_patch`` — с результатом замены первого вхождения ``old_text``. Если
    ``old_text`` в файле нет, diff пуст: служба пометит шаг неуспешным по
    ``REASON_PATCH_ANCHOR``, а не покажет выдуманную правку.
    """
    mode = str(arguments.get("mode") or "overwrite")
    after = str(arguments.get("new_text") or "")
    if tool == TOOL_WRITE_FILE:
        content = str(arguments.get("content") or "")
        if mode == "append":
            gap = "\n" if current and not current.endswith("\n") else ""
            after = current + gap + content
        else:
            after = content
    elif tool == TOOL_APPLY_PATCH:
        anchor = str(arguments.get("old_text") or "")
        if not anchor or anchor not in current:
            return ""
        after = current.replace(anchor, after, 1)
    else:
        return ""
    if after == current:
        return NO_PRESUMED_DIFF
    lines = list(difflib.unified_diff(current.splitlines(), after.splitlines(),
                                     fromfile=f"a/{path}", tofile=f"b/{path}",
                                     lineterm=""))
    return "\n".join(lines) if lines else NO_PRESUMED_DIFF


def verdict(record: dict, scenario: dict) -> str:
    """Вердикт строки демо-прогона: чем именно подтверждён результат.

    Порядок проверок — от самого сильного факта к самому слабому: сбой шага (видно,
    что упало), провал прогона, режим ``dry_run`` (файлы не менялись по замыслу),
    отсутствие ожидаемого файла (прогон прошёл, но не туда) и только потом «цель
    достигнута».
    """
    for step in record.get("steps_executed") or []:
        if not step.get("ok", True):
            return VERDICT_STEP_FAILED.format(index=step.get("step_index"),
                                              tool=step.get("tool"),
                                              error=step.get("error") or "—")
    if str(record.get("status") or "") == STATUS_FAILED:
        return VERDICT_RUN_FAILED
    if record.get("dry_run"):
        return VERDICT_DRY_RUN
    modified = set(record.get("files_modified") or [])
    created = set(record.get("files_created") or [])
    for path in scenario.get("expect_modified") or ():
        if path not in modified:
            return VERDICT_EXPECTED_MISSING.format(path=path)
    for path in scenario.get("expect_created") or ():
        if path not in created:
            return VERDICT_EXPECTED_MISSING.format(path=path)
    return VERDICT_DONE


def _json(value: Any) -> str:
    """Значение для журнала: JSON (одна строка на поле после ``_short``)."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _short(text: object, limit: int) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"
