"""Оценка прогона профилей (день 29): строка вопроса, сводка варианта и вердикт пары.

Вынесено из ``local_tuning`` (как ``rag_eval`` из ``rag_mode`` дня 24): там профили и
их параметры, здесь — то, что считается о результате прогона. Линия раздела — предмет:
``local_tuning`` отвечает на вопрос «с какими ручками звали модель», этот модуль — «что
из этого вышло».

Почему вердикт машинный. Ранжирование вариантов опирается только на правила проекта:
вердикт строки дня 24 (``rag_demo.verdict``), подтверждённые цитаты дня 22 и опора на
контекст дня 24. Оценки человека и модели-судьи здесь нет намеренно — она внесла бы
второй, неповторяемый критерий в отчёт; человек дописывает «Выводы» в самом отчёте.

Время не входит в качество, а работает тайбрейком: ``avg_ms`` считается только по
строкам режима ``rag`` (в ``dont_know`` модель не звали, и время поиска по корпусу
испортило бы сравнение скорости генерации).
"""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

from . import rag_demo, rag_mode
from .local_tuning import PROFILE_BASELINE, TuningProfile

__all__ = ["MODE_ANSWERED", "MODE_ERROR", "OK_VERDICTS", "VERDICT_BASELINE_BETTER",
           "VERDICT_SAME", "VERDICT_TUNED_BETTER", "compare", "quality_row",
           "summarize", "summary"]

#: Вердикты сравнения профилей: имена одинаковы у сводки, интерфейса и отчёта.
VERDICT_TUNED_BETTER = "после оптимизации лучше"
VERDICT_BASELINE_BETTER = "до оптимизации лучше"
VERDICT_SAME = "равно"

#: Вердикты строки дня 24, которые считаются совпадением с ожиданием.
OK_VERDICTS = (rag_demo.VERDICT_OK, rag_demo.VERDICT_DONT_KNOW_OK)

#: Режим успешного ответа по корпусу: в ``dont_know`` модель не звали, ``error`` —
#: она упала, поэтому ни то, ни другое не входит в среднее время ответа.
MODE_ANSWERED = "rag"
MODE_ERROR = "error"


def quality_row(question: rag_demo.DemoQuestion, record: dict, *,
                profile: Optional[TuningProfile] = None,
                model: Optional[str] = None) -> dict:
    """Строка прогона: вопрос, параметры варианта, вердикт дня 24 и метрики ответа.

    Токены и скорость берутся из ``record["tokens"]``: у режима «не знаю» модель не
    вызывалась, поэтому там нули, а у строки ``error`` словаря токенов нет вовсе.
    """
    tokens = record.get("tokens") or {}
    answer = str(record.get("answer") or "")
    expected_mode = str(question.expected_mode or "")
    mode = str(record.get("mode") or "")
    return {
        "question": question.question,
        "profile": profile.name if profile is not None else "",
        "model": str(model or ""),
        "mode": mode,
        "verdict": rag_demo.verdict(question, record),
        "mode_match": (mode == expected_mode) if expected_mode else True,
        "sources_found": rag_demo.expected_found(record.get("sources") or [], question),
        "quotes_verified": bool(record.get("quotes_verified")),
        "quote_count": len(record.get("quotes") or []),
        "confidence": float(record.get("confidence") or 0.0),
        "grounding_ok": record.get("grounding") == rag_mode.GROUNDED_VERDICT,
        "answer": answer,
        "answer_chars": len(answer),
        "prompt_tokens": int(tokens.get("prompt_tokens") or 0),
        "completion_tokens": int(tokens.get("completion_tokens") or 0),
        "duration_ms": int(record.get("duration_ms") or 0),
        "tokens_per_second": float(tokens.get("tokens_per_second") or 0.0),
        "load_ms": int(tokens.get("load_ms") or 0),
        "sources": list(record.get("sources") or []),
        "quotes": list(record.get("quotes") or []),
        "expected_mode": expected_mode,
        "expected_sources": list(question.expected_sources),
        "warning": str(record.get("warning") or ""),
    }


def _mean(values: Iterable[float]) -> float:
    """Среднее списка; пустой список — ``0.0`` (а не деление на ноль)."""
    items = [float(value or 0) for value in values]
    return sum(items) / len(items) if items else 0.0


