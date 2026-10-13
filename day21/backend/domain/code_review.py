"""AI-ревью PR (день 32): контракт ревью — ответ модели, diff и контекст.

Граница модуля: только чистые правила и тексты — ни HTTP, ни диска, ни модели, ни
индекса. Сеть, MCP-инструменты и поиск по корпусу живут в службе
(``services/code_review_service``), а здесь:

- **что спросить у модели** — ``SYSTEM_PROMPT`` и ``JSON_CONTRACT``: ревью приходит
  структурой (баги, архитектурные проблемы, рекомендации, риски P0–P3), потому что
  свободный текст некуда положить — ни в таблицу, ни в комментарий PR;
- **что сделать с diff-ом** — ``truncate_diff`` (предел 2000 строк),
  ``changed_files_from_diff``, ``added_lines`` и ``context_query``: список файлов и
  запрос к индексу собираются из самого diff-а, без повторного чтения файлов;
- **как разобрать ответ** — ``normalize_review``: приходит и ``p`` вместо ``P``, и
  строка вместо объекта, и текст без JSON; разбор терпимый, а признак ``parsed``
  честно говорит, что структуры нет.

Приоритеты (``P0``…``P3``) приводятся к каноническому виду и сортируются здесь, а
разметка отчёта и комментария PR лежит в ``code_review_report`` — она нужна только
скриптам, а контракт ревью читает служба.
"""
from __future__ import annotations

import json
import re
from typing import Mapping, Optional, Sequence

from .dev_assistant import TOOL_CHANGED_FILES, TOOL_PR_DIFF

#: Идентификатор в журнале расходов (``llm_usage``): вызовы ревью видно отдельно.
AGENT_ID = "code-review"
#: Приоритеты находок: P0 — критично, P3 — минорно. Порядок задаёт и сортировку.
PRIORITY_P0, PRIORITY_P1, PRIORITY_P2, PRIORITY_P3 = "P0", "P1", "P2", "P3"
PRIORITIES = (PRIORITY_P0, PRIORITY_P1, PRIORITY_P2, PRIORITY_P3)
PRIORITY_DEFAULT = PRIORITY_P3
PRIORITY_LABELS = {PRIORITY_P0: "критично", PRIORITY_P1: "важно",
                   PRIORITY_P2: "средне", PRIORITY_P3: "минорно"}
#: Сколько фрагментов берёт поиск и сколько изменённых файлов ищется в индексе кода.
DEFAULT_TOP_K = 5
MAX_CONTEXT_FILES = 8
#: Предел diff-а в промпте и пределы запроса к индексу (общий и по одному файлу).
MAX_DIFF_LINES = 2000
QUERY_MAX_CHARS = 800
FILE_QUERY_MAX_CHARS = 500
#: Путь отчёта по умолчанию (от корня дня), заголовок и предел текста модели.
REPORT_PATH = "docs/reports/code_review_demo.md"
REPORT_TITLE = "# Отчёт дня 32: автоматическое AI-ревью кода"
#: Путь и заголовок отчёта режима GitHub (скрипт ``run_github_pr_review.py``).
GITHUB_REPORT_PATH = "docs/reports/github_pr_review.md"
GITHUB_REPORT_TITLE = "# Отчёт дня 32: ревью реального GitHub PR"
MAX_REVIEW_CHARS = 6000

#: Контракт ответа модели: он же попадает в системный промпт целиком.
JSON_CONTRACT = (
    '{"bugs": [{"file": "путь", "line": "12", "issue": "что не так", '
    '"priority": "P0"}], '
    '"architecture_issues": [{"file": "путь", "issue": "нарушение слоёв", '
    '"recommendation": "как исправить", "priority": "P1"}], '
    '"recommendations": ["рекомендация"], '
    '"risks": [{"priority": "P0", "file": "путь", "risk": "чем это грозит"}]} '
    'Поля priority — только P0, P1, P2 или P3. Если находок нет, оставь список пустым.'
)
#: Сколько находок каждого вида просит контракт. Границы обязательны: ответ идёт
#: типом задачи ``chat`` с пределом ``config.LLM_MAX_RESPONSE_TOKENS``, и без них
#: модель обрывается на середине JSON — структуру тогда не разобрать.
MAX_BUGS = 3
MAX_ARCHITECTURE = 2
MAX_RECOMMENDATIONS = 2
MAX_RISKS = 3
SYSTEM_PROMPT = (
    "Ты — senior code reviewer. Проанализируй diff и контекст. Верни "
    "структурированное ревью: 1) Потенциальные баги с указанием файла и строки. "
    "2) Архитектурные проблемы. 3) Рекомендации по улучшению. 4) Риски с приоритетами "
    "P0 (критично) — P3 (минорно). Не пиши общие фразы, указывай конкретные места. "
    f"Не больше {MAX_BUGS} багов, {MAX_ARCHITECTURE} архитектурных проблем, "
    f"{MAX_RECOMMENDATIONS} рекомендаций и {MAX_RISKS} рисков; каждое поле — одно "
    "короткое предложение. Ответ — ТОЛЬКО JSON-объект без пояснений и без "
    "markdown-обёртки, по контракту:\n" + JSON_CONTRACT)

