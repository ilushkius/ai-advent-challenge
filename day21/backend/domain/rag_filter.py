"""Отбор фрагментов RAG (день 23): режимы, реранкер и порог отсечения.

День 22 заканчивал отбор обрезкой до top-K и не знал порога релевантности: фрагмент
без единого слова вопроса попадал в контекст наравне с точным. Здесь лежат правила
второго этапа отбора — чистая арифметика над баллами и именами режимов, без БД,
LLM и транспорта (как ``rag_mode``).

Четыре режима отбора описывают один и тот же поиск с разными ступенями:

* ``baseline`` — поведение дня 22 (гибридный порядок, без отсечения): им проверяется,
  что новые ступени не изменили числа по умолчанию;
* ``rewrite`` — переформулировка вопроса моделью перед поиском;
* ``rerank`` — кросс-энкодер пересортировывает кандидатов по паре (вопрос, фрагмент);
* ``rerank_filter`` — то же плюс порог отсечения по баллу реранкера.

Порог ``RAG_FILTER_MIN_SCORE`` измеряется свипом по контрольным вопросам
(``scripts/run_rag_eval.py --sweep``): это величина МОДЕЛИ реранкера, поэтому при
смене ``RAG_RERANK_MODEL`` калибровку надо повторить. Порог по гибридному баллу
(когда реранкер выключен) живёт в другой шкале — «доля веса слов вопроса плюс
0.2 × косинус» (практически 0…1.2), и порог ``1.0`` такой режим обнулит.
"""
from __future__ import annotations

import math
import os
from typing import Any, List, Mapping, Optional, Sequence

