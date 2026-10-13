"""Отчёт дня 32: ревью в markdown для комментария PR и файла отчёта.

Отделён от ``code_review`` (контракт ревью) по читателю и по лимиту строк: правила
разбора ответа модели нужны службе, а разметка — только скриптам
(``scripts/run_local_pr_review.py`` пишет отчёт, ``scripts/gh_review_comment.py``
публикует комментарий в PR). Markdown у обоих один и тот же, поэтому разделы
фиксированы: баги с файлом и строкой, архитектурные проблемы с рекомендацией,
рекомендации, риски по приоритетам, источники RAG и предупреждения шагов; полный
ответ модели убран под ``<details>`` — он нужен для проверки, но не должен закрывать
собой структуру.

Модуль чистый: ни диска, ни модели. ``upsert_report_section`` работает с ТЕКСТОМ
отчёта, а не с файлом — запись файла остаётся на скрипте, как и выбор пути.
"""
from __future__ import annotations

from typing import Sequence

from .code_review import (MAX_REVIEW_CHARS, PRIORITY_LABELS, REPORT_TITLE,
                          normalize_priority)

__all__ = ["SECTION_MARKER", "render_markdown", "report_header", "upsert_report_section"]

#: Маркер секции отчёта: по нему скрипт находит границы СВОЕЙ секции. HTML-комментарий
#: не виден в markdown-просмотре, а разбор становится однозначным: в теле секции есть
#: свои заголовки ``##`` (``## 🤖 AI-ревью: …``), поэтому «следующий заголовок» как
#: граница не годится — по нему замена секции оставляла бы старое тело под новым.
SECTION_MARKER = "<!-- section: {title} -->"


def _cell(value: object) -> str:
    """Значение ячейки таблицы: переводы строк и ``|`` ломают разметку таблицы."""
    return " ".join(str(value or "").split()).replace("|", "\\|") or "—"


def _priority(priority: object) -> str:
    """Приоритет с подписью для человека: ``P0 (критично)``."""
    code = normalize_priority(priority)
    return f"{code} ({PRIORITY_LABELS[code]})"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    """Строки markdown-таблицы: шапка, разделитель и данные; пусто — одна строка."""
    if not rows:
        return ["— не найдено"]
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows)
    return lines


def _bullets(header: str, items: Sequence[str], empty: str = "— не найдено") -> list[str]:
    """Раздел списком: заголовок и пункты; пусто — строка ``empty``."""
    lines = [header, ""]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append(empty)
    return lines


def render_markdown(record: dict, *, label: str = "") -> str:
    """Ревью в markdown: один и тот же текст идёт в комментарий PR и в отчёт.

    Разделы печатаются всегда, даже пустые: «Рекомендации — не найдено» читается
    лучше, чем отсутствие раздела, по которому непонятно, был он или нет.
    """
    data = dict(record or {})
    bugs = list(data.get("bugs") or [])
    architecture = list(data.get("architecture_issues") or [])
    recommendations = [str(item) for item in data.get("recommendations") or []]
    risks = list(data.get("risks") or [])
    sources = list(data.get("sources") or [])
    warnings = [str(item) for item in data.get("warnings") or []]
    changed = [str(item) for item in data.get("changed_files") or []]
    title = str(label or "").strip() or "без метки"
    lines = [f"## 🤖 AI-ревью: {title}", "",
             f"_Провайдер: {data.get('provider') or ''} · "
             f"{int(data.get('duration_ms') or 0)} мс · файлов: {len(changed)} · "
             f"источников RAG: {len(sources)}_", ""]
    lines += _bullets("### Изменённые файлы", [f"`{path}`" for path in changed],
                      empty="— файлов нет")
    lines += ["", "### Потенциальные баги", ""]
    lines += _table(["Файл", "Строка", "Приоритет", "Проблема"],
                    [[item.get("file"), item.get("line"), _priority(item.get("priority")),
                      item.get("issue")] for item in bugs])
    lines += ["", "### Архитектурные проблемы", ""]
    lines += _table(["Файл", "Приоритет", "Проблема", "Рекомендация"],
                    [[item.get("file"), _priority(item.get("priority")),
                      item.get("issue"), item.get("recommendation")]
                     for item in architecture])
    lines += _bullets("### Рекомендации", recommendations)
    lines += ["", "### Риски (P0 — P3)", ""]
    lines += _table(["Приоритет", "Файл", "Риск"],
                    [[_priority(item.get("priority")), item.get("file"), item.get("risk")]
                     for item in risks])
    lines += _bullets("### Источники RAG",
                      [f"`{item.get('source') or ''}` · {item.get('section') or '—'} · "
                       f"{item.get('score')}" for item in sources])
    lines += _bullets("### Предупреждения", warnings, empty="— нет")
    review_text = str(data.get("review_text") or "").strip()
    if review_text:
        lines += ["", "<details><summary>Полный ответ модели</summary>", "",
                  review_text[:MAX_REVIEW_CHARS], "", "</details>"]
    return "\n".join(lines) + "\n"


def report_header() -> str:
    """Заголовок отчёта: что в нём и какими командами добавляется секция."""
    return "\n".join([
        REPORT_TITLE, "",
        "Отчёт собирает скрипт `scripts/run_local_pr_review.py`: каждая секция — одно",
        "ревью (пара ref-ов или файл diff-а). Повторный прогон с тем же заголовком секции",
        "заменяет её, новый заголовок добавляет ещё одну; границы секции отмечены",
        "невидимым в просмотре маркером `<!-- section: … -->`.", "",
        "```bash",
        "uv run python scripts/run_local_pr_review.py --base day30 --head day31",
        "uv run python scripts/run_local_pr_review.py --diff-file docs/reports/synthetic_pr.diff \\",
        '  --pr-label "synthetic PR: прямой SQL из слоя служб" \\',
        '  --section-title "Синтетический PR: прямой SQL из службы вместо хранилища"',
        "```",
    ])


def upsert_report_section(text: str, title: str, body: str) -> str:
    """Текст отчёта с секцией ``{title}``: одноимённая заменяется, новой дописывается.

    Отчёт переживает несколько прогонов: заменять файл целиком значило бы терять
    предыдущие примеры, а дописывать всегда — копить дубли при повторном запуске.
    Границы секции задаёт маркер (``SECTION_MARKER``), а не заголовок: в теле секции
    есть свои заголовки второго уровня.
    """
    heading = f"## {title}"
    marker = SECTION_MARKER.format(title=str(title))
    current = str(text or "")
    lines = current.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if line.strip() == marker), None)
    if start is None:
        section = f"{marker}\n\n{heading}\n\n{body}\n"
        if not current.strip():
            return f"{report_header()}\n\n{section}"
        return current.rstrip("\n") + "\n\n---\n\n" + section
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("<!-- section:")), len(lines))
    merged = (lines[:start] + [marker, "", heading, ""]
              + str(body or "").splitlines() + [""] + lines[end:])
    return "\n".join(merged).rstrip("\n") + "\n"
