"""Этапы отбора RAG: гибридный поиск, реранкер и порог отсечения (день 23).

Служба дня 22 умела ровно один отбор: поиск FAISS плюс словесные веса. Здесь тот же
путь разложен на ступени, чтобы режимы (``rerank``, ``rerank_filter``) включались по
одной, а интерфейс и отчёт видели «до и после» каждой ступени: ``RAGStages`` несёт и
весь пул кандидатов, и то, что осталось после отсечения.

LLM внутрь не попадает: переформулировку вопроса делает ``RAGService``, у которого
уже есть политика повторов вызова. Поэтому сбой реранкера (необязательной ступени)
не стоит ответа: он превращается в предупреждение, а порядок фрагментов остаётся
таким же, каким его отдал гибридный поиск дня 22.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional

from shared.logging_utils import get_logger

from ..domain import rag_filter, rag_mode
from ..storage.chunk_store import ChunkStore
from .index_service import IndexNotBuiltError, IndexService, get_index_service
from .rag_errors import RAGRejected
from .rerank_service import RerankError, RerankService, get_rerank_service

logger = get_logger(__name__)

__all__ = ["RAGRetrieval", "RAGStages"]


class RAGStages(NamedTuple):
    """Что случилось на каждой ступени отбора: вход, пул кандидатов и результат."""

    #: Исходный вопрос пользователя (может отличаться от текста поиска).
    question: str
    #: Текст, по которому реально искали: переформулировка или сам вопрос.
    query: str
    #: Нормализованное имя режима отбора (``baseline``…``rerank_filter``).
    mode: str
    #: Строка индекса, по которой шёл поиск.
    strategy: str
    #: Сколько фрагментов просили на выходе (top-K после отсечения).
    limit: int
    #: Сколько кандидатов запрошено у поиска (размер пула до отсечения).
    candidate_limit: int
    #: Порог отсечения, если он применялся.
    min_score: Optional[float]
    #: По какому полю шло отсечение и сортировка (``score`` или ``rerank_score``).
    score_field: str
    #: Весь пул кандидатов с баллами — порядок ДО отсечения.
    candidates: List[dict]
    #: Фрагменты ПОСЛЕ отсечения, обрезанные до ``limit``.
    hits: List[dict]
    #: Состоялась ли пересортировка: сбой реранкера даёт ``False`` и предупреждение.
    reranked: bool
    #: Предупреждение реранкера (пусто, если ступень прошла).
    rerank_warning: str
    #: Предупреждение переформулировки: её делает служба, а хранит отчёт этап отбора.
    rewrite_warning: str = ""


class RAGRetrieval:
    """Цепочка «поиск → реранк → порог»: владеет индексом, чанками и реранкером."""

    def __init__(self, *, index_service: Optional[IndexService] = None,
                 store: Optional[ChunkStore] = None,
                 rerank_service: Optional[RerankService] = None) -> None:
        self._index_service = index_service
        self._store = store
        self._rerank_service = rerank_service

    # ---------- зависимости ----------
    @property
    def index_service(self) -> IndexService:
        """Служба индексов: переданная или служба процесса."""
        if self._index_service is None:
            self._index_service = get_index_service()
        return self._index_service

    @property
    def store(self) -> ChunkStore:
        """Хранилище чанков: переданное или хранилище процесса."""
        if self._store is None:
            self._store = ChunkStore()
        return self._store

    @property
    def rerank_service(self) -> RerankService:
        """Служба реранкера: переданная или служба процесса."""
        if self._rerank_service is None:
            self._rerank_service = get_rerank_service()
        return self._rerank_service

    # ---------- отбор ----------
    def run(self, question: str, *, query: Optional[str] = None,
            top_k: Optional[int] = None, strategy: Optional[str] = None,
            mode: Optional[str] = None, min_score: Optional[float] = None,
            top_k_candidates: Optional[int] = None,
            rerank: Optional[bool] = None,
            rewrite_warning: str = "") -> RAGStages:
        """Прогоняет ступени отбора и описывает результат целиком.

        Явные аргументы перекрывают режим: ``rerank=False`` выключает кросс-энкодер
        даже в режиме ``rerank``, а порог без реранкера трактуется как порог по
        гибридному баллу (шкала — доля словесных весов плюс вектор, не ``[0, 1]``).
        """
        text = str(question or "").strip()
        if not text:
            raise RAGRejected(rag_mode.REASON_RAG_EMPTY_QUERY,
                              "Вопрос пуст: введите текст запроса")
        resolved = rag_mode.resolve_rag_strategy(strategy)
        if resolved is None:
            raise RAGRejected(rag_mode.REASON_RAG_BAD_STRATEGY,
                              f"Неизвестная стратегия поиска: {strategy!r}")
        name = rag_filter.resolve_rag_mode(mode)
        if name is None:
            raise RAGRejected(rag_filter.REASON_RAG_BAD_MODE,
                              f"Неизвестный режим отбора: {mode!r}")
        knobs = rag_filter.mode_knobs(name)
        requested = bool(knobs["rerank"] if rerank is None else rerank)
        threshold = min_score
        if requested and threshold is None:
            threshold = knobs["min_score"]
        search_text = str(query or "").strip() or text
        limit = self._limit(top_k)
        pool = self._candidate_limit(limit, top_k_candidates)
        raw = self._search(search_text, resolved, pool)
        # Сырая близость FAISS сохраняется ДО гибридного ранжирования: оно затирает
        # поле `score` итоговым баллом, и иначе «нашлось вектором» было бы не видно.
        prepared = [{**hit, "vector_score": round(float(hit.get("score") or 0.0), 4)}
                    for hit in raw]
        candidates = rag_mode.rank_candidates(search_text, prepared,
                                              self.store.chunks(resolved), pool)
        warning = ""
        applied = False
        field = rag_filter.SCORE_FIELD_HYBRID
        if requested:
            candidates, warning = self._rerank(search_text, candidates)
            applied = not warning
            if applied:
                field = rag_filter.SCORE_FIELD_RERANK
            elif min_score is None:
                # Порог режима задан на шкале реранкера: без баллов реранкера он
                # смысла не имеет, а гибридный балл живёт на своей шкале. Явный
                # порог пользователя при этом остаётся в силе.
                threshold = None
        hits = rag_filter.filter_hits(candidates, threshold, field)[:limit]
        return RAGStages(
            question=text, query=search_text, mode=name, strategy=resolved,
            limit=limit, candidate_limit=pool, min_score=threshold,
            score_field=field, candidates=candidates, hits=hits,
            reranked=applied, rerank_warning=warning,
            rewrite_warning=rewrite_warning,
        )

    @staticmethod
    def _limit(top_k: Optional[int]) -> int:
        """Сколько фрагментов запросить: значение по умолчанию или в границах."""
        if top_k is None:
            return rag_mode.RAG_DEFAULT_TOP_K
        return max(1, min(int(top_k), rag_mode.RAG_MAX_TOP_K))

    @staticmethod
    def _candidate_limit(limit: int, top_k_candidates: Optional[int]) -> int:
        """Размер пула кандидатов: как в дне 22 или запрошенный в границах."""
        if top_k_candidates is None:
            return max(rag_mode.RAG_CANDIDATE_POOL, limit)
        return max(limit, min(int(top_k_candidates), rag_filter.RAG_MAX_CANDIDATES))

    def _search(self, text: str, strategy: str, pool: int) -> List[dict]:
        """Сырые попадания индекса: единственное место, знающее про пустой индекс."""
        try:
            return self.index_service.search(text, top_k=pool, strategy=strategy)
        except IndexNotBuiltError as exc:
            raise RAGRejected(rag_mode.REASON_RAG_INDEX_EMPTY,
                              rag_mode.RAG_INDEX_EMPTY_MESSAGE) from exc

    def _rerank(self, query: str, hits: List[dict]) -> tuple[List[dict], str]:
        """Пересортировка кросс-энкодером: сбой ступени — предупреждение, не отказ."""
        try:
            scores = self.rerank_service.score(
                query, [rag_filter.candidate_text(hit) for hit in hits])
        except RerankError as exc:
            warning = rag_filter.RAG_RERANK_WARNING.format(error=exc)
            logger.warning("RAG: %s", warning)
            return hits, warning
        return rag_filter.apply_rerank(hits, scores), ""
