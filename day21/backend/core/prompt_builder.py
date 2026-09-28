"""Строитель промптов с кэшируемым стабильным префиксом (день 21).

Зачем модуль. Кэш контекста DeepSeek сопоставляет самый длинный общий префикс
запроса: если начало промпта от запроса к запросу не меняется, его токены
приходят из кэша по сниженной цене (``config.LLM_CACHE_INPUT_RATIO``). Поэтому
промпт собирается строго по зонам, от стабильной к изменчивой:

1. **стабильный префикс** — ``profile → system → invariants → tools → examples →
   general``. Профиль идёт первым: он один и тот же во всех запросах одного
   пользователя, значит именно он должен образовывать общий префикс;
2. **динамическая часть** — блоки ``dynamic`` (текущее состояние задачи, память)
   и блоки ``tool_results`` (результаты инструментов). Эти блоки проходят через
   ``PromptCompressor``: они меняются каждый ход, кэш их не подхватит, поэтому их
   задача — занимать как можно меньше токенов;
3. **хвост** — инструкция о длине ответа. Она стоит последней (кэш-префикс от неё
   не зависит) и только при непустом остальном содержимом: голая инструкция без
   контекста — шум, а пустое system-сообщение обязано остаться пустым.

Стабильный префикс НИКОГДА не сжимается: сжатие меняло бы текст префикса, и кэш
переставал бы попадать. Собранный префикс кладётся в кэш экземпляра по кортежу
непустых частей: повторный вызов получает ту же строку и те же токены без
повторной конкатенации и повторного подсчёта.

Защита от ошибки использования: если в стабильные части попала метка времени или
hex-id (``looks_dynamic``), такой префикс заведомо меняется каждый запрос — это
пишется в лог предупреждением, а префикс в кэш не кладётся (``cache_hit=False``).
Иначе кэш молча «не работал бы», а причина была бы не видна.
"""
from __future__ import annotations

import re
import threading
from typing import (TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional,
                    Sequence, Tuple)

from shared.logging_utils import get_logger
from shared.token_counter import count_tokens

from . import config

if TYPE_CHECKING:  # только для аннотаций: импорт на уровне модуля тянул бы faiss
    from ..services.prompt_compressor import PromptCompressor

logger = get_logger(__name__)

__all__ = [
    "MAX_TOKENS_TEMPLATE",
    "STABLE_PART_ORDER",
    "PromptBuilder",
    "get_prompt_builder",
    "looks_dynamic",
    "reset_prompt_builder",
]

#: Порядок стабильных частей в промпте: он же ключ кэша. Профиль первый — он
#: одинаков во всех запросах пользователя и задаёт самый длинный общий префикс.
STABLE_PART_ORDER: Tuple[str, ...] = (
    "profile", "system", "invariants", "tools", "examples", "general",
)

#: Хвостовая инструкция о длине ответа (последняя зона промпта).
MAX_TOKENS_TEMPLATE = "Отвечай не длиннее {max_tokens} токенов."

#: Признаки изменчивого текста в стабильной части: ISO-подобная метка времени и
#: hex-id (32 символа — дайджест, 8-4-4-4-12 — UUID).
ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?")
HEX_ID_RE = re.compile(r"\b[0-9a-fA-F]{32}\b")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")


def looks_dynamic(text: str) -> bool:
    """Похож ли текст на изменчивый (метка времени или hex-id)?

    Только два признака, оба однозначные: дата-время с часами и хеш-идентификатор.
    Одна дата без времени намеренно не считается (``2026-09-28`` может быть
    частью стабильного профиля), иначе под предупреждение попадали бы честные
    префиксы.
    """
    if not text:
        return False
    return bool(
        ISO_TIMESTAMP_RE.search(text)
        or HEX_ID_RE.search(text)
        or UUID_RE.search(text)
    )


def _stable_parts(profile: str = "", system: str = "", invariants: str = "",
                  tools: str = "", examples: str = "",
                  general: str = "") -> Tuple[Tuple[str, str], ...]:
    """Непустые стабильные части в порядке ``STABLE_PART_ORDER`` (с обрезкой)."""
    given = {"profile": profile, "system": system, "invariants": invariants,
             "tools": tools, "examples": examples, "general": general}
    items: List[Tuple[str, str]] = []
    for name in STABLE_PART_ORDER:
        text = (given.get(name) or "").strip()
        if text:
            items.append((name, text))
    return tuple(items)


def _join(parts: Sequence[str]) -> str:
    """Склеивает непустые части промпта пустой строкой между ними."""
    return "\n\n".join(part for part in parts if part)


