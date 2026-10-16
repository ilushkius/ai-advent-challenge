"""Модель в подготовке релиза (день 35): пачки коммитов → тип версии и группы.

Вынесено из ``release_service.py`` (предел 400 строк) и по предмету: здесь только
разговор с моделью и разбор её ответа, ни MCP, ни файлов, ни проверок. Служба решает,
когда спрашивать и что делать с отказом; этот модуль — как спросить.

Почему пачками. История челленджа — десятки коммитов, и один запрос со всем списком
размывает ответ: модель начинает пересказывать заголовки вместо группировки. Пачка по
``COMMIT_BATCH`` коммитов даёт короткий список, а результаты пачек склеиваются
(``_unique`` убирает повторы, ``release.merge_groups`` — дубли групп).

Почему отказ модели не исключение. ``llm_json`` ловит ``RAGUpstreamError`` (нет ключа,
таймаут, обрыв) и возвращает пустую строку: пустой ответ разбирается как «не разобрано»,
и дальше работает детерминированное правило (``release.pick_bump`` — для версии,
заголовки коммитов — для пунктов CHANGELOG). Подготовка релиза не должна падать из-за
того, что облако недоступно, — но и молчать об этом нельзя: причина видна в
``version_reason`` и в заметках прогона.
"""
from __future__ import annotations

from typing import Any, Callable

from shared.logging_utils import get_logger

from ..core import config
from ..domain import release
from . import rag_llm
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["batches", "changelog_groups", "llm_json", "version_analysis"]


def batches(commits: list[dict]) -> list[list[dict]]:
    """Коммиты пачками по ``COMMIT_BATCH``, не больше ``COMMITS_MAX`` всего."""
    limited = list(commits)[:release.COMMITS_MAX]
    size = release.COMMIT_BATCH
    return [limited[index:index + size] for index in range(0, len(limited), size)]


def llm_json(client: Any, system: str, question: str, *, task_type: str,
             max_tokens: int, sleep: Callable[[float], None]) -> str:
    """Ответ модели текстом; недоступная модель — пустая строка (работает правило)."""
    try:
        result = rag_llm.call_with_retry(
            sleep, client.generate_with_context, system=system, context="",
            question=question, task_type=task_type, agent_id=release.AGENT_ID,
            temperature=0.0, max_tokens=max_tokens)
    except RAGUpstreamError as exc:
        logger.warning("Релиз: модель недоступна: %s", exc)
        return ""
    return rag_llm.response_text(result)


def _ask(client: Any, system: str, question: str, *, task_type: str, max_tokens: int,
         sleep: Callable[[float], None], retry_hint: str, parse: Callable) -> Any:
    """Ответ модели и его разбор; неразобранный ответ повторяется с подсказкой.

    Повтор нужен из-за реального поведения модели: пересказывая заголовки коммитов,
    она упирается в предел токенов и приходит без закрывающей скобки — а подсказка ко
    второй попытке просит короткие пункты. Когда и вторая попытка не разобрана, вопрос
    закрывает детерминированное правило (``pick_bump``/заголовки коммитов).
    """
    parsed = None
    for attempt in range(release.PARSER_ATTEMPTS):
        raw = llm_json(client, system, question, task_type=task_type,
                       max_tokens=max_tokens, sleep=sleep)
        parsed = parse(raw)
        if parsed is not None:
            return parsed
        logger.warning("Релиз: ответ модели не разобран (попытка %d из %d)",
                       attempt + 1, release.PARSER_ATTEMPTS)
        question = f"{question}\n\n{retry_hint}"
    return parsed


def version_analysis(client: Any, commits: list[dict], *,
                     sleep: Callable[[float], None]) -> tuple:
    """Тип изменения и пункты от модели; модель молчит — правило по меткам коммитов.

    Возвращает ``(bump, reason, breaking_changes, features, fixes)``: сильнейшее
    предложение пачек побеждает (``BUMP_ORDER``), а его списки склеиваются с остальными
    и обрезаются до ``MAX_KEY_CHANGES`` — «почему новая версия» объясняется одним
    предложением, а не пятью.
    """
    suggestions = []
    for batch in batches(commits):
        system, question = release.build_version_prompt(batch, total=len(commits))
        parsed = _ask(client, system, question, task_type=config.LLM_TASK_CLASSIFY,
                      max_tokens=config.LLM_MAX_RESPONSE_TOKENS, sleep=sleep,
                      retry_hint=release.VERSION_RETRY_HINT,
                      parse=release.parse_version_suggestion)
        if parsed is not None:
            suggestions.append(parsed)
    if not suggestions:
        bump, rule = release.pick_bump(commits)
        return bump, release.FALLBACK_REASON.format(rule=rule), [], [], []
    best = max(suggestions, key=lambda item: release.BUMP_ORDER.index(
        item["suggested_version"]))
    return (best["suggested_version"], best["reason"],
            _unique([item for parsed in suggestions
                     for item in parsed["breaking_changes"]]),
            _unique([item for parsed in suggestions for item in parsed["features"]]),
            _unique([item for parsed in suggestions for item in parsed["fixes"]]))


def changelog_groups(client: Any, commits: list[dict], changed_files: list[str], *,
                     sleep: Callable[[float], None]) -> tuple:
    """Группы CHANGELOG и счётчики: ``(kept, dropped, minor_count, note)``.

    Пунктами отката становятся заголовки коммитов: ключевые изменения в разделе есть
    всегда, даже если модель недоступна, — а заметка говорит, что это правило, а не она.
    """
    collected = []
    for batch in batches(commits):
        system, question = release.build_changelog_prompt(batch, changed_files)
        parsed = _ask(client, system, question, task_type=config.LLM_TASK_CODE,
                      max_tokens=config.LLM_MAX_RESPONSE_TOKENS_LONG, sleep=sleep,
                      retry_hint=release.CHANGELOG_RETRY_HINT,
                      parse=release.parse_changelog_groups)
        if parsed is not None:
            collected.append(parsed)
    groups = release.merge_groups(collected)
    note = ""
    if not release.key_items(groups):
        groups = {"breaking": [], "changed": [], "fixed": [], "removed": [],
                  "added": [str(commit.get("subject") or "").strip()
                            for commit in commits
                            if str(commit.get("subject") or "").strip()]}
        note = release.FALLBACK_CHANGELOG_NOTE
    kept, dropped = release.cap_groups(groups, release.MAX_KEY_CHANGES)
    minor_count = max(0, len(commits) - len(release.key_items(kept)))
    return kept, dropped, minor_count, note


def _unique(items: list[str], limit: int = release.MAX_KEY_CHANGES) -> list[str]:
    """Строки без пустых и повторов, не больше ``limit`` (склейка пунктов пачек)."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result
