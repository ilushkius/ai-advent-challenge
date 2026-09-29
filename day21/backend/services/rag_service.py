"""Режим RAG (день 22): поиск по корпусу, ответ с контекстом и без, оценка опоры.

Что делает служба.
    Три шага задачи: ``retrieve`` — поиск релевантных чанков корпуса, ``rag_query`` —
    ответ модели с блоком найденного контекста, ``no_rag_query`` — ответ на тот же
    вопрос без контекста. ``compare`` соединяет два последних, чтобы разница была
    видна в одном ответе API: иначе сравнение расползлось бы по интерфейсу.

Почему отдельный модуль, а не метод дня 21.
    Индексация отвечает на вопрос «что лежит в индексе», RAG — «что ответила модель и
    на чём основан ответ»: два режима ответа, бюджет контекста, повторы, откат и опора.

Корпус и колонка ``strategy``.
    Корпус лежит в ``documents/rag_corpus/`` и индексируется под своими именами
    (``rag_corpus_fixed``, ``rag_corpus_structural``): таблица ``document_chunks``
    и каталог ``index/`` общие, а поиск дня 21 и поиск по корпусу RAG не должны
    мешать друг другу. Новых таблиц нет — мешает только namespace.

Отказы — данные, а не стек.
    ``RAGRejected`` несёт код причины (``bad_strategy``, ``empty_query``,
    ``index_empty``) и переводится роутером в 400/409, ``RAGUpstreamError`` — в 502.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger
from shared.token_counter import count_tokens

from ..core import config
from ..domain import rag_corpus_spec, rag_mode
from ..domain.chunking import ChunkStrategy
from ..storage.chunk_store import ChunkStore
from .chunker import chunk_document
from .index_service import IndexNotBuiltError, IndexService, get_index_service
from .llm_client import LLMCallResult, LLMClient
from .rag_corpus_loader import RagCorpusLoader, get_rag_corpus_loader

logger = get_logger(__name__)

__all__ = [
    "AGENT_ID",
    "CHUNK_STRATEGIES",
    "RAGError",
    "RAGRejected",
    "RAGService",
    "RAGUpstreamError",
    "get_rag_service",
    "make_rag_client",
]

#: Идентификатор в журнале расходов: строки RAG видно отдельно от агентских.
AGENT_ID = "rag"

#: Разбиение текста для каждой стратегии корпуса: имена индексов свои, а код
#: чанкинга общий с днём 21 — иначе у RAG-корпуса появился бы свой третий чанкер.
CHUNK_STRATEGIES = {
    rag_mode.RAG_STRATEGY_FIXED: ChunkStrategy.FIXED,
    rag_mode.RAG_STRATEGY_STRUCTURAL: ChunkStrategy.STRUCTURAL,
}


def make_rag_client() -> Any:
    """Клиент DeepSeek для режима RAG: ключ резолвится в момент вызова.

    Как у проверки инвариантов: служба собирается на старте приложения, а ключ к
    моменту первого обращения к модели может быть ещё не задан.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


class RAGError(Exception):
    """Базовая ошибка режима RAG."""