#: Шапки блоков контекста: по ним модель видит, откуда пришли данные.
CONTEXT_DOCS_HEADER = "=== ДОКУМЕНТАЦИЯ ПРОЕКТА (фрагменты RAG) ==="
CONTEXT_CODE_HEADER = "=== КОД ИЗМЕНЁННЫХ ФАЙЛОВ (фрагменты RAG) ==="
CONTEXT_FILES_HEADER = "=== ИЗМЕНЁННЫЕ ФАЙЛЫ ==="
CONTEXT_DIFF_HEADER = "=== DIFF (base..head) ==="

#: Тексты отказов: они уходят в ``warnings``, а не стеком.
DIFF_TRUNCATED_NOTE = ("… diff обрезан: показаны первые {kept} строк из {total} "
                       "(пропущены файлы: {files})")
NO_FILES_NOTE = "(список изменённых файлов не получен)"
WARN_INDEX_EMPTY = "Индекс корпуса недоступен: {error}"
WARN_FILE_NOT_INDEXED = ("В контексте нет фрагментов файла {path}: его нет среди "
                         "источников корпуса или фрагменты не попали в выдачу поиска — "
                         "по этому файлу виден только diff")
WARN_MCP_UNAVAILABLE = "MCP-сервер разработки недоступен: {error}"
WARN_TOOL_FAILED = "MCP-инструмент {tool} вернул ошибку: {error}"
WARN_JSON = "Модель вернула не JSON: структура ревью не разобрана ({error})"
WARN_DIFF_TRUNCATED = DIFF_TRUNCATED_NOTE  # тот же текст идёт в warnings
WARN_GITHUB_COMMENT_FAILED = "Комментарий в PR не опубликован: {error}"
LLM_UNAVAILABLE_ANSWER = "Ревью недоступно: провайдер «{provider}» не ответил ({error})"
EMPTY_DIFF_ERROR = "Diff пуст: ревью нечего анализировать"
NO_DIFF_ERROR = ("Нужен diff или base и head: без них ревью нечего анализировать")

#: Заголовок diff-а, по которому берётся путь нового файла: ``diff --git a/X b/Y``.
#: Приоритет в свободной форме: ``p0``, ``P0 (критично)``, ``0``, ``"2"``.
_GIT_HEADER = "diff --git "
_PRIORITY_RE = re.compile(r"P?([0-3])")

__all__ = ["AGENT_ID", "CONTEXT_CODE_HEADER", "CONTEXT_DIFF_HEADER",
           "CONTEXT_DOCS_HEADER", "CONTEXT_FILES_HEADER", "DEFAULT_TOP_K",
           "DIFF_TRUNCATED_NOTE", "EMPTY_DIFF_ERROR", "FILE_QUERY_MAX_CHARS",
           "GITHUB_REPORT_PATH", "GITHUB_REPORT_TITLE", "JSON_CONTRACT",
           "LLM_UNAVAILABLE_ANSWER", "MAX_ARCHITECTURE", "MAX_BUGS",
           "MAX_CONTEXT_FILES", "MAX_DIFF_LINES", "MAX_RECOMMENDATIONS",
           "MAX_REVIEW_CHARS", "MAX_RISKS", "NO_DIFF_ERROR", "NO_FILES_NOTE",
           "PRIORITIES", "PRIORITY_DEFAULT", "PRIORITY_LABELS", "PRIORITY_P0",
           "PRIORITY_P1", "PRIORITY_P2", "PRIORITY_P3", "QUERY_MAX_CHARS",
           "REPORT_PATH", "REPORT_TITLE", "SYSTEM_PROMPT", "TOOL_CHANGED_FILES",
           "TOOL_PR_DIFF", "WARN_DIFF_TRUNCATED", "WARN_FILE_NOT_INDEXED",
           "WARN_GITHUB_COMMENT_FAILED", "WARN_INDEX_EMPTY", "WARN_JSON",
           "WARN_MCP_UNAVAILABLE", "WARN_TOOL_FAILED",
           "added_lines", "changed_files_from_diff", "context_query",
           "normalize_priority", "normalize_review", "render_context",
           "review_question", "sort_risks", "strip_json_fence", "truncate_diff"]