class PromptBuilder:
    """Сборка промпта по зонам с кэшем стабильного префикса и статистикой.

    Экземпляр живёт на процесс (см. ``get_prompt_builder``): кэш префикса и
    счётчики попаданий имеют смысл только при переиспользовании, а счётчик
    ``counter`` подменяем — тестам и офлайн-сценариям не нужен tiktoken.
    """

    def __init__(self, *, max_response_tokens: Optional[int] = None,
                 counter: Optional[Callable[[str], int]] = None,
                 max_prefix_tokens: Optional[int] = None,
                 compressor: Optional["PromptCompressor"] = None) -> None:
        self._counter: Callable[[str], int] = counter or count_tokens
        #: Предел длины ответа для этого строителя (пользовательский лимит агента).
        self._max_response_tokens = (config.LLM_MAX_RESPONSE_TOKENS
                                     if max_response_tokens is None
                                     else int(max_response_tokens))
        #: Предел длины стабильного префикса: превышение — предупреждение в лог.
        self._max_prefix_tokens = (config.PROMPT_STABLE_PREFIX_MAX
                                   if max_prefix_tokens is None
                                   else int(max_prefix_tokens))
        self.compressor: "PromptCompressor"
        if compressor is not None:
            self.compressor = compressor
        else:
            # Импорт внутри метода: пакет services/ тянет faiss, sqlalchemy и
            # embeddings, а ``core`` импортируется приложением раньше и чаще —
            # держать эту зависимость на уровне модуля нельзя.
            from ..services.prompt_compressor import PromptCompressor

            self.compressor = PromptCompressor(counter=self._counter)
        #: Кэш стабильных префиксов: кортеж частей → (текст, число токенов).
        self._cache: Dict[Tuple[Tuple[str, str], ...], Tuple[str, int]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._requests = 0
        self._stable_tokens = 0
        self._dynamic_tokens = 0
        self._saved_tokens = 0

    # ---------- наблюдение ----------
    @property
    def cache_hits(self) -> int:
        """Сколько сборок получили стабильный префикс из кэша."""
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        """Сколько сборок собрали стабильный префикс заново."""
        return self._cache_misses

    def stats(self) -> Dict[str, object]:
        """Статистика экземпляра: кэш, токены зон, экономия и доля попаданий."""
        percent = (round(self._cache_hits * 100 / self._requests, 1)
                   if self._requests else 0.0)
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_size": len(self._cache),
            "stable_tokens": self._stable_tokens,
            "dynamic_tokens": self._dynamic_tokens,
            "saved_tokens": self._saved_tokens,
            "requests": self._requests,
            "cache_hit_percent": percent,
        }

    def reset(self) -> None:
        """Обнуляет кэш префиксов и все счётчики (тесты, новый замер)."""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._requests = 0
        self._stable_tokens = 0
        self._dynamic_tokens = 0
        self._saved_tokens = 0

    def max_tokens_for(self, task_type: Optional[str] = None) -> int:
        """Предел длины ответа по типу задачи (без пользовательского зажима).

        Тип задачи выбирает предел из ``config.LLM_TASK_MAX_TOKENS``: ``chat`` —
        1000, ``indexing``/``code`` — 4000, ``summarize`` — 512. Неизвестный или
        отсутствующий тип получает общий предел ``LLM_MAX_RESPONSE_TOKENS``.
        """
        return config.LLM_TASK_MAX_TOKENS.get(task_type, config.LLM_MAX_RESPONSE_TOKENS)

    # ---------- сжатие ----------
    def compress(self, text: str) -> str:
        """Сжать ОДИН динамический блок (стабильный префикс не сжимается никогда).

        Нужен вызывающему коду, который дописывает блоки в промпт уже после
        сборки (результаты пайплайна, оркестрации, поиска по индексу): их тоже
        надо сжать и посчитать токены по факту сжатия. Статистика этого вызова
        живёт в ``self.compressor``, а не в ``stats()`` строителя.
        """
        return self.compressor.compress(text) if text else ""

    # ---------- сборка ----------
    def stable_prefix(self, *, profile: str = "", system: str = "",
                      invariants: str = "", tools: str = "",
                      examples: str = "", general: str = "") -> str:
        """Текст стабильного префикса без обращения к кэшу и счётчикам.

        Порядок частей — ``profile → system → invariants → tools → examples →
        general``; пустые части пропускаются. Если префикс выглядит изменчивым,
        в лог идёт предупреждение: такой префикс потеряет кэш контекста.
        """
        text = _join([part for _, part in _stable_parts(
            profile, system, invariants, tools, examples, general)])
        if looks_dynamic(text):
            _warn_dynamic_prefix()
        return text

    def _cached_prefix(self, parts: Tuple[Tuple[str, str], ...]) -> Tuple[str, bool, int]:
        """Возвращает (текст префикса, попадание в кэш, число токенов).

        При первом вызове текст собирается и кладётся в кэш вместе с числом
        токенов: повторный вызов не пересобирает конкатенацию и не считает токены
        заново. Изменчивый префикс не кэшируется и считается промахом — иначе
        кэш рос бы бесполезными записями, а причина «кэш не работает» была бы
        не видна в логах.
        """
        if not parts:
            return "", False, 0
        text = _join([part for _, part in parts])
        if looks_dynamic(text):
            _warn_dynamic_prefix()
            self._cache_misses += 1
            return text, False, self._counter(text)
        cached = self._cache.get(parts)
        if cached is not None:
            self._cache_hits += 1
            logger.info("стабильный префикс взят из кэша (%d токенов, частей: %d)",
                        cached[1], len(parts))
            return cached[0], True, cached[1]
        self._cache_misses += 1
        tokens = self._counter(text)
        self._cache[parts] = (text, tokens)
        if tokens > self._max_prefix_tokens:
            logger.warning(
                "стабильный префикс промпта — %d токенов, это больше предела %d: "
                "кэшируется целиком, поэтому раздутый префикс дороже остального "
                "промпта", tokens, self._max_prefix_tokens)
        return text, False, tokens

    def build(self, *, system: str = "", profile: str = "", invariants: str = "",
              tools: str = "", examples: str = "", general: str = "",
              dynamic: Sequence[str] = (), tool_results: Sequence[str] = (),
              user_query: str = "", history: Sequence[Mapping[str, Any]] = (),
              max_response_tokens: Optional[int] = None,
              task_type: Optional[str] = None,
              compress: bool = True) -> Dict[str, object]:
        """Собирает payload запроса к модели по зонам промпта.

        Возвращает словарь ровно с ключами ``messages``, ``system``,
        ``max_tokens``, ``stable_tokens``, ``dynamic_tokens``, ``saved_tokens``,
        ``cache_hit``. Сообщение с ролью ``system`` добавляется только при
        непустом тексте: вызывающий код (агент дня 21) сверяет ``system`` с
        пустой строкой, и голая инструкция о длине без контекста была бы шумом.
        """
        parts = _stable_parts(profile, system, invariants, tools, examples, general)
        prefix_text, cache_hit, stable_tokens = self._cached_prefix(parts)

        blocks = [block for block in (*dynamic, *tool_results) if block and block.strip()]
        compressed: List[str] = []
        for block in blocks:
            text = (self.compressor.compress(block) if compress else block).strip()
            if text:
                compressed.append(text)
        dynamic_text = _join(compressed)
        dynamic_tokens = self._counter(dynamic_text) if dynamic_text else 0
        # Экономия — разница между тем, что динамическая зона стоила бы без сжатия,
        # и тем, что она стоит сейчас. Считаем по собранному тексту (с разделителями),
        # иначе счётчик не сходился бы с dynamic_tokens. Без блоков считать нечего —
        # лишний вызов счётчика на пустой строке только шумит в статистике.
        saved_tokens = (self._counter(_join(blocks)) - dynamic_tokens
                        if compress and blocks else 0)
        if saved_tokens:
            logger.info("сжатие динамической части промпта: %d → %d токенов (экономия %d)",
                        dynamic_tokens + saved_tokens, dynamic_tokens, saved_tokens)

        limit = (self._max_response_tokens if max_response_tokens is None
                 else int(max_response_tokens))
        max_tokens = min(self.max_tokens_for(task_type), limit)
        # Хвост с пределом длины идёт вместе со СТАБИЛЬНЫМ ПРЕФИКСОМ: это часть
        # инструкции агенту. Если инструкций нет вовсе (пустой системный промпт,
        # нет профиля и правил), то и ограничивать нечего — промпт остаётся пустым,
        # как и до дня 21. Так «ответ не длиннее N токенов» не появляется там, где
        # никаких других указаний модели не передаётся.
        tail = (MAX_TOKENS_TEMPLATE.format(max_tokens=max_tokens)
                if prefix_text else "")
        system_text = _join([prefix_text, dynamic_text, tail])

        messages: List[Dict[str, Any]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.extend(dict(item) for item in history if item)
        if user_query and user_query.strip():
            messages.append({"role": "user", "content": user_query})

        self._requests += 1
        self._stable_tokens += stable_tokens
        self._dynamic_tokens += dynamic_tokens
        self._saved_tokens += saved_tokens
        return {
            "messages": messages,
            "system": system_text,
            "max_tokens": max_tokens,
            "stable_tokens": stable_tokens,
            "dynamic_tokens": dynamic_tokens,
            "saved_tokens": saved_tokens,
            "cache_hit": cache_hit,
        }


def _warn_dynamic_prefix() -> None:
    """Предупреждение о метке времени/hex-id в стабильной части промпта."""
    logger.warning(
        "стабильный префикс промпта содержит метку времени или hex-id: самый "
        "длинный общий префикс запроса будет меняться, кэш контекста не сработает "
        "— префикс в кэш не кладу")


# --- singleton процесса -------------------------------------------------------
_BUILDER: Optional[PromptBuilder] = None
_BUILDER_LOCK = threading.Lock()


def get_prompt_builder() -> PromptBuilder:
    """Строитель промптов процесса (ленивый singleton под блокировкой)."""
    global _BUILDER
    if _BUILDER is None:
        with _BUILDER_LOCK:
            if _BUILDER is None:
                _BUILDER = PromptBuilder()
    return _BUILDER


def reset_prompt_builder() -> None:
    """Сбрасывает singleton: следующий вызов соберёт строитель заново (тесты)."""
    global _BUILDER
    with _BUILDER_LOCK:
        _BUILDER = None