class RAGRejected(RAGError):
    """Отказ режима RAG: код причины переводится роутером в HTTP-статус."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


class RAGUpstreamError(RAGError):
    """Вызов модели не удался после всех повторов (роутер отвечает 502)."""


class RAGService:
    """Поиск по корпусу, ответ с контекстом и без, оценка опоры на фрагменты."""

    def __init__(self, *, index_service: Optional[IndexService] = None,
                 loader: Optional[RagCorpusLoader] = None,
                 store: Optional[ChunkStore] = None,
                 llm_client: Optional[LLMClient] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._index_service = index_service
        self._loader = loader
        self._store = store
        self._llm_client = llm_client
        self.sleep = sleep

    # ---------- зависимости ----------
    @property
    def index_service(self) -> IndexService:
        """Служба индексов: переданная или служба процесса."""
        if self._index_service is None:
            self._index_service = get_index_service()
        return self._index_service

    @property
    def loader(self) -> RagCorpusLoader:
        """Загрузчик корпуса: переданный или корпус процесса."""
        if self._loader is None:
            self._loader = get_rag_corpus_loader()
        return self._loader

    @property
    def store(self) -> ChunkStore:
        """Хранилище чанков: переданное или хранилище процесса."""
        if self._store is None:
            self._store = ChunkStore()
        return self._store

    @property
    def llm_client(self) -> LLMClient:
        """Обёртка вызова LLM: переданная или собранная на фабрике ключа."""
        if self._llm_client is None:
            self._llm_client = LLMClient(agent_id=AGENT_ID,
                                        client_factory=make_rag_client)
        return self._llm_client

    # ---------- поиск ----------
    def retrieve(self, question: str, top_k: Optional[int] = None,
                 strategy: Optional[str] = None) -> List[dict]:
        """Топ-k чанков корпуса по вопросу (поиск без обращения к модели).

        Публичная форма — то, что нужно интерфейсу: источник, заголовок, раздел,
        идентификатор чанка и оценка. Текст фрагментов остаётся внутри (``_hits``).
        """
        return [self._source(hit) for hit in self._hits(question, top_k, strategy)]

    def _hits(self, question: str, top_k: Optional[int],
              strategy: Optional[str]) -> List[dict]:
        """Проверка входа и поиск по индексу: сырые чанки с текстом."""
        text = str(question or "").strip()
        if not text:
            raise RAGRejected(rag_mode.REASON_RAG_EMPTY_QUERY,
                              "Вопрос пуст: введите текст запроса")
        resolved = rag_mode.resolve_rag_strategy(strategy)
        if resolved is None:
            raise RAGRejected(
                rag_mode.REASON_RAG_BAD_STRATEGY,
                f"Неизвестная стратегия поиска: {strategy!r}",
            )
        limit = self._limit(top_k)
        try:
            hits = self.index_service.search(
                text, top_k=max(rag_mode.RAG_CANDIDATE_POOL, limit), strategy=resolved)
        except IndexNotBuiltError as exc:
            raise RAGRejected(rag_mode.REASON_RAG_INDEX_EMPTY,
                              rag_mode.RAG_INDEX_EMPTY_MESSAGE) from exc
        chunks = self.store.chunks(resolved)
        return rag_mode.rank_candidates(text, hits, chunks, limit)

    @staticmethod
    def _limit(top_k: Optional[int]) -> int:
        """Сколько фрагментов запросить: значение по умолчанию или в границах."""
        if top_k is None:
            return rag_mode.RAG_DEFAULT_TOP_K
        return max(1, min(int(top_k), rag_mode.RAG_MAX_TOP_K))

    @staticmethod
    def _source(hit: Dict[str, Any]) -> dict:
        """Ссылка на использованный фрагмент: пять полей, без текста чанка."""
        return {
            "source": str(hit.get("source") or ""),
            "title": str(hit.get("title") or ""),
            "section": str(hit.get("section") or ""),
            "chunk_id": str(hit.get("chunk_id") or ""),
            "score": round(float(hit.get("score") or 0.0), 4),
        }

    # ---------- ответы ----------
    def rag_query(self, question: str, top_k: Optional[int] = None,
                  strategy: Optional[str] = None) -> dict:
        """Ответ по корпусу: поиск, блок контекста, вызов модели, оценка опоры.

        Сбой вызова не отменяет запрос: результат помечается ``fallback`` и
        предупреждением, и сравнение не выдаёт его за обычный ответ с RAG.
        """
        started = time.perf_counter()
        try:
            return self._answer(question, use_rag=True, top_k=top_k, strategy=strategy)
        except RAGUpstreamError as exc:
            logger.warning("RAG: откат на ответ без RAG (%s)", exc)
            result = self._answer(question, use_rag=False)
            result.update({
                "mode": "rag",
                "fallback": True,
                "warning": rag_mode.RAG_FALLBACK_WARNING.format(error=exc),
                "sources": [],
                "chunks_used": 0,
                "context_tokens": 0,
                "grounding": "",
            })
            result["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return result

    def no_rag_query(self, question: str) -> dict:
        """Ответ на тот же вопрос без контекста: база сравнения.

        Системный промпт тот же, что и у режима с RAG: различие ровно одно — блок
        контекста, иначе сравнение мерило бы ещё и разные инструкции.
        """
        return self._answer(question, use_rag=False)

    def compare(self, question: str, top_k: Optional[int] = None,
                strategy: Optional[str] = None) -> dict:
        """Оба ответа подряд: сначала без RAG, потом с ним — сбой не отнимает базу."""
        without = self.no_rag_query(question)
        with_rag = self.rag_query(question, top_k, strategy)
        return {"question": str(question or "").strip(),
                "no_rag": without, "rag": with_rag}

    def _answer(self, question: str, *, use_rag: bool,
                top_k: Optional[int] = None,
                strategy: Optional[str] = None) -> dict:
        """Общий путь обоих режимов: собрать контекст, вызвать модель, описать результат."""
        text = str(question or "").strip()
        if not text:
            raise RAGRejected(rag_mode.REASON_RAG_EMPTY_QUERY,
                              "Вопрос пуст: введите текст запроса")
        mode = "rag" if use_rag else "no_rag"
        started = time.perf_counter()
        hits: List[dict] = []
        items: List[dict] = []
        context_block = ""
        if use_rag:
            hits = self._hits(text, top_k, strategy)
            items = rag_mode.fit_context(rag_mode.render_context(hits))
            context_block = rag_mode.render_rag_block(items)
        context_tokens = count_tokens(context_block) if context_block else 0
        result = self._call(self.llm_client.generate_with_context,
                            system=rag_mode.RAG_SYSTEM_PROMPT,
                            context=context_block, question=text,
                            task_type=config.LLM_TASK_CHAT, agent_id=AGENT_ID)
        answer = self._text(result)
        grounding = ""
        if use_rag:
            texts = [str(item.get("text") or "") for item in items]
            grounding = rag_mode.grounding_verdict(
                rag_mode.grounding_share(answer, texts))
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "RAG: режим %s, чанков %d, контекст %d токенов, ответ %d токенов, "
            "%d мс, опора: %s",
            mode, len(items), context_tokens,
            int(getattr(result, "completion_tokens", 0) or 0), duration_ms,
            grounding or "—",
        )
        return {
            "mode": mode,
            "question": text,
            "answer": answer,
            "sources": [self._source(hit) for hit in hits],
            "chunks_used": len(items),
            "context_tokens": context_tokens,
            "tokens": self._usage(result),
            "duration_ms": duration_ms,
            "grounding": grounding,
            "fallback": False,
            "warning": "",
        }

    def _call(self, func: Callable[..., LLMCallResult], **kwargs: Any) -> LLMCallResult:
        """Вызов модели с повторами: последний провал — ``RAGUpstreamError``.

        Пауза между попытками растёт по ``RAG_RETRY_BACKOFF``: сбой сети не говорит
        о вопросе ничего, и первый же таймаут не должен выбрасывать строку отчёта.
        """
        last: Optional[Exception] = None
        for attempt in range(rag_mode.RAG_LLM_ATTEMPTS):
            if attempt:
                self.sleep(rag_mode.RAG_RETRY_SECONDS
                           * (rag_mode.RAG_RETRY_BACKOFF ** (attempt - 1)))
            try:
                return func(**kwargs)
            except Exception as exc:  # noqa: BLE001 — повторяем любой сбой вызова
                last = exc
                logger.warning("RAG: попытка %d из %d не удалась: %s",
                               attempt + 1, rag_mode.RAG_LLM_ATTEMPTS, exc)
        raise RAGUpstreamError(f"RAG-запрос не выполнен: {last}") from last

    @staticmethod
    def _text(result: LLMCallResult) -> str:
        """Текст ответа модели: пустой ответ — пустая строка, а не ошибка."""
        choices = getattr(result.response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        return str(getattr(message, "content", "") or "").strip()

    @staticmethod
    def _usage(result: LLMCallResult) -> Optional[dict]:
        """Расход вызова: те же поля, что у ``LLMCallResult.to_dict``, без типа задачи."""
        if result is None:
            return None
        return {
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cache_hit_tokens": result.cache_hit_tokens,
            "cache_miss_tokens": result.cache_miss_tokens,
            "cache_hit_percent": result.cache_hit_percent,
            "cost_estimate": result.cost_estimate,
        }

    # ---------- корпус и конфигурация ----------
    def prepare_corpus(self) -> dict:
        """Собирает корпус заново и строит оба индекса под именами дня 22.

        Пересборка, а не дозапись: ``index_chunks`` умеет только дописывать, поэтому
        индекс предварительно очищается, и повторный прогон даёт то же состояние.
        """
        problems = self.loader.validate()
        if problems:
            raise RAGError("Источники корпуса не готовы: " + "; ".join(problems))
        self.loader.collect()
        documents = self.loader.load_documents()
        indexes: Dict[str, dict] = {}
        counts: Dict[str, int] = {}
        for strategy in rag_mode.RAG_STRATEGIES:
            chunks = [chunk
                      for document in documents
                      for chunk in chunk_document(document, CHUNK_STRATEGIES[strategy])]
            self.index_service.clear_index(strategy)
            indexes[strategy] = self.index_service.index_chunks(chunks, strategy)
            counts[strategy] = len(chunks)
            if len(chunks) < rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS:
                logger.warning("RAG: чанков стратегии %s меньше минимума: %d < %d",
                               strategy, len(chunks),
                               rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS)
        logger.info("Корпус RAG собран: документов %d, чанков %s",
                    len(documents), counts)
        return {
            "corpus": self.loader.status(),
            "indexes": indexes,
            "chunks": counts,
            "min_pages": rag_corpus_spec.RAG_CORPUS_MIN_PAGES,
            "min_chunks": rag_corpus_spec.RAG_CORPUS_MIN_CHUNKS,
        }

    def config(self) -> dict:
        """Готовность режима: объём корпуса, чанки обеих стратегий и лимиты.

        Числа берутся из ``document_chunks``, а не из файлов индекса.
        """
        corpus = self.loader.status()
        indexes = [{"strategy": strategy, "chunks": self.store.count(strategy)}
                   for strategy in rag_mode.RAG_STRATEGIES]
        total = sum(int(item["chunks"]) for item in indexes)
        return {
            "ready": bool(corpus.get("ready")) and total > 0,
            "corpus": corpus,
            "indexes": indexes,
            "chunks_total": total,
            "strategies": list(rag_mode.RAG_STRATEGIES),
            "default_strategy": rag_mode.RAG_DEFAULT_STRATEGY,
            "top_k_default": rag_mode.RAG_DEFAULT_TOP_K,
            "top_k_max": rag_mode.RAG_MAX_TOP_K,
            "context_max_tokens": rag_mode.RAG_CONTEXT_MAX_TOKENS,
            "chunk_max_chars": rag_mode.RAG_CHUNK_MAX_CHARS,
        }


#: Служба процесса: одна на процесс, чтобы журнал расходов и индексы не разъезжались.
_service: Optional[RAGService] = None
_service_lock = threading.Lock()


def get_rag_service() -> RAGService:
    """Служба режима RAG процесса (точка подмены для тестов: ``main.get_rag_service``)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = RAGService()
    return _service
