"""Стейт-машина прогона индексации: состояния, события и граф переходов (день 21).

Один прогон — один автомат: ``LOADING`` → ``CHUNKING`` → ``EMBEDDING`` →
``INDEXING`` → (``SEARCHING`` → ``COMPARING``) → ``COMPLETED``. События приходят из
цикла прогона (``backend/services/indexing_service.py``), а значения состояний — это
ровно те статусы, что лежат в колонке ``index_runs.status`` и уходят в API и
интерфейс: маппинг не нужен.

Граф переходов однозначен:

===================  ===================================================
состояние            событие → новое состояние
===================  ===================================================
``LOADING``          ``LOADED`` → ``CHUNKING`` (документы собраны);
                     ``FAIL`` → ``FAILED``
``CHUNKING``         ``CHUNKED`` → ``EMBEDDING``;
                     ``FAIL`` → ``FAILED``
``EMBEDDING``        ``EMBEDDED`` → ``INDEXING``;
                     ``FAIL`` → ``FAILED``
``INDEXING``         ``INDEXED`` → ``SEARCHING`` (прогон обеих стратегий);
                     ``DONE`` → ``COMPLETED`` (одиночная стратегия: поиска нет);
                     ``FAIL`` → ``FAILED``
``SEARCHING``        ``SEARCHED`` → ``COMPARING``;
                     ``FAIL`` → ``FAILED``
``COMPARING``        ``COMPARED`` → ``COMPLETED``;
                     ``FAIL`` → ``FAILED``
``COMPLETED``        ``START`` → ``LOADING`` (следующий прогон)
``FAILED``           ``START`` → ``LOADING``
===================  ===================================================

Два выхода из ``INDEXING`` — не неоднозначность: событие ``DONE`` приходит только
от прогона одной стратегии (сравнивать нечего), а ``INDEXED`` — только от
демо-сценария, где дальше идут поиск и сравнение. Терминальный ``COMPLETED``
допускает только ``START``.

Неизвестное событие в состоянии — явная ошибка ``UnknownIndexingEvent`` с перечнем
допустимых: «тихо ничего не сделать» здесь недопустимо, потому что статус прогона
уходит в историю запусков, и по нему судят о результате.

Модуль чистый: ``enum`` и стандартная библиотека (эталон — ``pipeline_fsm.py``).
"""
from __future__ import annotations

import enum
from typing import ClassVar

__all__ = [
    "ALLOWED_TRANSITIONS",
    "HANDLERS",
    "ChunkingPhase",
    "ComparingPhase",
    "CompletedPhase",
    "EmbeddingPhase",
    "FailedPhase",
    "IndexingEvent",
    "IndexingFSM",
    "IndexingState",
    "IndexingPhase",
    "LoadingPhase",
    "SearchingPhase",
    "UnknownIndexingEvent",
    "allowed_events",
]


class IndexingState(enum.Enum):
    """Состояние прогона индексации (оно же — статус запуска в БД и API)."""

    LOADING = "loading"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    SEARCHING = "searching"
    COMPARING = "comparing"
    COMPLETED = "completed"
    FAILED = "failed"


class IndexingEvent(enum.Enum):
    """Событие, которое двигает прогон по графу."""

    LOADED = "loaded"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    DONE = "done"
    SEARCHED = "searched"
    COMPARED = "compared"
    FAIL = "fail"
    START = "start"


class UnknownIndexingEvent(Exception):
    """Событие, недопустимое в текущем состоянии прогона."""

    def __init__(self, state: IndexingState, event: IndexingEvent) -> None:
        self.state = state
        self.event = event
        allowed = ", ".join(item.value for item in allowed_events(state)) or "—"
        super().__init__(
            f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
            f"допустимы: {allowed}"
        )


class IndexingStateHandler:
    """Общий интерфейс состояния: одно событие → ровно одно новое состояние."""

    state: ClassVar[IndexingState]
    transitions: ClassVar[dict[IndexingEvent, IndexingState]]

    def handle(self, event: IndexingEvent) -> IndexingState:
        """Возвращает состояние после события; неизвестное событие — ошибка."""
        try:
            return self.transitions[event]
        except KeyError:
            raise UnknownIndexingEvent(self.state, event) from None


