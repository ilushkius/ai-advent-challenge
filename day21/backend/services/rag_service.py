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

from shared.logging_utils import get_logger
from shared.token_counter import count_tokens

from ..core import config
from ..domain import llm_provider, local_tuning, rag_filter, rag_mode, rag_quotes
from ..domain.local_tuning import TuningProfile
from ..storage.chunk_store import ChunkStore
from . import llm_factory, rag_corpus_index, rag_llm, rag_records
from .index_service import IndexService, get_index_service
from .llm_client import LLMClient
from .rag_corpus_loader import RagCorpusLoader, get_rag_corpus_loader
from .rag_errors import RAGError, RAGRejected, RAGUpstreamError
from .rag_retrieval import RAGRetrieval, RAGStages
from .rerank_service import RerankService, get_rerank_service

logger = get_logger(__name__)

__all__ = [
    "AGENT_ID",
    "RAGService",
    "get_rag_service",
]

#: Идентификатор в журнале расходов: строки RAG видно отдельно от агентских.
AGENT_ID = "rag"


class RAGService:
    """Поиск по корпусу, ответ с контекстом и без, оценка опоры на фрагменты."""

    def __init__(self, *, index_service: Optional[IndexService] = None,
                 loader: Optional[RagCorpusLoader] = None,
                 store: Optional[ChunkStore] = None,
                 llm_client: Optional[LLMClient] = None,
                 rerank_service: Optional[RerankService] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._index_service = index_service
        self._loader = loader
        self._store = store
        self._llm_client = llm_client
        self._llm_clients: Dict[str, Any] = {}
        self._rerank_service = rerank_service
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
    def llm_client(self) -> Any:
        """Обёртка вызова LLM: переданная или собранная на фабрике ключа."""
        return self.llm_client_for(None)

    def llm_client_for(self, provider: Optional[str] = None,
                       profile: Optional[TuningProfile] = None) -> Any:
        """Клиент провайдера: подменённый (тесты) или из кэша пары «провайдер + профиль»
        дня 29: профиль несёт модель и ``num_ctx``, поэтому это разные клиенты."""
        return rag_llm.client_for(
            self._llm_clients, provider, profile, stub=self._llm_client,
            agent_id=AGENT_ID, client_factory=rag_llm.make_rag_client)

    @property
    def rerank_service(self) -> RerankService:
        """Реранкер: переданный или служба процесса (день 23)."""
        if self._rerank_service is None:
            self._rerank_service = get_rerank_service()
        return self._rerank_service

    @property
    def retrieval(self) -> RAGRetrieval:
        """Ступени отбора (день 23): собираются из тех же зависимостей, что и служба."""
        return RAGRetrieval(index_service=self.index_service, store=self.store,
                            rerank_service=self.rerank_service)

    # ---------- поиск ----------
    def retrieve(self, question: str, top_k: Optional[int] = None,
                 strategy: Optional[str] = None,
                 mode: Optional[str] = None,
                 min_score: Optional[float] = None,
                 top_k_candidates: Optional[int] = None,
                 rerank: Optional[bool] = None) -> List[dict]:
        """Топ-k чанков корпуса по вопросу (поиск без обращения к модели).

        Публичная форма — то, что нужно интерфейсу: источник, заголовок, раздел,
        идентификатор чанка и три балла (гибридный, векторный, лексический), плюс
        балл реранкера, если он работал. Текст фрагментов остаётся внутри; провайдера
        здесь нет — отбор локальный, ``provider`` выбирает лишь отвечающего.
        """
        stages = self._stages(question, top_k=top_k, strategy=strategy, mode=mode,
                              min_score=min_score,
                              top_k_candidates=top_k_candidates, rerank=rerank,
                              profile=local_tuning.profile_for(None, None))
        return [rag_records.source(hit) for hit in stages.hits]

    def _stages(self, question: str, *, top_k: Optional[int] = None,
                strategy: Optional[str] = None, mode: Optional[str] = None,
                min_score: Optional[float] = None,
                top_k_candidates: Optional[int] = None,
                rewrite: Optional[bool] = None,
                rerank: Optional[bool] = None,
                provider: Optional[str] = None,
                profile: Optional[TuningProfile] = None) -> RAGStages:
        """Прогоняет режим целиком: переформулировка, поиск, реранк, порог.

        Режим задаёт ручки по умолчанию, явные аргументы их перекрывают: интерфейс
        может включить переформулировку поверх режима ``baseline``.
        """
        name = rag_filter.resolve_rag_mode(mode)
        if name is None:
            raise RAGRejected(rag_filter.REASON_RAG_BAD_MODE,
                              f"Неизвестный режим отбора: {mode!r}")
        knobs = rag_filter.mode_knobs(name)
        wants_rewrite = bool(knobs["rewrite"] if rewrite is None else rewrite)
        query, warning = ("", "")
        if wants_rewrite:
            query, warning = self._rewrite(question, provider, profile)
        stages = self.retrieval.run(question, query=query, top_k=top_k,
                                    strategy=strategy, mode=name,
                                    min_score=min_score,
                                    top_k_candidates=top_k_candidates,
                                    rerank=rerank,
                                    rewrite_warning=warning)
        return stages

    def _rewrite(self, question: str, provider: Optional[str] = None,
                 profile: Optional[TuningProfile] = None) -> tuple[str, str]:
        """Переформулировка запроса моделью: сбой не отменяет поиск по вопросу."""
        try:
            result = rag_llm.call_with_retry(
                self.sleep, self.llm_client_for(provider, profile).generate_with_context,
                system=rag_filter.RAG_REWRITE_SYSTEM_PROMPT, context="",
                question=str(question or "").strip(),
                task_type=config.LLM_TASK_CHAT, agent_id=AGENT_ID)
        except RAGUpstreamError as exc:
            return question, rag_filter.RAG_REWRITE_WARNING.format(error=exc)
        rewritten = rag_llm.response_text(result)
        if not rewritten or len(rewritten) > rag_filter.RAG_REWRITE_MAX_CHARS:
            return question, rag_filter.RAG_REWRITE_EMPTY_WARNING
        logger.info("RAG: вопрос переформулирован (%d → %d символов)",
                    len(str(question or "").strip()), len(rewritten))
        return rewritten, ""

    # ---------- ответы ----------
    def rag_query(self, question: str, top_k: Optional[int] = None,
                  strategy: Optional[str] = None,
                  mode: Optional[str] = None,
                  min_score: Optional[float] = None,
                  top_k_candidates: Optional[int] = None,
                  rerank: Optional[bool] = None,
                  rewrite: Optional[bool] = None,
                  provider: Optional[str] = None,
                  profile: Optional[TuningProfile] = None) -> dict:
        """Ответ по корпусу: поиск, блок контекста, вызов модели, оценка опоры.

        Сбой вызова не отменяет запрос: результат помечается ``fallback`` и
        предупреждением, и сравнение не выдаёт его за обычный ответ с RAG.
        ``provider`` выбирает, кто отвечает (``deepseek``/``local``); он же попадает
        в запись ответа, чтобы отчёт и интерфейс не догадывались об этом по тексту.
        ``profile`` (день 29) задаёт параметры вызова и промпт вызова.
        """
        started = time.perf_counter()
        profile = local_tuning.profile_for(provider, profile)
        knobs = {"mode": mode, "min_score": min_score, "provider": provider,
                 "top_k_candidates": top_k_candidates,
                 "rerank": rerank, "rewrite": rewrite}
        try:
            return self._answer(question, use_rag=True, top_k=top_k,
                                strategy=strategy, profile=profile, **knobs)
        except RAGUpstreamError as exc:
            logger.warning("RAG: откат на ответ без RAG (%s)", exc)
            result = self._answer(question, use_rag=False, provider=provider,
                                  profile=profile)
            result.update({
                "mode": "rag",
                "fallback": True,
                "warning": rag_mode.RAG_FALLBACK_WARNING.format(error=exc),
                "sources": [],
                "chunks_used": 0,
                "context_tokens": 0,
                "grounding": "",
                "quotes": [],
                "quotes_verified": False,
                "confidence": 0.0,
            })
            result["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return result

    def no_rag_query(self, question: str, provider: Optional[str] = None,
                     profile: Optional[TuningProfile] = None) -> dict:
        """Ответ на тот же вопрос без контекста: база сравнения.

        Системный промпт тот же, что и у режима с RAG: различие ровно одно — блок
        контекста, иначе сравнение мерило бы ещё и разные инструкции.
        """
        return self._answer(question, use_rag=False, provider=provider,
                            profile=local_tuning.profile_for(provider, profile))

    def compare(self, question: str, top_k: Optional[int] = None,
                strategy: Optional[str] = None,
                mode: Optional[str] = None,
                min_score: Optional[float] = None,
                top_k_candidates: Optional[int] = None,
                rerank: Optional[bool] = None,
                rewrite: Optional[bool] = None) -> dict:
        """Оба ответа подряд: сначала без RAG, потом с ним — сбой не отнимает базу."""
        without = self.no_rag_query(question)
        with_rag = self.rag_query(question, top_k, strategy, mode=mode,
                                  min_score=min_score,
                                  top_k_candidates=top_k_candidates,
                                  rerank=rerank, rewrite=rewrite)
        return {"question": str(question or "").strip(),
                "no_rag": without, "rag": with_rag}

    def compare_modes(self, question: str, top_k: Optional[int] = None,
                      strategy: Optional[str] = None,
                      min_score: Optional[float] = None,
                      top_k_candidates: Optional[int] = None,
                      modes: Optional[List[str]] = None) -> dict:
        """Один вопрос по нескольким режимам отбора: сравнение ступеней в одном ответе.

        Незнакомые имена отбрасываются, но если в запросе нет ни одного известного —
        это отказ: иначе интерфейс показал бы пустой список как «режимов нет».
        """
        names = [name for name in (modes or rag_filter.RAG_MODES)
                 if rag_filter.resolve_rag_mode(name)]
        if not names:
            raise RAGRejected(rag_filter.REASON_RAG_BAD_MODE,
                              f"Неизвестный режим отбора: {modes!r}")
        entries = []
        for name in names:
            knobs = rag_filter.mode_knobs(name)
            if min_score is not None:
                knobs["min_score"] = min_score
            record = self.rag_query(question, top_k, strategy,
                                    top_k_candidates=top_k_candidates, **knobs)
            entries.append({"mode": name,
                            "label": rag_filter.RAG_MODE_LABELS[name],
                            "result": record})
        return {"question": str(question or "").strip(), "modes": entries}

    def _answer(self, question: str, *, use_rag: bool,
                top_k: Optional[int] = None,
                strategy: Optional[str] = None,
                mode: Optional[str] = None,
                min_score: Optional[float] = None,
                top_k_candidates: Optional[int] = None,
                rerank: Optional[bool] = None,
                rewrite: Optional[bool] = None,
                provider: Optional[str] = None,
                profile: Optional[TuningProfile] = None) -> dict:
        """Общий путь обоих режимов: собрать контекст, вызвать модель, описать результат."""
        text = str(question or "").strip()
        if not text:
            raise RAGRejected(rag_mode.REASON_RAG_EMPTY_QUERY,
                              "Вопрос пуст: введите текст запроса")
        name = "rag" if use_rag else "no_rag"
        provider_name = llm_provider.resolve(provider)
        started = time.perf_counter()
        stages: Optional[RAGStages] = None
        items: List[dict] = []
        context_block = ""
        if use_rag:
            stages = self._stages(text, top_k=top_k, strategy=strategy, mode=mode,
                                  min_score=min_score,
                                  top_k_candidates=top_k_candidates,
                                  rerank=rerank, rewrite=rewrite, provider=provider)
            # Слабый контекст — режим «не знаю» без вызова модели. Порог сравнивается с
            # косинусом лучшего из рассмотренных кандидатов, а не только с итоговыми
            # фрагментами: гибридный отбор ранжирует буквальные совпадения выше
            # векторных, и максимум по пяти фрагментам падает до нуля у вопросов,
            # ответ на которые в корпусе есть (замер: 0.0 против 0.62 по пулу).
            if not stages.hits or rag_quotes.is_weak(stages.candidates):
                return {**rag_records.dont_know(
                    text, stages, int((time.perf_counter() - started) * 1000)),
                    "provider": provider_name}
            items = rag_mode.fit_context(rag_mode.render_context(stages.hits))
            context_block = rag_mode.render_rag_block(items)
        context_tokens = count_tokens(context_block) if context_block else 0
        result = rag_llm.answer(
            self.sleep, self.llm_client_for(provider, profile),
            system=local_tuning.prompt_for(profile, rag_mode.RAG_SYSTEM_PROMPT),
            context=context_block, question=text, agent_id=AGENT_ID, profile=profile)
        answer = rag_llm.response_text(result)
        grounding = ""
        if stages is not None:
            texts = [str(item.get("text") or "") for item in items]
            grounding = rag_mode.grounding_verdict(
                rag_mode.grounding_share(answer, texts))
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "RAG: режим %s, провайдер %s, профиль %s, запрос %s, чанков %d из %d, "
            "контекст %d токенов, ответ %d токенов, %d мс, опора: %s",
            name, provider_name, profile.name if profile is not None else "—",
            stages.mode if stages else "—", len(stages.hits) if stages else 0,
            len(stages.candidates) if stages else 0, context_tokens,
            rag_llm.completion_tokens(result), duration_ms, grounding or "—")
        record = {
            "mode": name,
            "question": text,
            "answer": answer,
            "provider": provider_name,
            "sources": [rag_records.source(hit)
                        for hit in (stages.hits if stages else [])],
            "chunks_used": len(items),
            "context_tokens": context_tokens,
            "tokens": rag_llm.usage_dict(result),
            "duration_ms": duration_ms,
            "grounding": grounding,
            "fallback": False,
            "warning": "",
        }
        record.update(rag_records.selection(stages))
        record.update(rag_quotes.citation_block(answer, items, name))
        return record

    # ---------- корпус и конфигурация ----------
    def prepare_corpus(self) -> dict:
        """Собирает корпус заново и строит оба индекса под именами дня 22.

        Пересборка, а не дозапись: ``index_chunks`` умеет только дописывать, поэтому
        индекс предварительно очищается, и повторный прогон даёт то же состояние.
        """
        return rag_corpus_index.prepare_corpus(self.loader, self.index_service)

    def config(self) -> dict:
        """Готовность режима: объём корпуса, чанки обеих стратегий, лимиты и режимы отбора.

        Числа берутся из ``document_chunks``, а не из файлов индекса; список режимов —
        тот же, что принимает ``/rag/query``, поэтому интерфейс не дублирует имена.
        """
        return {
            **rag_corpus_index.corpus_config(self.loader, self.store),
            "modes": rag_filter.mode_catalog(),
            "rerank_model": rag_filter.RAG_RERANK_MODEL,
            "min_score_default": rag_filter.RAG_FILTER_MIN_SCORE,
            "candidates_max": rag_filter.RAG_MAX_CANDIDATES,
            "relevance_threshold": rag_quotes.RAG_RELEVANCE_THRESHOLD,
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
