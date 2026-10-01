"""Домен демо-сценария RAG (день 24): контрольные вопросы и вердикты прогона.

Набор из десяти вопросов лежит в ``backend/data/demo_questions.json``: пять с
ответом в корпусе, три частичных и два без ответа. Файл читается на каждый запрос,
поэтому набор правят без перезапуска бэкенда.

Вердикт строки — это одно слово-итог для отчёта и интерфейса: совпал ли режим с
ожиданием, нашёлся ли ожидаемый источник, подтверждают ли цитаты ответ. Логика
здесь, а не в API: её проверяют и скрипт отчёта, и тесты.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from . import rag_eval, rag_quotes

logger = logging.getLogger(__name__)

__all__ = [
    "DEMO_QUESTIONS_PATH",
    "DemoQuestion",
    "VERDICT_DONT_KNOW_OK",
    "VERDICT_FALLBACK",
    "VERDICT_MODE_MISMATCH",
    "VERDICT_NONE",
    "VERDICT_OK",
    "VERDICT_SOURCE_MISS",
    "VERDICT_UNCITED",
    "expected_found",
    "load_questions",
    "question_as_dict",
    "verdict",
]

#: Файл набора вопросов: ``backend/data/demo_questions.json`` рядом с ``backend``.
DEMO_QUESTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_questions.json"

#: Вердикты строки прогона. ``OK`` и ``DONT_KNOW_OK`` — совпадения с ожиданием,
#: остальные считаются расхождениями в сводке.
VERDICT_OK = "совпадает"
VERDICT_DONT_KNOW_OK = "верно: ответа в корпусе нет"
VERDICT_MODE_MISMATCH = "режим не совпал с ожиданием"
VERDICT_SOURCE_MISS = "источник не найден"
VERDICT_UNCITED = "цитаты не подтверждают ответ"
VERDICT_FALLBACK = "ошибка модели, ответ без корпуса"
VERDICT_NONE = "без ожиданий"


@dataclass(frozen=True)
class DemoQuestion:
    """Контрольный вопрос демо: текст, ожидание и ожидаемые источники корпуса."""

    question: str
    expectation: str = ""
    expected_mode: str = ""
    expected_sources: tuple[str, ...] = ()
    note: str = ""


def _as_sources(value: Any) -> tuple[str, ...]:
    """Ожидаемые источники — всегда кортеж строк (одна строка тоже допустима)."""
    if isinstance(value, (str, bytes)):
        return (str(value),) if value else ()
    if not value:
        return ()
    return tuple(str(item) for item in value if item)


def load_questions(path: Optional[Any] = None) -> list[DemoQuestion]:
    """Читает набор контрольных вопросов; сбой чтения — пустой список.

    Отсутствующий или битый файл не роняет демо: сервис просто покажет пустой
    список. Вопрос без непустого текста пропускается с предупреждением.
    """
    target = DEMO_QUESTIONS_PATH if path is None else Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Набор демо-вопросов не прочитан (%s): %s", target, exc)
        return []
    raw = payload.get("questions") if isinstance(payload, dict) else payload
    items: list[DemoQuestion] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        if not question:
            logger.warning("Вопрос демо пропущен: пустой текст (%r)", entry)
            continue
        items.append(DemoQuestion(
            question=question,
            expectation=str(entry.get("expectation") or ""),
            expected_mode=str(entry.get("expected_mode") or ""),
            expected_sources=_as_sources(entry.get("expected_sources")),
            note=str(entry.get("note") or ""),
        ))
    return items


def question_as_dict(item: DemoQuestion) -> dict:
    """Вопрос для API и интерфейса: источники — список, а не кортеж."""
    return {
        "question": item.question,
        "expectation": item.expectation,
        "expected_mode": item.expected_mode,
        "expected_sources": list(item.expected_sources),
        "note": item.note,
    }


def expected_found(sources: Iterable[Any], question: DemoQuestion) -> bool:
    """Найден ли хотя бы один ожидаемый источник среди использованных.

    Сравнение — ``rag_eval.source_matches`` (по буквам и цифрам), поэтому слаг
    корпуса и имя файла сходятся независимо от разделителей. Вопрос без ожидаемых
    источников (тот, что ждёт ``dont_know``) всегда даёт ``False``.
    """
    names = [str((source or {}).get("source") or "") for source in sources or []]
    return any(rag_eval.source_matches(name, expected)
               for expected in question.expected_sources
               for name in names)


def verdict(question: DemoQuestion, record: dict) -> str:
    """Итог строки прогона — одно слово для отчёта и интерфейса.

    Порядок проверок задан намеренно: откат важнее режима (модель упала — строка
    «ошибка», а не «режим»), расхождение режима важнее содержания.
    """
    if record.get("fallback"):
        return VERDICT_FALLBACK
    mode = str(record.get("mode") or "")
    if question.expected_mode and mode != question.expected_mode:
        return VERDICT_MODE_MISMATCH
    if mode == rag_quotes.RAG_MODE_DONT_KNOW:
        return VERDICT_DONT_KNOW_OK
    if mode == rag_quotes.RAG_MODE_RAG:
        if not expected_found(record.get("sources") or [], question):
            return VERDICT_SOURCE_MISS
        if not record.get("quotes_verified"):
            return VERDICT_UNCITED
        return VERDICT_OK
    return VERDICT_NONE
