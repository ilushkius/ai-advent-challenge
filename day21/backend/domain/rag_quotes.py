"""Домен дня 24: порог релевантности, цитаты и оценка опоры ответа.

Модуль держит три вещи, которых нет в соседних доменах:

* настраиваемый порог ``RAG_RELEVANCE_THRESHOLD`` (env → ``.env`` → значение по
  умолчанию). Порог сравнивается с **косинусом** лучшего фрагмента, а не с
  гибридным ``score``: индекс собран на нормализованных эмбеддингах
  (``faiss.IndexFlatIP`` в ``backend/services/index_service.py``), поэтому
  ``vector_score`` ограничен отрезком ``[0, 1]``, а гибридный балл — нет;
* детерминированные цитаты из использованных фрагментов (первое предложение,
  не длиннее ``QUOTE_MAX_CHARS``) — модель в их формировании не участвует;
* проверку того, что ответ опирается на цитаты, и шкалу уверенности.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ..core import config
from . import rag_mode

logger = logging.getLogger(__name__)

__all__ = [
    "CITATION_MIN_SHARE",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_NONE",
    "DONT_KNOW_ANSWER",
    "DONT_KNOW_WARNING",
    "QUOTE_KEYS",
    "QUOTE_MAX_CHARS",
    "QUOTE_SENTENCE_ENDS",
    "RAG_MODE_DONT_KNOW",
    "RAG_MODE_NO_RAG",
    "RAG_MODE_RAG",
    "RAG_RELEVANCE_ENV",
    "RAG_RELEVANCE_THRESHOLD",
    "RAG_RELEVANCE_THRESHOLD_DEFAULT",
    "RAG_RELEVANCE_THRESHOLD_MAX",
    "RAG_RELEVANCE_THRESHOLD_MIN",
    "best_vector_score",
    "citation_block",
    "citation_share",
    "confidence",
    "dont_know_warning",
    "is_weak",
    "normalize",
    "quote_of",
    "quotes_from_items",
    "resolve_relevance_threshold",
    "verify_citations",
]

#: Режимы ответа RAG. ``rag`` — ответ по контексту, ``no_rag`` — модель без RAG,
#: ``dont_know`` — контекста не хватило, модель не вызывалась.
RAG_MODE_RAG = "rag"
RAG_MODE_NO_RAG = "no_rag"
RAG_MODE_DONT_KNOW = "dont_know"

#: Порог релевантности: имя переменной окружения и границы допустимых значений.
RAG_RELEVANCE_ENV = "RAG_RELEVANCE_THRESHOLD"
RAG_RELEVANCE_THRESHOLD_DEFAULT = 0.6
RAG_RELEVANCE_THRESHOLD_MIN = 0.0
RAG_RELEVANCE_THRESHOLD_MAX = 1.0

#: Ответ и предупреждение режима «не знаю».
DONT_KNOW_ANSWER = "Не знаю. Уточните вопрос или дайте больше контекста"
DONT_KNOW_WARNING = (
    "Недостаточно контекста: максимальный балл {score} ниже порога {threshold}"
)

#: Цитата — первое предложение фрагмента, не длиннее этого числа символов.
QUOTE_MAX_CHARS = 200
QUOTE_SENTENCE_ENDS = (". ", "! ", "? ", "…", "\n")
#: Те же концы предложений без обязательного пробела: текст может заканчиваться
#: точкой — тогда срез возвращается целиком, а не режется по последнему пробелу.
_TERMINAL_ENDS = tuple(end[0] for end in QUOTE_SENTENCE_ENDS)

#: Доля ключевых слов цитаты, найденных в ответе, при которой цитата считается
#: подтверждающей: альтернатива точному вхождению (модель пересказывает цитату).
CITATION_MIN_SHARE = 0.3

#: Шкала уверенности: без RAG — 0, ответ без подтверждённых цитат — 0.3, ответ
#: с подтверждёнными цитатами — 1.0.
CONFIDENCE_NONE = 0.0
CONFIDENCE_LOW = 0.3
CONFIDENCE_HIGH = 1.0

#: Поля цитаты; порядок задаёт вид объекта в ответе API и в интерфейсе.
QUOTE_KEYS = ("source", "section", "chunk_id", "quote")


def _env_file_value(name: str, path: Optional[Any]) -> Optional[str]:
    """Читает ``NAME=VALUE`` из файла окружения; ``None``, если ключа нет.

    Имя ключа — параметр (в отличие от ``shared.deepseek_utils``): порог живёт в
    ``day21/.env``, но значение по умолчанию остаётся в этом модуле. Пустые
    строки и комментарии пропускаются, кавычки вокруг значения снимаются.
    """
    if not path:
        return None
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != name:
            continue
        return value.strip().strip('"').strip("'")
    return None


def resolve_relevance_threshold(env: Optional[Mapping[str, str]] = None, path=None) -> float:
    """Порог релевантности: ``env`` → файл ``.env`` → значение по умолчанию.

    ``env=None`` читает процессное окружение (``os.environ``). Не число или
    значение вне ``[0, 1]`` — предупреждение и значение по умолчанию: неверная
    запись в ``.env`` не должна ронять сервис.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    raw = source.get(RAG_RELEVANCE_ENV)
    if not raw:
        raw = _env_file_value(RAG_RELEVANCE_ENV, config.ENV_FILE if path is None else path)
    if not raw:
        return RAG_RELEVANCE_THRESHOLD_DEFAULT
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(
            "%s=%r не число, беру %s", RAG_RELEVANCE_ENV, raw, RAG_RELEVANCE_THRESHOLD_DEFAULT
        )
        return RAG_RELEVANCE_THRESHOLD_DEFAULT
    if not RAG_RELEVANCE_THRESHOLD_MIN <= value <= RAG_RELEVANCE_THRESHOLD_MAX:
        logger.warning(
            "%s=%s вне [%s, %s], беру %s",
            RAG_RELEVANCE_ENV,
            value,
            RAG_RELEVANCE_THRESHOLD_MIN,
            RAG_RELEVANCE_THRESHOLD_MAX,
            RAG_RELEVANCE_THRESHOLD_DEFAULT,
        )
        return RAG_RELEVANCE_THRESHOLD_DEFAULT
    return value


