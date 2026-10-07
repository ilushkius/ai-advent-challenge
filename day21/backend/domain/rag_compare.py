"""Сравнение провайдеров ответа RAG (день 28): вердикт строки и сводка прогона.

Один вопрос прогоняется дважды — локальной моделью Ollama и облаком DeepSeek, — и
разница должна читаться человеком: здесь правила «кто лучше» и средние числа по
прогону. Retrieval в это сравнение не входит: поиск по корпусу всегда локальный,
различается только тот, кто генерирует ответ.

Правило вердикта упорядочено, а не «по среднему баллу»: сначала смотрит, ответил ли
провайдер по корпусу вообще (``dont_know`` и откат — не ответ), и только между
ответившими сравниваются подтверждённые цитаты, уверенность и число источников.
Порядок важен: иначе уверенная запись «не знаю» с нулём источников весила бы столько
же, сколько пустая, и вердикт терял бы смысл.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

__all__ = ["MODE_ANSWERED", "VERDICT_CLOUD_BETTER", "VERDICT_EQUAL",
           "VERDICT_LOCAL_BETTER", "VERDICT_LABELS", "row", "summary", "verdict"]

#: Режим успешного ответа по корпусу: ``dont_know`` и ``error`` — не ответ.
MODE_ANSWERED = "rag"

VERDICT_LOCAL_BETTER = "локально лучше"
VERDICT_CLOUD_BETTER = "облако лучше"
VERDICT_EQUAL = "равно"

#: Подписи вердиктов: их отдают сводка и интерфейс, чтобы список не дублировался.
VERDICT_LABELS = (VERDICT_LOCAL_BETTER, VERDICT_CLOUD_BETTER, VERDICT_EQUAL)

#: Ключи сводки: одинаковый набор у пустого прогона и у полного — иначе таблица
#: отчёта и метрики интерфейса читали бы то, чего в сводке нет.
_SUMMARY_COUNTERS = ("local_rag", "cloud_rag", "local_dont_know", "cloud_dont_know",
                     "local_with_sources", "cloud_with_sources",
                     "local_verified", "cloud_verified",
                     "better_local", "better_cloud", "equal")

#: Ключи, по которым считается среднее время: локальная сторона и облачная.
_DURATION_KEYS = {"local_avg_ms": "local", "cloud_avg_ms": "cloud"}


def _answered(record: Dict[str, Any]) -> bool:
    """Ответил ли провайдер по корпусу: режим ``rag`` и вызов не откатывался."""
    return record.get("mode") == MODE_ANSWERED and not record.get("fallback")


def _rank(record: Dict[str, Any]) -> tuple:
    """Ранг ответа между двумя ответившими: цитаты, уверенность, число источников."""
    return (bool(record.get("quotes_verified")),
            float(record.get("confidence") or 0.0),
            len(record.get("sources") or []))


def verdict(local: Dict[str, Any], cloud: Dict[str, Any]) -> str:
    """Кто ответил лучше — по режиму, затем по рангу ответа.

    Проверки идут по порядку: сначала «ответил ли» (откат и ``dont_know`` проигрывают
    любому ответу по корпусу), потом ранг между ответившими.
    """
    l_ok, c_ok = _answered(local), _answered(cloud)
    if l_ok and not c_ok:
        return VERDICT_LOCAL_BETTER
    if c_ok and not l_ok:
        return VERDICT_CLOUD_BETTER
    l_rank, c_rank = _rank(local), _rank(cloud)
    if l_rank > c_rank:
        return VERDICT_LOCAL_BETTER
    if l_rank < c_rank:
        return VERDICT_CLOUD_BETTER
    return VERDICT_EQUAL


def row(question: str, local: Dict[str, Any], cloud: Dict[str, Any]) -> dict:
    """Строка сравнения: вопрос, оба ответа целиком и машинный вердикт."""
    return {"question": str(question or "").strip(), "local": local, "cloud": cloud,
            "verdict": verdict(local, cloud)}


def summary(rows: Iterable[Dict[str, Any]]) -> dict:
    """Сводка прогона: счётчики сторон, среднее время и общий вердикт.

    ``local_rag``/``cloud_rag`` считаются по режиму ответа (а не по «не откат»):
    строка с откатом помечена ``mode="rag"`` и ``fallback=True``, но ответа по
    корпусу в ней нет, и записывать её в ответившие было бы неправдой.
    """
    items: List[Dict[str, Any]] = list(rows)
    counts = {key: 0 for key in _SUMMARY_COUNTERS}
    durations = {side: [] for side in _DURATION_KEYS.values()}
    verdicts = {VERDICT_LOCAL_BETTER: 0, VERDICT_CLOUD_BETTER: 0, VERDICT_EQUAL: 0}
    for item in items:
        local, cloud = item.get("local") or {}, item.get("cloud") or {}
        for side, record in (("local", local), ("cloud", cloud)):
            if _answered(record):
                counts[f"{side}_rag"] += 1
            if record.get("mode") == "dont_know":
                counts[f"{side}_dont_know"] += 1
            if record.get("sources"):
                counts[f"{side}_with_sources"] += 1
            if record.get("quotes_verified"):
                counts[f"{side}_verified"] += 1
            try:
                durations[side].append(float(record.get("duration_ms") or 0))
            except (TypeError, ValueError):
                durations[side].append(0.0)
        name = item.get("verdict")
        if name in verdicts:
            verdicts[name] += 1
    counts["better_local"] = verdicts[VERDICT_LOCAL_BETTER]
    counts["better_cloud"] = verdicts[VERDICT_CLOUD_BETTER]
    counts["equal"] = verdicts[VERDICT_EQUAL]
    result = {"total": len(items)}
    for key in _SUMMARY_COUNTERS:
        result[key] = counts[key]
    for key, side in _DURATION_KEYS.items():
        values = durations[side]
        result[key] = int(round(sum(values) / len(values))) if values else 0
    result["verdict"] = _overall(verdicts)
    return result


def _overall(verdicts: Dict[str, int]) -> str:
    """Общий вердикт прогона: чьих побед больше; ничья (и пусто) — «равно»."""
    if verdicts[VERDICT_LOCAL_BETTER] > verdicts[VERDICT_CLOUD_BETTER]:
        return VERDICT_LOCAL_BETTER
    if verdicts[VERDICT_CLOUD_BETTER] > verdicts[VERDICT_LOCAL_BETTER]:
        return VERDICT_CLOUD_BETTER
    return VERDICT_EQUAL