#: Кросс-энкодер реранкера: мультиязычный (MS MARCO перевод), без ``trust_remote_code``.
#: Веса кэшируются в ``index/models``; смена модели требует калибровки порога заново.
RAG_RERANK_MODEL = os.environ.get(
    "RAG_RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
#: Батч кросс-энкодера: компромисс памяти и скорости (как у эмбеддера).
RAG_RERANK_BATCH_SIZE = 32
#: Предел токенов пары (вопрос, фрагмент) кросс-энкодера.
RAG_RERANK_MAX_LENGTH = 512
#: Сколько символов фрагмента подаётся в пару: длинный чанк режется, хвост не нужен.
RAG_RERANK_MAX_CHARS = 1000
#: Порог отсечения по баллу реранкера. Измерен свипом по 10 контрольным вопросам
#: (``scripts/run_rag_eval.py --sweep``, отчёт ``docs/reports/rag_modes.md``): наименьший
#: положительный порог, при котором каждый вопрос сохраняет хотя бы один фрагмент, а
#: ожидаемый источник сохраняется минимум в 9 из 10. Сам по себе порог ответы не
#: улучшает: на том же прогоне ``rerank_filter`` против ``rerank`` — лучше 1, хуже 3,
#: равно 6; выгода ступени в другом — контекст короче (в среднем 4.4 фрагмента против
#: 5), а заведомо слабые кандидаты в ответ не идут. Ноль выключает отсечение
#: (``rerank_filter`` повторяет ``rerank``); при смене ``RAG_RERANK_MODEL`` калибровку
#: надо повторить — порог принадлежит модели.
RAG_FILTER_MIN_SCORE = 0.05
#: Верхняя граница ``top_k_candidates``: сколько кандидатов можно запросить у поиска.
RAG_MAX_CANDIDATES = 60
#: Сетка свипа порога: 0.00 … 0.90 шагом 0.05.
RAG_THRESHOLD_GRID = tuple(round(0.05 * step, 2) for step in range(19))

#: Имена режимов отбора; порядок = порядок в отчёте, UI и ``GET /rag/config``.
RAG_MODE_BASELINE = "baseline"
RAG_MODE_REWRITE = "rewrite"
RAG_MODE_RERANK = "rerank"
RAG_MODE_RERANK_FILTER = "rerank_filter"
RAG_MODES = (RAG_MODE_BASELINE, RAG_MODE_REWRITE, RAG_MODE_RERANK, RAG_MODE_RERANK_FILTER)
RAG_MODE_LABELS = {
    RAG_MODE_BASELINE: "как в дне 22: гибридный поиск без отсечения",
    RAG_MODE_REWRITE: "переформулировка запроса моделью",
    RAG_MODE_RERANK: "кросс-энкодер пересортировывает кандидатов",
    RAG_MODE_RERANK_FILTER: "кросс-энкодер и порог отсечения",
}
#: Режим → что он делает. Значения по умолчанию совпадают с поведением дня 22.
RAG_MODE_KNOBS = {
    RAG_MODE_BASELINE: {"rewrite": False, "rerank": False, "min_score": None},
    RAG_MODE_REWRITE: {"rewrite": True, "rerank": False, "min_score": None},
    RAG_MODE_RERANK: {"rewrite": False, "rerank": True, "min_score": None},
    RAG_MODE_RERANK_FILTER: {"rewrite": False, "rerank": True,
                             "min_score": RAG_FILTER_MIN_SCORE},
}

#: Поля балла: гибридный (день 22) и балл реранкера.
SCORE_FIELD_RERANK = "rerank_score"
SCORE_FIELD_HYBRID = "score"

#: Код причины отказа: неизвестный режим отбора.
REASON_RAG_BAD_MODE = "bad_mode"

#: Системное сообщение переформулировки: на выходе — только поисковый запрос строкой.
RAG_REWRITE_SYSTEM_PROMPT = (
    "Ты переформулируешь вопрос пользователя для поиска по корпусу документов проекта. "
    "Верни ТОЛЬКО текст поискового запроса одной строкой: ключевые слова, имена функций и "
    "констант из вопроса, без пояснений и преамбул. Не отвечай на сам вопрос."
)
#: Предел длины переформулировки: длиннее — модель ответила не по делу.
RAG_REWRITE_MAX_CHARS = 300

#: Тексты предупреждений необязательных ступеней: они не отменяют ответ.
RAG_REWRITE_WARNING = "Переформулировка не удалась: {error}; поиск по исходному вопросу"
RAG_REWRITE_EMPTY_WARNING = "Переформулировка вернула пустой запрос: поиск по исходному вопросу"
RAG_RERANK_WARNING = "Реранкер недоступен: {error}; порядок фрагментов как в дне 22"
RAG_FILTER_EMPTY_WARNING = ("Порог отсечения {min_score:.2f} отбросил все фрагменты: "
                            "ответ уходит в режим «не знаю»")


def resolve_rag_mode(value: Optional[str]) -> Optional[str]:
    """Режим отбора по значению запроса: пусто → базовый, незнакомое имя → ``None``.

    ``None`` (и пустая строка) означает «как в дне 22»: ступени реранка и порога
    выключены. Незнакомое имя вызывающий переводит в отказ ``RAGRejected``.
    """
    text = str(value or "").strip()
    if not text:
        return RAG_MODE_BASELINE
    return text if text in RAG_MODES else None


def mode_knobs(name: Optional[str]) -> dict:
    """Копия настроек режима: ``rewrite``, ``rerank`` и ``min_score``.

    Незнакомое имя приводится к базовому: явный отказ проверяет вызывающий
    (``resolve_rag_mode``), а здесь важно лишь отдать безопасные значения по умолчанию.
    """
    resolved = resolve_rag_mode(name) or RAG_MODE_BASELINE
    return dict(RAG_MODE_KNOBS[resolved])


def mode_catalog() -> list[dict]:
    """Каталог режимов для ``GET /rag/config`` и селектора интерфейса."""
    return [{"name": name, "label": RAG_MODE_LABELS[name], **RAG_MODE_KNOBS[name]}
            for name in RAG_MODES]


def normalize_rerank_scores(values: Sequence[float]) -> list[float]:
    """Баллы кросс-энкодера → значения в ``[0, 1]``, округлённые до 4 знаков.

    Модели с одиночным выходом отдают вероятность (``nn.Sigmoid``), и тогда значения
    уже в ``[0, 1]``: они возвращаются как есть. Модели без сигмоиды дают логиты —
    их пропускаем через логистику. Пустой вход даёт пустой список.
    """
    items = [float(value) for value in values]
    if not items:
        return []
    if all(0.0 <= item <= 1.0 for item in items):
        return [round(item, 4) for item in items]
    return [round(1.0 / (1.0 + math.exp(-item)), 4) for item in items]


def candidate_text(hit: Mapping[str, Any]) -> str:
    """Текст фрагмента для пары кросс-энкодера: содержимое или превью, обрезанное."""
    text = str(hit.get("content") or hit.get("preview") or "")
    return text[:RAG_RERANK_MAX_CHARS]


def apply_rerank(hits: Sequence[dict], scores: Sequence[float]) -> list[dict]:
    """Раскладывает баллы реранкера по кандидатам и сортирует по ним.

    Сортировка стабильная: кандидаты с равным баллом сохраняют порядок дня 22.
    Рассинхрон длин — ошибка вызывающего: баллы и кандидаты обязаны идти парами.
    """
    values = [float(score) for score in scores]
    if len(values) != len(hits):
        raise ValueError("число баллов реранкера не совпало с числом кандидатов")
    ranked = [{**hit, SCORE_FIELD_RERANK: round(score, 4)}
              for hit, score in zip(hits, values)]
    ranked.sort(key=lambda item: item[SCORE_FIELD_RERANK], reverse=True)
    return ranked


def filter_hits(hits: List[dict], min_score: Optional[float],
                field: str = SCORE_FIELD_HYBRID) -> List[dict]:
    """Оставляет фрагменты с баллом не ниже порога (``None`` — без отсечения).

    Без порога список возвращается тем же объектом (не копией): вызывающий его не
    мутирует. Отсутствующее поле балла считается нулём — фрагмент без оценки проходит
    порог только при ``min_score <= 0``.
    """
    if min_score is None:
        return hits
    threshold = float(min_score)
    return [hit for hit in hits if float(hit.get(field) or 0.0) >= threshold]


def score_field(reranked: bool) -> str:
    """По какому полю шло отсечение и сортировка: балл реранкера или гибридный."""
    return SCORE_FIELD_RERANK if reranked else SCORE_FIELD_HYBRID


def filtered_empty_warning(min_score: float) -> str:
    """Предупреждение о том, что порог отсечения отбросил все фрагменты."""
    return RAG_FILTER_EMPTY_WARNING.format(min_score=float(min_score))


__all__ = [
    "RAG_FILTER_EMPTY_WARNING",
    "RAG_FILTER_MIN_SCORE",
    "RAG_MAX_CANDIDATES",
    "RAG_MODE_BASELINE",
    "RAG_MODE_KNOBS",
    "RAG_MODE_LABELS",
    "RAG_MODE_RERANK",
    "RAG_MODE_RERANK_FILTER",
    "RAG_MODE_REWRITE",
    "RAG_MODES",
    "RAG_RERANK_BATCH_SIZE",
    "RAG_RERANK_MAX_CHARS",
    "RAG_RERANK_MAX_LENGTH",
    "RAG_RERANK_MODEL",
    "RAG_RERANK_WARNING",
    "RAG_REWRITE_EMPTY_WARNING",
    "RAG_REWRITE_MAX_CHARS",
    "RAG_REWRITE_SYSTEM_PROMPT",
    "RAG_REWRITE_WARNING",
    "RAG_THRESHOLD_GRID",
    "REASON_RAG_BAD_MODE",
    "SCORE_FIELD_HYBRID",
    "SCORE_FIELD_RERANK",
    "apply_rerank",
    "candidate_text",
    "filter_hits",
    "filtered_empty_warning",
    "mode_catalog",
    "mode_knobs",
    "normalize_rerank_scores",
    "resolve_rag_mode",
    "score_field",
]
