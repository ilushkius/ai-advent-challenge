"""Память задачи мини-чата (день 25): четыре ключа рабочей памяти дня 11.

``goal`` — цель диалога одной строкой; ``terms``, ``constraints``,
``clarifications`` — списки зафиксированных терминов, ограничений и уточнений.
Значения хранятся JSON-строками: ``MemoryManager.add_working`` требует непустое
значение, поэтому пустая цель (``""``) остаётся непустой строкой в базе — иначе
запись было бы не создать, а удалять записи рабочей памяти API дня 11 не умеет.

Обновление — ПОЛНАЯ ЗАМЕНА четырёх ключей, без слияния с предыдущим состоянием:
слияние маскировало бы дрейф цели, который обязан измерять отчёт о сценариях.

Модуль вынесен из ``mini_chat_service`` по пределу строк: здесь правила памяти,
там — отбор фрагментов и вызов модели.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from shared.logging_utils import get_logger

from ..agents.memory import MemoryManager
from ..core import config
from ..domain import orchestration_plan
from . import rag_llm
from .llm_client import LLMClient

logger = get_logger(__name__)

#: Служебная строка ``agents``: якорь внешних ключей таблиц памяти мини-чата.
MINI_CHAT_AGENT_ID = "mini-chat"

#: Ключи памяти задачи в рабочей памяти дня 11, порядок = порядок в промпте и панели.
MINI_CHAT_MEMORY_KEYS = ("goal", "terms", "constraints", "clarifications")

MINI_CHAT_MEMORY_HEADER = "## Память задачи"
MINI_CHAT_DIALOG_HEADER = "## История диалога"
#: Напоминание о цели идёт последней строкой блока памяти — ближе к вопросу.
MINI_CHAT_GOAL_REMINDER = "Текущая цель диалога: {goal}. Не отклоняйся от неё."
MINI_CHAT_ROLE_LABELS = {"user": "Пользователь", "assistant": "Ассистент"}

MINI_CHAT_EXTRACT_QUESTION = "Извлеки память задачи из диалога."
MINI_CHAT_EXTRACT_SYSTEM_PROMPT = (
    "Проанализируй диалог. Извлеки: цель диалога (goal), зафиксированные термины "
    "(terms: список), ограничения (constraints: список), что пользователь уточнил "
    "(clarifications: список). Верни JSON. Формат ответа ровно такой: "
    "{\"goal\": \"...\", \"terms\": [\"...\"], \"constraints\": [\"...\"], "
    "\"clarifications\": [\"...\"]}. Ничего кроме JSON не выводи."
)

#: Пределы полей извлекаемой памяти: модель не должна раздувать панель и промпт.
MINI_CHAT_LIST_LIMIT = 20
MINI_CHAT_ITEM_MAX = 200
MINI_CHAT_GOAL_MAX = 400

__all__ = ["MINI_CHAT_AGENT_ID", "MINI_CHAT_EXTRACT_QUESTION",
           "MINI_CHAT_MEMORY_KEYS", "dialog_block", "extract_payload",
           "memory_block", "payload", "store_payload", "task_memory"]


def _load_value(row: Dict[str, Any], default: Any) -> Any:
    """Значение записи рабочей памяти: битый JSON не должен ронять панель."""
    try:
        return json.loads(row["value"])
    except (KeyError, TypeError, ValueError):
        return default


def _normalize_items(value: Any) -> List[str]:
    """Список непустых строк памяти: обрезка по элементу и по числу элементов."""
    if not isinstance(value, (list, tuple)):
        return []
    items = [str(item).strip()[:MINI_CHAT_ITEM_MAX] for item in value]
    return [item for item in items if item][:MINI_CHAT_LIST_LIMIT]


def _clean_goal(value: Any) -> str:
    """Цель диалога одной строкой с пределом длины."""
    return str(value or "").strip()[:MINI_CHAT_GOAL_MAX]


def _extract_payload(text: str) -> Optional[dict]:
    """Память задачи из ответа модели: ``None``, если JSON не разобран.

    Разбор толерантный и общий с оркестрацией дня 20: берётся первый сбалансированный
    ``{...}``, поэтому markdown-обёртка вокруг JSON не считается сбоем.
    """
    parsed = orchestration_plan._first_json_object(str(text or ""))
    if parsed is None:
        return None
    return {
        "goal": _clean_goal(parsed.get("goal")),
        "terms": _normalize_items(parsed.get("terms")),
        "constraints": _normalize_items(parsed.get("constraints")),
        "clarifications": _normalize_items(parsed.get("clarifications")),
    }


def payload(memory: MemoryManager, task_id: str) -> dict:
    """Память задачи: нормализованные четыре ключа плюс исходные строки (``_rows``)."""
    rows = {row["key"]: row
            for row in memory.get_working(MINI_CHAT_AGENT_ID, task_id)}
    result: Dict[str, Any] = {"_rows": rows}
    for key in MINI_CHAT_MEMORY_KEYS:
        row = rows.get(key)
        default = "" if key == "goal" else []
        value = default if row is None else _load_value(row, default)
        result[key] = (_clean_goal(value) if key == "goal"
                       else _normalize_items(value))
    return result


def task_memory(memory: MemoryManager, session_id: str, task_id: str) -> dict:
    """Память задачи сессии для API: четыре поля, счётчик реплик и метка обновления."""
    data = payload(memory, task_id)
    rows = data["_rows"]
    updated_at = None
    for row in rows.values():
        stamp = row.get("updated_at")
        text = stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp)
        if updated_at is None or text > updated_at:
            updated_at = text
    return {
        "session_id": session_id, "task_id": task_id,
        "goal": data["goal"], "terms": data["terms"],
        "constraints": data["constraints"],
        "clarifications": data["clarifications"],
        "message_count": memory.count_short_term(
            MINI_CHAT_AGENT_ID, session_id),
        "updated": bool(rows), "updated_at": updated_at,
    }


def memory_block(memory: MemoryManager, task_id: str) -> str:
    """Блок памяти задачи для промпта; пустая память — пустая строка."""
    data = payload(memory, task_id)
    lines = [MINI_CHAT_MEMORY_HEADER]
    if data["goal"]:
        lines.append(f"Цель: {data['goal']}")
    if data["terms"]:
        lines.append("Термины: " + "; ".join(data["terms"]))
    if data["constraints"]:
        lines.append("Ограничения: " + "; ".join(data["constraints"]))
    if data["clarifications"]:
        lines.append("Уточнения: " + "; ".join(data["clarifications"]))
    if len(lines) == 1:
        return ""
    if data["goal"]:
        lines.append(MINI_CHAT_GOAL_REMINDER.format(goal=data["goal"]))
    return "\n".join(lines)


def dialog_block(history: List[dict]) -> str:
    """Блок истории диалога: роли словами, реплики в хронологическом порядке."""
    if not history:
        return ""
    lines = [MINI_CHAT_DIALOG_HEADER]
    for message in history:
        role = MINI_CHAT_ROLE_LABELS.get(message["role"], message["role"])
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines)


def extract_payload(memory_client: LLMClient,
                    dialog_history: List[dict]) -> Optional[dict]:
    """Память задачи из диалога: ``None`` — не удалось, предыдущее сохраняется.

    Одна попытка без повторов: предел ожидания задан фабрикой клиента, а сбой
    извлечения не должен стоить ответа.
    """
    if not dialog_history:
        return None
    context = "\n".join(
        f"{MINI_CHAT_ROLE_LABELS.get(m['role'], m['role'])}: {m['content']}"
        for m in dialog_history)
    try:
        result = memory_client.generate_with_context(
            system=MINI_CHAT_EXTRACT_SYSTEM_PROMPT, context=context,
            question=MINI_CHAT_EXTRACT_QUESTION, task_type=config.LLM_TASK_CHAT,
            agent_id=MINI_CHAT_AGENT_ID)
    except Exception as exc:  # noqa: BLE001 — любой сбой = «память не обновлена»
        logger.warning("Мини-чат: память задачи не извлечена: %s", exc)
        return None
    return _extract_payload(rag_llm.response_text(result))


def store_payload(memory: MemoryManager, task_id: str, data: dict) -> None:
    """Переписывает четыре ключа памяти задачи целиком (JSON-строками)."""
    for key in MINI_CHAT_MEMORY_KEYS:
        memory.add_working(MINI_CHAT_AGENT_ID, task_id, key,
                           json.dumps(data[key], ensure_ascii=False))