class LoadingPhase(IndexingStateHandler):
    """Документы собираются и читаются; чанков ещё нет."""

    state = IndexingState.LOADING
    transitions = {
        IndexingEvent.LOADED: IndexingState.CHUNKING,
        IndexingEvent.FAIL: IndexingState.FAILED,
    }


class ChunkingPhase(IndexingStateHandler):
    """Документы режутся на чанки обеими (или одной) стратегиями."""

    state = IndexingState.CHUNKING
    transitions = {
        IndexingEvent.CHUNKED: IndexingState.EMBEDDING,
        IndexingEvent.FAIL: IndexingState.FAILED,
    }


class EmbeddingPhase(IndexingStateHandler):
    """Считаются эмбеддинги чанков (батчами, с прогрессом)."""

    state = IndexingState.EMBEDDING
    transitions = {
        IndexingEvent.EMBEDDED: IndexingState.INDEXING,
        IndexingEvent.FAIL: IndexingState.FAILED,
    }


class IndexingPhase(IndexingStateHandler):
    """Векторы и метаданные записываются в FAISS и SQLite.

    Два исхода намеренны: одиночный прогон завершается сразу (``DONE``), а
    демо-сценарий идёт дальше на поиск и сравнение стратегий (``INDEXED``).
    """

    state = IndexingState.INDEXING
    transitions = {
        IndexingEvent.INDEXED: IndexingState.SEARCHING,
        IndexingEvent.DONE: IndexingState.COMPLETED,
        IndexingEvent.FAIL: IndexingState.FAILED,
    }


class SearchingPhase(IndexingStateHandler):
    """По индексу выполняются тестовые запросы (на каждой стратегии)."""

    state = IndexingState.SEARCHING
    transitions = {
        IndexingEvent.SEARCHED: IndexingState.COMPARING,
        IndexingEvent.FAIL: IndexingState.FAILED,
    }


class ComparingPhase(IndexingStateHandler):
    """Считаются метрики сравнения: размеры, покрытие, качество поиска."""

    state = IndexingState.COMPARING
    transitions = {
        IndexingEvent.COMPARED: IndexingState.COMPLETED,
        IndexingEvent.FAIL: IndexingState.FAILED,
    }


class CompletedPhase(IndexingStateHandler):
    """Прогон завершён: индексы построены, метрики посчитаны."""

    state = IndexingState.COMPLETED
    transitions = {IndexingEvent.START: IndexingState.LOADING}


class FailedPhase(IndexingStateHandler):
    """Прогон остановлен ошибкой: состояние и текст ошибки — в строке запуска."""

    state = IndexingState.FAILED
    transitions = {IndexingEvent.START: IndexingState.LOADING}


#: Обработчик на каждое состояние (паттерн State: состояние — объект с поведением).
HANDLERS: dict[IndexingState, IndexingStateHandler] = {
    cls.state: cls()
    for cls in (LoadingPhase, ChunkingPhase, EmbeddingPhase, IndexingPhase,
                SearchingPhase, ComparingPhase, CompletedPhase, FailedPhase)
}

#: Граф допуска: состояние → {событие: новое состояние} (для UI, журнала и тестов).
ALLOWED_TRANSITIONS: dict[IndexingState, dict[IndexingEvent, IndexingState]] = {
    state: dict(handler.transitions) for state, handler in HANDLERS.items()
}


def allowed_events(state: IndexingState) -> tuple[IndexingEvent, ...]:
    """События, допустимые в состоянии (в порядке объявления ``IndexingEvent``)."""
    transitions = ALLOWED_TRANSITIONS.get(state, {})
    return tuple(event for event in IndexingEvent if event in transitions)


class IndexingFSM:
    """Стейт-машина прогона: хранит состояние и делегирует события ему."""

    def __init__(self, state: IndexingState = IndexingState.LOADING) -> None:
        self._state = state

    @property
    def state(self) -> IndexingState:
        """Текущее состояние прогона."""
        return self._state

    def apply(self, event: IndexingEvent) -> IndexingState:
        """Обрабатывает событие и возвращает новое состояние (недопустимое — ошибка)."""
        self._state = HANDLERS[self._state].handle(event)
        return self._state

    def allowed(self) -> tuple[IndexingEvent, ...]:
        """События, допустимые прямо сейчас."""
        return allowed_events(self._state)

    def can(self, event: IndexingEvent) -> bool:
        """Допустимо ли событие в текущем состоянии."""
        return event in ALLOWED_TRANSITIONS.get(self._state, {})
