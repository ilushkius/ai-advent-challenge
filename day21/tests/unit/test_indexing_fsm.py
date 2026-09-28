"""Стейт-машина прогона индексации: таблица переходов и негативный сценарий (день 21).

Параметризованная таблица перебирает ВСЕ допустимые пары (состояние, событие) →
новое состояние, а негативные проверки требуют явной ошибки на недопустимый шаг:
статус прогона уходит в историю запусков, и «тихо ничего не сделать» было бы худшим
исходом, чем отказ.
"""
import pytest

from backend.domain.indexing_fsm import (
    ALLOWED_TRANSITIONS,
    HANDLERS,
    IndexingEvent,
    IndexingFSM,
    IndexingState,
    UnknownIndexingEvent,
    allowed_events,
)

#: Полная таблица: (состояние, событие) → состояние после события.
TRANSITIONS = [
    (IndexingState.LOADING, IndexingEvent.LOADED, IndexingState.CHUNKING),
    (IndexingState.LOADING, IndexingEvent.FAIL, IndexingState.FAILED),
    (IndexingState.CHUNKING, IndexingEvent.CHUNKED, IndexingState.EMBEDDING),
    (IndexingState.CHUNKING, IndexingEvent.FAIL, IndexingState.FAILED),
    (IndexingState.EMBEDDING, IndexingEvent.EMBEDDED, IndexingState.INDEXING),
    (IndexingState.EMBEDDING, IndexingEvent.FAIL, IndexingState.FAILED),
    (IndexingState.INDEXING, IndexingEvent.INDEXED, IndexingState.SEARCHING),
    (IndexingState.INDEXING, IndexingEvent.DONE, IndexingState.COMPLETED),
    (IndexingState.INDEXING, IndexingEvent.FAIL, IndexingState.FAILED),
    (IndexingState.SEARCHING, IndexingEvent.SEARCHED, IndexingState.COMPARING),
    (IndexingState.SEARCHING, IndexingEvent.FAIL, IndexingState.FAILED),
    (IndexingState.COMPARING, IndexingEvent.COMPARED, IndexingState.COMPLETED),
    (IndexingState.COMPARING, IndexingEvent.FAIL, IndexingState.FAILED),
    (IndexingState.COMPLETED, IndexingEvent.START, IndexingState.LOADING),
    (IndexingState.FAILED, IndexingEvent.START, IndexingState.LOADING),
]


@pytest.mark.parametrize("state,event,expected", TRANSITIONS)
def test_transition_table(state, event, expected):
    """Каждая допустимая пара (состояние, событие) даёт ровно одно новое состояние."""
    assert HANDLERS[state].handle(event) is expected
    assert ALLOWED_TRANSITIONS[state][event] is expected


def test_every_state_has_handler_and_entry():
    """У каждого состояния есть обработчик и хотя бы одно допустимое событие."""
    handlers = {handler.state for handler in HANDLERS.values()}
    assert handlers == set(IndexingState)
    assert all(allowed_events(state) for state in IndexingState)


@pytest.mark.parametrize("state,event", [
    (IndexingState.LOADING, IndexingEvent.CHUNKED),
    (IndexingState.LOADING, IndexingEvent.START),
    (IndexingState.CHUNKING, IndexingEvent.LOADED),
    (IndexingState.EMBEDDING, IndexingEvent.CHUNKED),
    (IndexingState.INDEXING, IndexingEvent.EMBEDDED),
    (IndexingState.SEARCHING, IndexingEvent.INDEXED),
    (IndexingState.COMPARING, IndexingEvent.SEARCHED),
    (IndexingState.COMPLETED, IndexingEvent.DONE),
    (IndexingState.COMPLETED, IndexingEvent.FAIL),
    (IndexingState.FAILED, IndexingEvent.LOADED),
])
def test_unknown_event_is_explicit_error(state, event):
    """Недопустимое событие в состоянии — явная ошибка с перечнем допустимых."""
    fsm = IndexingFSM(state)
    with pytest.raises(UnknownIndexingEvent) as exc:
        fsm.apply(event)
    assert event.value in str(exc.value)
    assert state.value in str(exc.value)


def test_terminal_completed_accepts_only_start():
    """Терминальный ``completed`` допускает только старт нового прогона."""
    assert allowed_events(IndexingState.COMPLETED) == (IndexingEvent.START,)


def test_allowed_events_order_follows_event_declaration():
    """Список допустимых событий идёт в порядке объявления ``IndexingEvent``."""
    assert allowed_events(IndexingState.LOADING) == (IndexingEvent.LOADED,
                                                     IndexingEvent.FAIL)


def test_fsm_walks_full_demo_path():
    """Полный путь демо-прогона: загрузка → чанкинг → эмбеддинги → индекс → поиск → сравнение."""
    fsm = IndexingFSM()
    assert fsm.state is IndexingState.LOADING
    assert fsm.apply(IndexingEvent.LOADED) is IndexingState.CHUNKING
    assert fsm.apply(IndexingEvent.CHUNKED) is IndexingState.EMBEDDING
    assert fsm.apply(IndexingEvent.EMBEDDED) is IndexingState.INDEXING
    assert fsm.apply(IndexingEvent.INDEXED) is IndexingState.SEARCHING
    assert fsm.apply(IndexingEvent.SEARCHED) is IndexingState.COMPARING
    assert fsm.apply(IndexingEvent.COMPARED) is IndexingState.COMPLETED
    assert fsm.allowed() == (IndexingEvent.START,)


def test_fsm_single_strategy_finishes_without_search():
    """Одиночная стратегия завершается из ``indexing`` без поиска и сравнения."""
    fsm = IndexingFSM(IndexingState.INDEXING)
    assert fsm.can(IndexingEvent.DONE) is True
    assert fsm.can(IndexingEvent.INDEXED) is True
    assert fsm.apply(IndexingEvent.DONE) is IndexingState.COMPLETED


def test_fsm_failure_from_any_working_state():
    """Сбой из любого рабочего состояния переводит прогон в ``failed``."""
    for state in (IndexingState.LOADING, IndexingState.CHUNKING,
                  IndexingState.EMBEDDING, IndexingState.INDEXING,
                  IndexingState.SEARCHING, IndexingState.COMPARING):
        assert IndexingFSM(state).apply(IndexingEvent.FAIL) is IndexingState.FAILED


def test_fsm_restart_after_failure():
    """После сбоя прогон можно начать заново (``START``)."""
    fsm = IndexingFSM(IndexingState.FAILED)
    assert fsm.apply(IndexingEvent.START) is IndexingState.LOADING
