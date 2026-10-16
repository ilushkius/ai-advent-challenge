"""Файлы релиза (день 35): чтение текущих текстов, план правки и запись через MCP.

Вынесено из ``release_service.py`` (предел 400 строк) и по предмету: служба решает,
ЧТО собрать (коммиты, версия, группы, проверки), а этот модуль — КАК прочитать и
записать три файла релиза и что показать в предпросмотре. Правило идемпотентности
(«раздел этой версии уже есть — файл не меняется») живёт здесь же, потому что оно про
файлы, а не про версию.

Два инварианта, которые держат предпросмотр честным:

- diff считается ТЕМ ЖЕ правилом, что и правка: ``plan_files`` → ``diff_preview`` →
  ``write``. Вставка раздела в ``CHANGELOG.md`` (файл newest-first) идёт через
  ``release.insert_changelog_section`` и там, и здесь, поэтому ``dry_run`` показывает
  ровно то, что было бы записано;
- файл, который не будет записан (``skipped``), показывается ПУСТЫМ diff-ом: обещать
  правку, которой не случится, нельзя, и причина стоит рядом в ``note``.

Ошибки MCP — ``ReleaseError`` (роутер отвечает 500). Класс объявлен здесь, а не в
службе: этот модуль один касается транспорта, и он же решает, что «инструмент вернул
ошибку» — сбой всего прогона, а не строки отчёта. Служба реэкспортирует его.
"""
from __future__ import annotations

from typing import Any

from shared.logging_utils import get_logger

from ..domain import release

logger = get_logger(__name__)

__all__ = ["ReleaseError", "call", "diff_preview", "plan_files", "read", "try_call",
           "write"]


class ReleaseError(RuntimeError):
    """MCP-сервер файлов недоступен или инструмент вернул ошибку (роутер отвечает 500)."""


def call(mcp: Any, tool: str, arguments: dict) -> Any:
    """Вызов инструмента сервера файлов; отказ — ``ReleaseError``."""
    ok, payload, error, _ms = mcp.call(tool, dict(arguments))
    if not ok:
        logger.warning("Релиз: инструмент %s не сработал: %s", tool, error)
        raise ReleaseError(error or release.WARN_TOOL_FAILED.format(tool=tool, error=""))
    return payload


def try_call(mcp: Any, tool: str, arguments: dict) -> tuple:
    """Вызов инструмента, отказ которого не критичен: ``(успех, результат, ошибка)``."""
    ok, payload, error, _ms = mcp.call(tool, dict(arguments))
    return bool(ok), payload, str(error or "")


def read(mcp: Any, path: str,
         max_bytes: int = release.RELEASE_MAX_READ_BYTES) -> tuple[str | None, bool]:
    """Читает файл инструментом ``read_file``: ``(текст, признак обрезки)``.

    ``None`` вместо текста означает «файла нет или чтение не удалось»: отсутствие
    ``CHANGELOG.md`` — штатный первый релиз, а не сбой, и решение принимает служба.
    """
    ok, payload, error, _ms = mcp.call(release.TOOL_READ_FILE,
                                       {"path": path, "max_bytes": int(max_bytes)})
    if not ok or not isinstance(payload, dict):
        logger.info("Релиз: файл %s не прочитан: %s", path, error)
        return None, False
    return str(payload.get("content") or ""), bool(payload.get("truncated"))


def plan_files(version: str, current_changelog: str,
               current_readme: str) -> list[dict]:
    """План правки трёх файлов: чем меняется, пропущен ли и почему.

    Идемпотентность: раздел версии, который уже есть в ``CHANGELOG.md``, и раздел
    результата, который уже есть в ``README.md``, помечаются ``skipped`` — повторный
    прогон с той же версией не удваивает разделы. Пропавший ``README.md`` тоже
    пропускается: дописывать корневой файл с нуля — не работа релиза.
    """
    heading = release.release_heading(version)
    anchor = release.changelog_anchor(current_changelog)
    changelog_skip = heading in current_changelog
    readme_skip = (release.README_SECTION_TITLE in current_readme
                   or not current_readme.strip())
    return [
        _change(release.CHANGELOG_PATH,
                release.TOOL_APPLY_PATCH if anchor else release.TOOL_WRITE_FILE,
                changelog_skip, heading),
        _change(release.RELEASE_NOTES_PATH, release.TOOL_WRITE_FILE, False, heading),
        _change(release.README_PATH, release.TOOL_APPLY_PATCH, readme_skip,
                release.README_SECTION_TITLE),
    ]


def diff_preview(changes: list[dict], section: str, notes_text: str,
                 readme_section: str, current_changelog: str, current_readme: str,
                 current_notes: str) -> dict:
    """Предпросмотр правки каждого файла; пропущенный файл показывается пустым."""
    proposed = {
        release.CHANGELOG_PATH: (
            release.insert_changelog_section(current_changelog, section),
            current_changelog),
        release.RELEASE_NOTES_PATH: (notes_text, current_notes),
        release.README_PATH: (
            current_readme.replace(release.README_ANCHOR,
                                   f"{readme_section}\n{release.README_ANCHOR}", 1),
            current_readme),
    }
    preview = {}
    for entry in changes:
        new, old = proposed.get(entry["path"], ("", ""))
        preview[entry["path"]] = "" if entry["skipped"] else release.unified_diff(
            entry["path"], old, new)
    return preview


def write(entry: dict, section: str, notes_text: str, readme_section: str,
          current_changelog: str, mcp: Any, notes: list[str]) -> None:
    """Записывает файл плана выбранным инструментом; сбой — в поле записи и в заметки.

    Сбой одного файла не останавливает остальные: раздел CHANGELOG, заметки и README
    независимы, и «два из трёх записаны» полезнее, чем «прогон упал на первом».
    """
    path = entry["path"]
    if path == release.CHANGELOG_PATH:
        anchor = release.changelog_anchor(current_changelog)
        arguments = ({"path": path, "old_text": anchor, "new_text": f"{section}\n{anchor}"}
                     if anchor else
                     {"path": path,
                      "content": release.insert_changelog_section(current_changelog,
                                                                  section),
                      "mode": "overwrite"})
    elif path == release.RELEASE_NOTES_PATH:
        arguments = {"path": path, "content": notes_text, "mode": "overwrite"}
    else:
        arguments = {"path": path, "old_text": release.README_ANCHOR,
                     "new_text": f"{readme_section}\n{release.README_ANCHOR}"}
    try:
        call(mcp, entry["tool"], arguments)
    except ReleaseError as exc:
        entry["ok"] = False
        entry["error"] = str(exc)
        notes.append(release.WARN_WRITE_FAILED.format(path=path, error=exc))
        logger.warning("Релиз: файл %s не записан: %s", path, exc)
        return
    entry["ok"] = True
    entry["error"] = ""


def _change(path: str, tool: str, skipped: bool, heading: str) -> dict:
    """Запись плана правки файла: чем меняется, пропущена ли и почему."""
    note = (release.WARN_SECTION_EXISTS.format(heading=heading, path=path)
            if skipped else "")
    return {"path": path, "tool": tool, "skipped": bool(skipped), "ok": False,
            "error": "", "note": note}