def summarize(rows: Iterable[dict]) -> dict:
    """Сводка варианта: счётчики вердиктов, среднее время и скорость генерации.

    ``avg_ms`` — только по строкам режима ``rag``, ``avg_tokens_per_second`` — по
    строкам с непустым выводом модели: у режима «не знаю» генерации не было.
    """
    items = list(rows)
    answered = [row for row in items if row.get("mode") == MODE_ANSWERED]
    generated = [row for row in items if int(row.get("completion_tokens") or 0) > 0]
    return {
        "questions": len(items),
        "verdict_ok": sum(1 for row in items if row.get("verdict") in OK_VERDICTS),
        "mode_match": sum(1 for row in items if row.get("mode_match")),
        "sources_found": sum(1 for row in items if row.get("sources_found")),
        "quotes_verified": sum(1 for row in items if row.get("quotes_verified")),
        "grounding_ok": sum(1 for row in items if row.get("grounding_ok")),
        "errors": sum(1 for row in items if row.get("mode") == MODE_ERROR),
        "avg_ms": int(round(_mean(row.get("duration_ms") for row in answered))),
        "avg_tokens_per_second": round(
            _mean(row.get("tokens_per_second") for row in generated), 1),
        "completion_tokens": sum(int(row.get("completion_tokens") or 0)
                                 for row in items),
        "avg_answer_chars": round(_mean(row.get("answer_chars") for row in items), 1),
    }


def _rank(values: Mapping[str, Any]) -> tuple:
    """Ранг варианта: вердикты, затем подтверждённые цитаты, затем опора ответа."""
    return (int(values.get("verdict_ok") or 0),
            int(values.get("quotes_verified") or 0),
            int(values.get("grounding_ok") or 0))


def compare(baseline: Mapping[str, Any], other: Mapping[str, Any]) -> str:
    """Кто из двух сводок лучше: сначала ранг, затем меньшее среднее время.

    Вердикт детерминированный и без модели-судьи: правила дня 24 (вердикт строки),
    дня 22 (подтверждённые цитаты) и дня 24 (опора на контекст) уже формализованы, а
    время — тайбрейк, потому что оптимизация дня и про скорость тоже.
    """
    left, right = _rank(baseline), _rank(other)
    if right != left:
        return VERDICT_TUNED_BETTER if right > left else VERDICT_BASELINE_BETTER
    left_ms, right_ms = float(baseline.get("avg_ms") or 0), float(other.get("avg_ms") or 0)
    if left_ms and right_ms and left_ms != right_ms:
        return VERDICT_TUNED_BETTER if right_ms < left_ms else VERDICT_BASELINE_BETTER
    return VERDICT_SAME


def _title(variant: Mapping[str, Any]) -> str:
    """Подпись варианта для сводки: профиль и модель (как ``TuningProfile.title``)."""
    params = variant.get("params") or {}
    name = params.get("profile") or ""
    return f"{name} ({params.get('model') or 'модель конфига'})"


def _pair(baseline: Mapping[str, Any], other: Mapping[str, Any]) -> dict:
    """Строка сравнения двух вариантов одной модели: вердикт, качество и скорость."""
    left, right = baseline.get("summary") or {}, other.get("summary") or {}
    left_ms, right_ms = int(left.get("avg_ms") or 0), int(right.get("avg_ms") or 0)
    return {
        "model": str((baseline.get("params") or {}).get("model") or ""),
        "profile": str((other.get("params") or {}).get("profile") or ""),
        "baseline": _title(baseline),
        "other": _title(other),
        "verdict": compare(left, right),
        "quality_delta": (int(right.get("verdict_ok") or 0)
                          - int(left.get("verdict_ok") or 0)),
        "speedup": (round(left_ms / right_ms, 2) if left_ms and right_ms else 0.0),
    }


def summary(variants: Iterable[dict]) -> dict:
    """Сводка прогона: варианты, пары «baseline → tuned» по каждой модели и лучший.

    Единственный источник сводки и для службы, и для интерфейса, и для отчёта: иначе
    «лучший вариант» считался бы в трёх местах по-разному. ``total_ms`` — суммарное
    время ответов модели по всем строкам всех вариантов (то, что заняла генерация,
    без поиска по корпусу и накладных расходов прогона).
    """
    items = list(variants)
    pairs: List[dict] = []
    for model in dict.fromkeys(_model(item) for item in items):
        group = [item for item in items if _model(item) == model]
        baseline = next((item for item in group
                         if (item.get("params") or {}).get("profile") == PROFILE_BASELINE),
                        None)
        if baseline is None:
            continue
        pairs.extend(_pair(baseline, item) for item in group if item is not baseline)
    best = max(items, key=_best_key, default=None)
    return {
        "variants": items,
        "pairs": pairs,
        "best": _title(best) if best is not None else "",
        "total_ms": sum(int(row.get("duration_ms") or 0)
                        for item in items for row in (item.get("rows") or [])),
    }


def _model(variant: Mapping[str, Any]) -> str:
    """Модель варианта: пары «baseline → tuned» строятся внутри одной модели."""
    return str((variant.get("params") or {}).get("model") or "")


def _best_key(variant: Mapping[str, Any]) -> tuple:
    """Ключ лучшего варианта: ранг сводки, при равенстве — меньшее среднее время."""
    values = variant.get("summary") or {}
    return (_rank(values), -float(values.get("avg_ms") or 0))