def normalize_priority(value: object) -> str:
    """Приоритет из свободной формы: ``"p0"``, ``"P0 (критично)"``, ``0`` → ``"P0"``.

    Всё непонятное (пустое значение, ``"важно"``, ``None``) становится ``P3``: находка
    без приоритета — не повод падать и не повод ставить ей P0.
    """
    match = _PRIORITY_RE.search(str(value or "").upper())
    return f"P{match.group(1)}" if match else PRIORITY_DEFAULT


def sort_risks(risks: Sequence[dict]) -> list[dict]:
    """Риски по возрастанию приоритета: P0 первым; порядок равных сохраняется.

    Сортировка идёт по каноническому приоритету, а не по строке: ``"0"`` и ``"P0"``
    — один приоритет, а ``sorted`` по строке поставил бы ``P10`` перед ``P2``.
    """
    return sorted(risks, key=lambda item: PRIORITIES.index(
        normalize_priority(item.get("priority"))))


def changed_files_from_diff(diff: str) -> list[str]:
    """Пути изменённых файлов из текста diff-а — по порядку первого появления.

    Путь берётся из заголовка ``diff --git a/X b/Y`` (нужен ``Y``: у переименования
    ``X`` — старое имя), иначе из строки ``+++ b/X``; ``/dev/null`` пропускается.
    """
    paths: list[str] = []
    for line in str(diff or "").splitlines():
        path = ""
        if line.startswith(_GIT_HEADER):
            rest = line[len(_GIT_HEADER):]
            cut = rest.find(" b/")
            path = rest[cut + 3:] if cut >= 0 else ""
        elif line.startswith("+++ "):
            target = line[4:].strip()
            path = target[2:] if target.startswith("b/") else ""
        if path and path != "/dev/null" and path not in paths:
            paths.append(path)
    return paths


def added_lines(diff: str) -> list[str]:
    """Добавленные строки diff-а без ведущего ``+`` (шапка ``+++`` не считается).

    Из них собирается запрос к индексу: «что нового в коде» — ровно то, что стоит
    найти в корпусе, а строки контекста diff-а там уже есть.
    """
    lines: list[str] = []
    for line in str(diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            text = line[1:].strip()
            if text:
                lines.append(text)
    return lines


def context_query(paths: Sequence[str], diff: str, limit: int = QUERY_MAX_CHARS) -> str:
    """Запрос к индексу корпуса: пути файлов плюс добавленные строки diff-а.

    Путь в запросе обязателен: фильтра по источнику у поиска нет, поэтому проверка
    «этот фрагмент — из нужного файла» идёт по полю ``source``, а сам файл находится
    по имени в тексте запроса.
    """
    parts = [str(path).strip() for path in paths if str(path).strip()]
    parts.extend(added_lines(diff))
    return " ".join(parts)[:limit].strip()


def truncate_diff(diff: str, max_lines: int = MAX_DIFF_LINES) -> dict:
    """Diff с пределом строк и данными об обрезке — для промпта и предупреждений.

    ``omitted_files`` — файлы, начавшиеся ПОСЛЕ предела: по ним видно, чего не
    хватило модели. Файл, попавший в обрезку серединой, в списке не значится: его
    начало в промпте есть.
    """
    lines = str(diff or "").splitlines()
    total = len(lines)
    if total <= max_lines:
        return {"text": str(diff or "").strip(), "truncated": False, "total_lines": total,
                "kept_lines": total, "omitted_files": []}
    omitted = changed_files_from_diff("\n".join(lines[max_lines:]))[:20]
    note = DIFF_TRUNCATED_NOTE.format(kept=max_lines, total=total,
                                      files=", ".join(omitted) or "—")
    return {"text": "\n".join(lines[:max_lines]) + "\n" + note, "truncated": True,
            "total_lines": total, "kept_lines": max_lines, "omitted_files": omitted}


def strip_json_fence(text: str) -> str:
    """Снимает обрамляющие ```json … ``` — иначе разбор всегда падал бы."""
    content = str(text or "").strip()
    if not content.startswith("```"):
        return content
    lines = content.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _text_field(source: Mapping, keys: tuple[str, ...]) -> str:
    """Первое непустое значение словаря по списку возможных имён поля."""
    for key in keys:
        value = source.get(key)
        if value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _finding(raw: object, keys: tuple[str, ...],
             extra: Optional[Mapping[str, tuple[str, ...]]] = None) -> dict:
    """Элемент ревью, приведённый к словарю с фиксированными полями.

    Модель отвечает по контракту, но не всегда: вместо объекта приходит строка, а
    поле называется ``message`` вместо ``issue``; приведение живёт здесь, поэтому
    отчёт, комментарий PR и тесты читают одни и те же имена полей.
    """
    source = dict(raw) if isinstance(raw, dict) else {}
    text = str(raw).strip() if isinstance(raw, str) else _text_field(source, keys)
    finding = {keys[0]: text, "priority": normalize_priority(source.get("priority"))}
    for name, candidates in (extra or {}).items():
        finding[name] = _text_field(source, candidates)
    return finding


def _items(raw: object) -> list:
    """Список элементов ответа: не-список даёт пустой список, а не исключение."""
    return list(raw) if isinstance(raw, list) else []


def _load_payload(text: str) -> tuple[Optional[dict], str]:
    """JSON-объект ответа модели и текст ошибки разбора — заполнено ровно одно.

    Две попытки: текст как есть (со снятой обёрткой) и срез от первой ``{`` до
    последней ``}`` — модель часто добавляет пояснение до или после JSON.
    """
    raw = str(text or "").strip()
    if not raw:
        return None, "пустой ответ модели"
    candidates = [strip_json_fence(raw)]
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        candidates.append(raw[start:end + 1])
    error = ""
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, ValueError) as exc:
            error = str(exc)
            continue
        if isinstance(payload, dict):
            return payload, ""
        error = f"ответ не объект: {type(payload).__name__}"
    return None, error


