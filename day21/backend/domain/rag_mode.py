"""Режим RAG (день 22): промпт, лимиты контекста и проверка опоры ответа на фрагменты.

Модуль чистый: ни БД, ни индекса, ни модели — только правила, по которым сервис
режима (``backend.services.rag_service``) собирает блок контекста из найденных
чанков, режет его по бюджету токенов и решает, опирается ли ответ на контекст.

Новые стратегии живут в ТОЙ ЖЕ таблице ``document_chunks``, что и стратегии
индексации дня 21: различие — только в значении колонки ``strategy``, поэтому
отдельных таблиц и миграций режиму не нужно. Соответствие «стратегия → файл
индекса» держит ``IndexService.path_for``: для имён ``rag_corpus_*`` он даёт
``index/rag_corpus_fixed.index`` и ``index/rag_corpus_structural.index``.

Блок контекста не переиспользует ``indexing_prompt.render_index_block``: там
заголовок про индекс дня 21 и выдержка в 300 символов, а ответ по корпусу требует
и метаданных чанка (источник, раздел, оценка), и текста целиком.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from shared.token_counter import count_tokens

#: Имена стратегий: значение колонки ``document_chunks.strategy`` и имя файла
#: индекса. Порядок кортежа = порядок стратегий в отчёте и в ответе ``/rag/config``.
RAG_STRATEGY_FIXED = "rag_corpus_fixed"
RAG_STRATEGY_STRUCTURAL = "rag_corpus_structural"
RAG_STRATEGIES = (RAG_STRATEGY_FIXED, RAG_STRATEGY_STRUCTURAL)
RAG_DEFAULT_STRATEGY = RAG_STRATEGY_STRUCTURAL

#: Сколько фрагментов берёт поиск и сколько их допускает запрос.
RAG_DEFAULT_TOP_K = 5
RAG_MAX_TOP_K = 10

#: Бюджет блока контекста в промпте (жадный отбор ``fit_context``) и предел длины
#: одного фрагмента: окно чанкера — 512 токенов, а русский код держит ~4 символа
#: на токен, поэтому 2000 символов хватает целому фрагменту. Обрезка короче
#: (проверено на корпусе дня 22) теряла факт в конце фрагмента: у чанка длиной
#: 1401 символ константа стояла на 1205-м символе и в промпт не попадала.
RAG_CONTEXT_MAX_TOKENS = 3000
RAG_CHUNK_MAX_CHARS = 2000

#: Опора ответа на контекст: доля слов ответа, найденных в тексте фрагментов.
#: Слова короче трёх символов не считаются — предлоги и союзы есть в любом тексте.
RAG_GROUNDING_MIN_SHARE = 0.5
RAG_GROUNDING_MIN_WORD = 5

#: Повторы вызова модели: одна попытка и две повторные, пауза растёт 1.0 → 2.0 с.
RAG_LLM_ATTEMPTS = 3
RAG_RETRY_SECONDS = 1.0
RAG_RETRY_BACKOFF = 2.0

#: Гибридный отбор фрагментов: сколько кандидатов берётся у векторного поиска и
#: какой вес остаётся у векторной близости (словесное совпадение решает, близость
#: лишь разделяет равные по словам фрагменты — см. ``rank_candidates``).
RAG_CANDIDATE_POOL = 30
RAG_VECTOR_WEIGHT = 0.2

#: Тексты отказа: их отдают роутеры и подставляет откат режима.
RAG_INDEX_EMPTY_MESSAGE = ("Корпус RAG не проиндексирован: выполните "
                           "scripts/prepare_rag_corpus.py и scripts/index_rag_corpus.py")
RAG_FALLBACK_WARNING = "RAG-запрос не выполнен: {error}; возвращён ответ без RAG"

#: Коды причин отказа режима RAG (в HTTP: пустой вопрос и неизвестная стратегия — 400,
#: непроиндексированный корпус — 409).
REASON_RAG_BAD_STRATEGY = "bad_strategy"
REASON_RAG_EMPTY_QUERY = "empty_query"
REASON_RAG_INDEX_EMPTY = "index_empty"

#: Заголовок блока контекста: им же размечен контекст в промпте и в отчёте.
RAG_HEADER = "## Контекст из корпуса RAG"

#: Системное сообщение — СТАБИЛЬНЫЙ префикс запроса: один и тот же текст в обоих
#: режимах, поэтому кэш контекста DeepSeek попадает и после включения RAG.
RAG_SYSTEM_PROMPT = (
    "Ты отвечаешь по внутреннему корпусу документов проекта. "
    "Опирайся ТОЛЬКО на блок контекста из сообщения пользователя. "
    "Если ответа в контексте нет — напиши «В контексте нет данных для ответа» "
    "и не строй догадок. Не используй общие знания и не дополняй контекст. "
    "Отвечай по-русски, коротко: не длиннее шести предложений."
)

#: Вердикты об опоре ответа на найденные фрагменты.
GROUNDED_VERDICT = "есть опора в контексте"
LOW_CONFIDENCE_VERDICT = "низкая уверенность: в ответе нет фактов из контекста"

#: Слово для проверки опоры: буквы, цифры и подчёркивание (``CHARS_PER_PAGE`` —
#: одно слово, ``day21/backend`` — два).
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё_]+")


def resolve_rag_strategy(value: Optional[str]) -> Optional[str]:
    """Стратегия поиска по значению запроса: пусто → стратегия по умолчанию.

    Незнакомое имя даёт ``None``: сервис отвечает на это отказом ``bad_strategy``,
    а не молчаливым переходом на стратегию по умолчанию.
    """
    if value in (None, ""):
        return RAG_DEFAULT_STRATEGY
    return value if value in RAG_STRATEGIES else None


def render_context(hits: Sequence[dict]) -> list[dict]:
    """Приводит попадания поиска к элементам контекста: нужные поля и обрезка текста.

    Поиск отдаёт чанк целиком (с полями для интерфейса), а в промпт идёт только
    то, что нужно модели: идентификаторы, оценка и текст не длиннее
    ``RAG_CHUNK_MAX_CHARS``. Текст берётся из ``content``, усечённый предпросмотр —
    запасной вариант, если поиск отдал только его.
    """
    items = []
    for hit in hits:
        text = str(hit.get("content") or hit.get("preview") or "")
        items.append({
            "chunk_id": hit.get("chunk_id"),
            "source": hit.get("source"),
            "title": hit.get("title"),
            "section": hit.get("section"),
            "strategy": hit.get("strategy"),
            "score": hit.get("score"),
            "text": text[:RAG_CHUNK_MAX_CHARS],
        })
    return items


def render_rag_block(items: Sequence[dict]) -> str:
    """Блок контекста для промпта: заголовок, строка метаданных и текст каждого чанка.

    Пустой список даёт пустую строку: тогда сообщение пользователя состоит из
    одного вопроса — это и есть путь режима без RAG.
    """
    if not items:
        return ""
    parts = [RAG_HEADER, ""]
    for number, item in enumerate(items, start=1):
        parts.append(
            f"[{number}] source={item.get('source')} · title={item.get('title')} · "
            f"section={item.get('section') or '—'} · chunk_id={item.get('chunk_id')} · "
            f"score={_score_text(item.get('score'))}"
        )
        parts.append(str(item.get("text") or ""))
        parts.append("")
    return "\n".join(parts).rstrip()


def fit_context(items: Sequence[dict], max_tokens: Optional[int] = None,
                counter: Optional[Callable[[str], int]] = None) -> list[dict]:
    """Отбирает фрагменты в бюджет контекста (список уже отсортирован по оценке).

    Первый фрагмент берётся всегда: пустой контекст делает режим бессмысленным, а
    переполнение бюджета — только расход токенов. Остальные добавляются, пока
    следующий не выйдет за ``max_tokens`` (по умолчанию ``RAG_CONTEXT_MAX_TOKENS``).
    """
    limit = RAG_CONTEXT_MAX_TOKENS if max_tokens is None else int(max_tokens)
    measure = counter or count_tokens
    selected: list[dict] = []
    used = 0
    for item in items:
        cost = measure(str(item.get("text") or ""))
        if selected and used + cost > limit:
            break
        selected.append(item)
        used += cost
    return selected


def content_words(text: str) -> set[str]:
    """Содержательные слова текста: длина от ``RAG_GROUNDING_MIN_WORD``, нижний регистр.

    «ё» приводится к «е»: иначе одно и то же слово из контекста и из ответа
    считалось бы разными.
    """
    words = set()
    for match in _WORD_RE.finditer(str(text or "")):
        word = match.group(0).lower().replace("ё", "е")
        if len(word) >= RAG_GROUNDING_MIN_WORD:
            words.add(word)
    return words


def query_weights(question: str, documents: Iterable[str]) -> dict[str, float]:
    """Вес каждого слова вопроса: обратная частота слова в корпусе (1 при одном фрагменте).

    Идентификатор вроде ``CHARS_PER_PAGE`` есть в одном фрагменте и потому весит в
    десятки раз больше слова «day21», которое встречается почти везде: без этого
    буквальное совпадение не отличить от общей темы вопроса.
    """
    words = sorted(content_words(question))
    if not words:
        return {}
    counts = {word: 0 for word in words}
    for document in documents:
        text = str(document or "").lower().replace("ё", "е")
        for word in words:
            if word in text:
                counts[word] += 1
    return {word: 1.0 / count for word, count in counts.items() if count}


def lexical_score(text: str, weights: Mapping[str, float]) -> float:
    """Доля веса слов вопроса, найденных в тексте (0.0 — ни одного слова вопроса)."""
    total = sum(weights.values())
    if not total:
        return 0.0
    found = content_words(text) & set(weights)
    return round(sum(weights[word] for word in found) / total, 4)


def rank_candidates(question: str, vector_hits: Sequence[dict],
                    chunks: Sequence[dict], top_k: int) -> list[dict]:
    """Отбор фрагментов для контекста: векторная выдача плюс буквальные совпадения слов.

    Модель эмбеддингов различает близкие по теме фрагменты слабо: у вопроса про
    конкретный идентификатор верный чанк идёт ниже случайных (замер дня 22: близость
    0.24–0.56 против 0.6). Поэтому кандидаты собираются из двух источников — топ
    векторного поиска и фрагменты со словами вопроса, — а оценка складывается из
    словесного совпадения (вес слова обратен его частоте в корпусе) и небольшой доли
    близости: ``CHARS_PER_PAGE`` перевешивает общую тему вопроса, а без редких слов
    порядок по-прежнему задаёт вектор.
    """
    weights = query_weights(question, [str(row.get("content") or "") for row in chunks])
    candidates: dict[str, list] = {}
    for position, hit in enumerate(vector_hits):
        key = str(hit.get("chunk_id") or f"vector-{position}")
        candidates[key] = [hit, lexical_score(_hit_text(hit), weights)]
    for row in chunks:
        key = str(row.get("chunk_id") or "")
        lexical = lexical_score(str(row.get("content") or ""), weights)
        if key in candidates:
            candidates[key][1] = max(candidates[key][1], lexical)
        elif key and lexical > 0:
            candidates[key] = [row, lexical]
    ranked = [
        {**hit, "score": round(lexical
                               + RAG_VECTOR_WEIGHT * float(hit.get("score") or 0.0), 4)}
        for hit, lexical in candidates.values()
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:max(1, int(top_k))]


def _hit_text(hit: Mapping[str, Any]) -> str:
    """Текст попадания для словесной оценки: содержимое, превью, раздел, заголовок."""
    return " ".join(str(hit.get(key) or "")
                    for key in ("content", "preview", "section", "title"))


def grounding_share(answer: str, contexts: Iterable[str]) -> float:
    """Доля содержательных слов ответа, найденных в контексте (0.0 — опоры нет).

    Ответ без содержательных слов (пустой или из одних предлогов) даёт 0.0:
    подтвердить опору нечем.
    """
    words = content_words(answer)
    if not words:
        return 0.0
    known = content_words("\n".join(str(context or "") for context in contexts))
    return round(len(words & known) / len(words), 4)


def grounding_verdict(share: float) -> str:
    """Вердикт об опоре: доля найденных слов не ниже ``RAG_GROUNDING_MIN_SHARE``."""
    return GROUNDED_VERDICT if share >= RAG_GROUNDING_MIN_SHARE else LOW_CONFIDENCE_VERDICT


def _score_text(score: Any) -> str:
    """Оценка попадания в строку метаданных (``None`` → 0.0000)."""
    try:
        return f"{float(score):.4f}"
    except (TypeError, ValueError):
        return f"{0.0:.4f}"


__all__ = [
    "GROUNDED_VERDICT",
    "LOW_CONFIDENCE_VERDICT",
    "RAG_CANDIDATE_POOL",
    "RAG_CHUNK_MAX_CHARS",
    "RAG_CONTEXT_MAX_TOKENS",
    "RAG_DEFAULT_STRATEGY",
    "RAG_DEFAULT_TOP_K",
    "RAG_FALLBACK_WARNING",
    "RAG_GROUNDING_MIN_SHARE",
    "RAG_GROUNDING_MIN_WORD",
    "RAG_HEADER",
    "RAG_INDEX_EMPTY_MESSAGE",
    "RAG_VECTOR_WEIGHT",
    "RAG_LLM_ATTEMPTS",
    "RAG_MAX_TOP_K",
    "RAG_RETRY_BACKOFF",
    "RAG_RETRY_SECONDS",
    "RAG_STRATEGIES",
    "RAG_STRATEGY_FIXED",
    "RAG_STRATEGY_STRUCTURAL",
    "RAG_SYSTEM_PROMPT",
    "REASON_RAG_BAD_STRATEGY",
    "REASON_RAG_EMPTY_QUERY",
    "REASON_RAG_INDEX_EMPTY",
    "content_words",
    "fit_context",
    "grounding_share",
    "grounding_verdict",
    "lexical_score",
    "query_weights",
    "rank_candidates",
    "render_context",
    "render_rag_block",
    "resolve_rag_strategy",
]