#: Действующий порог: вычисляется на импорте, поэтому правка ``day21/.env``
#: требует перезапуска бэкенда.
RAG_RELEVANCE_THRESHOLD = resolve_relevance_threshold()


def best_vector_score(hits: Optional[Iterable[Any]]) -> float:
    """Максимальный косинус среди фрагментов; пустой список — ``0.0``."""
    return max(
        (float((hit or {}).get("vector_score") or 0.0) for hit in hits or []),
        default=0.0,
    )


def is_weak(hits: Optional[Iterable[Any]], threshold: Optional[float] = None) -> bool:
    """Слабый ли контекст: пусто или лучший косинус ниже порога.

    Порог резолвится в момент вызова (``threshold=None`` — текущая константа
    ``RAG_RELEVANCE_THRESHOLD``), а не защёлкивается при импорте: тесты подменяют
    константу, а вызывающий код может передать своё значение.
    """
    limit = RAG_RELEVANCE_THRESHOLD if threshold is None else float(threshold)
    return not hits or best_vector_score(hits) < limit


def dont_know_warning(hits: Optional[Iterable[Any]], threshold: Optional[float] = None) -> str:
    """Предупреждение режима «не знаю» с баллом и порогом."""
    limit = RAG_RELEVANCE_THRESHOLD if threshold is None else float(threshold)
    return DONT_KNOW_WARNING.format(
        score=f"{best_vector_score(hits):.3f}", threshold=f"{limit:g}"
    )


def normalize(text: Any) -> str:
    """Текст для сравнения: нижний регистр, ``ё``→``е``, одиночные пробелы."""
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def quote_of(text: Any, limit: int = QUOTE_MAX_CHARS) -> str:
    """Цитата: начало текста до конца первого предложения и не длиннее ``limit``.

    Ищем последний конец предложения внутри среза — иначе короткое первое
    предложение не использовалось бы. Если конца предложения нет, режем по
    последнему пробелу, а без пробела возвращаем срез целиком.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    head = flat[:limit]
    cut = max((head.rfind(end) for end in QUOTE_SENTENCE_ENDS), default=-1)
    if cut > 0:
        return head[: cut + 1].strip()
    if head[-1] in _TERMINAL_ENDS:
        return head.strip()
    space = head.rfind(" ")
    if space > 0:
        return head[:space].strip()
    return head


def quotes_from_items(items: Optional[Iterable[Any]]) -> list[dict]:
    """Цитаты использованных фрагментов: по одной на фрагмент, по порядку.

    Пустой текст пропускается; поля цитаты — ``QUOTE_KEYS``. Цитаты берутся из
    чанков детерминированно, поэтому не зависят от того, вставила ли модель
    кавычки в ответ.
    """
    quotes: list[dict] = []
    for item in items or []:
        chunk = item or {}
        quote = quote_of(chunk.get("text"))
        if not quote:
            continue
        quotes.append(
            {
                "source": str(chunk.get("source") or ""),
                "section": str(chunk.get("section") or ""),
                "chunk_id": chunk.get("chunk_id"),
                "quote": quote,
            }
        )
    return quotes


def citation_share(quote: Any, answer: Any) -> float:
    """Доля ключевых слов цитаты, найденных в ответе; пустая цитата — ``0.0``."""
    words = rag_mode.content_words(quote)
    if not words:
        return 0.0
    return len(words & rag_mode.content_words(answer)) / len(words)


def _quote_text(item: Any) -> str:
    """Текст цитаты: строка или элемент с полем ``quote``."""
    if isinstance(item, Mapping):
        return str(item.get("quote") or "")
    return str(item or "")


def verify_citations(answer: Any, quotes: Optional[Iterable[Any]]) -> bool:
    """Опирается ли ответ на цитаты контекста.

    Пустой ответ — ``False``. Иначе ``True``, если хотя бы одна цитата целиком
    входит в ответ (после нормализации) или пересекается с ним по ключевым
    словам не меньше чем на ``CITATION_MIN_SHARE``.
    """
    if not normalize(answer):
        return False
    answer_text = normalize(answer)
    for item in quotes or []:
        text = _quote_text(item)
        normalized = normalize(text)
        if normalized and normalized in answer_text:
            return True
        if text and citation_share(text, answer) >= CITATION_MIN_SHARE:
            return True
    return False


def confidence(verified: bool, mode: str = RAG_MODE_RAG) -> float:
    """Уверенность ответа: 1.0 с подтверждёнными цитатами, 0.3 без, 0.0 без RAG."""
    if mode != RAG_MODE_RAG:
        return CONFIDENCE_NONE
    return CONFIDENCE_HIGH if verified else CONFIDENCE_LOW


def citation_block(answer: Any, items: Optional[Iterable[Any]], mode: str = RAG_MODE_RAG) -> dict:
    """Поля цитат записи ответа: ``quotes``, ``quotes_verified``, ``confidence``."""
    quotes = quotes_from_items(items)
    verified = verify_citations(answer, quotes)
    return {
        "quotes": quotes,
        "quotes_verified": verified,
        "confidence": confidence(verified, mode),
    }