def normalize_review(text: str) -> dict:
    """Ответ модели, разобранный по контракту, плюс признак разбора.

    Пустой объект ``{}`` — успешный разбор без находок (модель честно ничего не
    нашла), а ``parsed=False`` означает, что структуры нет и показывать нечего.
    Списки не зависят от того, что пришло: не-список во входе даёт пустой список.
    """
    payload, error = _load_payload(text)
    if payload is None:
        return {"bugs": [], "architecture_issues": [], "recommendations": [],
                "risks": [], "parsed": False, "error": error}
    bugs = [_finding(item, ("issue", "message", "description"),
                     {"file": ("file", "path"), "line": ("line", "lines")})
            for item in _items(payload.get("bugs"))]
    architecture = [_finding(item, ("issue", "message", "description"),
                             {"file": ("file", "path"),
                              "recommendation": ("recommendation", "fix", "suggestion")})
                    for item in _items(payload.get("architecture_issues"))]
    recommendations = [str(item).strip()
                       for item in _items(payload.get("recommendations"))
                       if str(item).strip()]
    risks = sort_risks([_finding(item, ("risk", "issue", "message"),
                                 {"file": ("file", "path")})
                        for item in _items(payload.get("risks"))])
    return {"bugs": bugs, "architecture_issues": architecture,
            "recommendations": recommendations, "risks": risks,
            "parsed": True, "error": ""}


def review_question(label: str, changed_files: Sequence[str]) -> str:
    """Вопрос модели: метка PR и число изменённых файлов."""
    return f"Проведи ревью PR «{label}». Изменённых файлов: {len(changed_files)}."


def _files_block(changed_files: Sequence[str]) -> str:
    """Блок списка изменённых файлов: по нему модель называет файлы в находках."""
    lines = [CONTEXT_FILES_HEADER]
    lines.extend(f"- `{path}`" for path in changed_files)
    if len(lines) == 1:
        lines.append(NO_FILES_NOTE)
    return "\n".join(lines)


def _hits_block(header: str, hits: Sequence[dict]) -> str:
    """Блок фрагментов RAG: источник, заголовок, секция и текст чанка."""
    lines = [header]
    if not hits:
        return "\n".join(lines + ["Фрагментов не найдено."])
    for position, hit in enumerate(hits, start=1):
        lines.append(f"[{position}] источник: {hit.get('source') or ''} · "
                     f"заголовок: {hit.get('title') or ''} · "
                     f"секция: {hit.get('section') or ''}")
        lines.append(str(hit.get("content") or ""))
    return "\n".join(lines)


def render_context(docs_hits: Sequence[dict], code_hits: Sequence[dict],
                   changed_files: Sequence[str], diff_info: dict) -> str:
    """Контекст ревью: файлы, документация, код изменённых файлов и diff.

    Порядок — от дешёвого к дорогому: список файлов задаёт рамку, фрагменты корпуса
    объясняют правила проекта, diff показывает само изменение и потому идёт последним.
    """
    blocks = [
        _files_block(changed_files),
        _hits_block(CONTEXT_DOCS_HEADER, docs_hits),
        _hits_block(CONTEXT_CODE_HEADER, code_hits),
        f"{CONTEXT_DIFF_HEADER}\n{str(diff_info.get('text') or '')}",
    ]
    return "\n\n".join(blocks)
