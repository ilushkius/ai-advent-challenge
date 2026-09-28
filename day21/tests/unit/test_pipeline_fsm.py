"""Тесты стейт-машины прогона пайплайна: состояния, события и граф переходов (день 19).

Граф маленький, но именно он решает, каким статусом закончится запуск и что попадёт в
колонку ``pipeline_runs.status``: недопустимое событие обязано быть явной ошибкой, а не
«тихой» сменой статуса. Проверяются все объявленные переходы, все запрещённые пары из
рабочих состояний, порядок ``allowed_events`` (он же — подсказка в тексте ошибки) и то,
что значения ``enum`` совпадают со статусами БД и API без маппинга.
"""
import enum

import pytest

from backend.domain.pipeline_fsm import (
    ALLOWED_TRANSITIONS,
    HANDLERS,
    PipelineEvent,
    PipelineFSM,
    PipelineState,
    UnknownPipelineEvent,
    allowed_events,
)

#: Все допустимые переходы графа: состояние, событие → новое состояние.
TRANSITIONS = (
    (PipelineState.IDLE, PipelineEvent.START, PipelineState.RUNNING),
    (PipelineState.RUNNING, PipelineEvent.ADVANCE, PipelineState.RUNNING),
    (PipelineState.RUNNING, PipelineEvent.FINISH, PipelineState.COMPLETED),
    (PipelineState.RUNNING, PipelineEvent.STOP, PipelineState.STOPPED),
    (PipelineState.RUNNING, PipelineEvent.FAIL, PipelineState.FAILED),
    (PipelineState.COMPLETED, PipelineEvent.START, PipelineState.RUNNING),
    (PipelineState.STOPPED, PipelineEvent.START, PipelineState.RUNNING),
    (PipelineState.FAILED, PipelineEvent.START, PipelineState.RUNNING),
)

#: Запрещённые пары: событие не того шага, повторный старт из ``RUNNING`` либо
#: действие, которое уже невозможно после терминального состояния.
FORBIDDEN = (
    (PipelineState.IDLE, PipelineEvent.ADVANCE),
    (PipelineState.IDLE, PipelineEvent.FINISH),
    (PipelineState.IDLE, PipelineEvent.STOP),
    (PipelineState.IDLE, PipelineEvent.FAIL),
    (PipelineState.RUNNING, PipelineEvent.START),
    (PipelineState.COMPLETED, PipelineEvent.ADVANCE),
    (PipelineState.COMPLETED, PipelineEvent.FINISH),
    (PipelineState.COMPLETED, PipelineEvent.STOP),
    (PipelineState.COMPLETED, PipelineEvent.FAIL),
    (PipelineState.STOPPED, PipelineEvent.ADVANCE),
    (PipelineState.STOPPED, PipelineEvent.FAIL),
    (PipelineState.FAILED, PipelineEvent.ADVANCE),
    (PipelineState.FAILED, PipelineEvent.STOP),
)

#: Значения состояний — это ровно статусы запуска в БД и API.
STATE_VALUES = (
    (PipelineState.IDLE, "idle"),
    (PipelineState.RUNNING, "running"),
    (PipelineState.COMPLETED, "completed"),
    (PipelineState.STOPPED, "stopped"),
    (PipelineState.FAILED, "failed"),
)

#: Значения событий — строки, которыми прогон двигают из цикла шагов.
EVENT_VALUES = (
    (PipelineEvent.START, "start"),
    (PipelineEvent.ADVANCE, "advance"),
    (PipelineEvent.FINISH, "finish"),
    (PipelineEvent.STOP, "stop"),
    (PipelineEvent.FAIL, "fail"),
)

#: Ожидаемый набор допустимых событий на каждое состояние (порядок объявления).
EXPECTED_ALLOWED = (
    (PipelineState.IDLE, (PipelineEvent.START,)),
    (PipelineState.RUNNING, (
        PipelineEvent.ADVANCE,
        PipelineEvent.FINISH,
        PipelineEvent.STOP,
        PipelineEvent.FAIL,
    )),
    (PipelineState.COMPLETED, (PipelineEvent.START,)),
    (PipelineState.STOPPED, (PipelineEvent.START,)),
    (PipelineState.FAILED, (PipelineEvent.START,)),
)


@pytest.mark.parametrize("state,event,expected", TRANSITIONS)
def test_allowed_transitions(state, event, expected):
    """Каждая допустимая пара переводит машину ровно в объявленное состояние."""
    fsm = PipelineFSM(state)

    assert fsm.handle(event) is expected
    assert fsm.state is expected


@pytest.mark.parametrize("state,event", FORBIDDEN)
def test_forbidden_event_is_explicit_error(state, event):
    """Недопустимое событие — ошибка с перечнем допустимых; состояние не меняется."""
    fsm = PipelineFSM(state)

    with pytest.raises(UnknownPipelineEvent) as exc:
        fsm.handle(event)

    allowed = ", ".join(item.value for item in allowed_events(state))
    assert str(exc.value) == (
        f"Событие {event.value!r} недопустимо в состоянии {state.value!r}; "
        f"допустимы: {allowed}"
    )
    assert (exc.value.state, exc.value.event) == (state, event)
    assert fsm.state is state


def test_error_text_names_state_event_and_allowed_list():
    """Текст ошибки годится для журнала: видны состояние, событие и что делать."""
    with pytest.raises(UnknownPipelineEvent) as exc:
        PipelineFSM().handle(PipelineEvent.ADVANCE)

    assert str(exc.value) == (
        "Событие 'advance' недопустимо в состоянии 'idle'; допустимы: start"
    )


@pytest.mark.parametrize("member,value", STATE_VALUES)
def test_state_values_are_run_statuses(member, value):
    """Значения ``PipelineState`` — строки статусов запуска, попадающие в БД без маппинга."""
    assert isinstance(member, PipelineState)
    assert member.value == value


@pytest.mark.parametrize("member,value", EVENT_VALUES)
def test_event_values(member, value):
    """Значения ``PipelineEvent`` — короткие строки-события графа прогона."""
    assert isinstance(member, PipelineEvent)
    assert member.value == value


def test_enums_are_plain_enums():
    """Обе таблицы — обычные ``enum.Enum``: контракт со статусами БД и API."""
    assert issubclass(PipelineState, enum.Enum)
    assert issubclass(PipelineEvent, enum.Enum)
    assert not issubclass(PipelineState, str)
    assert len(PipelineState) == len(STATE_VALUES)
    assert len(PipelineEvent) == len(EVENT_VALUES)


@pytest.mark.parametrize("state,expected", EXPECTED_ALLOWED)
def test_allowed_events_follow_declaration_order(state, expected):
    """``allowed_events`` перечисляет события в порядке объявления ``PipelineEvent``."""
    assert allowed_events(state) == expected


def test_transition_table_has_entry_for_every_state():
    """Таблица допуска описана для каждого состояния, и она — копия переходов классов."""
    for state, handler in HANDLERS.items():
        assert handler.state is state
        assert state in ALLOWED_TRANSITIONS
        assert ALLOWED_TRANSITIONS[state] == handler.transitions

    assert set(ALLOWED_TRANSITIONS) == set(PipelineState)


def test_transition_table_entries_are_copies():
    """Таблица допуска — снимок переходов: её правка не меняет поведение обработчиков."""
    for state, handler in HANDLERS.items():
        assert ALLOWED_TRANSITIONS[state] is not handler.transitions


def test_can_and_allowed_events_answer_by_graph():
    """``can``/``allowed_events`` отвечают по графу, а не «на глаз»."""
    fsm = PipelineFSM(PipelineState.COMPLETED)

    assert fsm.can(PipelineEvent.START) is True
    assert fsm.can(PipelineEvent.FINISH) is False
    assert fsm.allowed_events() == (PipelineEvent.START,)

    fsm.handle(PipelineEvent.START)
    assert fsm.allowed_events() == (
        PipelineEvent.ADVANCE,
        PipelineEvent.FINISH,
        PipelineEvent.STOP,
        PipelineEvent.FAIL,
    )


def test_reset_returns_to_idle_and_machine_is_usable_again():
    """``reset`` отдаёт ``IDLE``, после чего прогон можно начать заново."""
    fsm = PipelineFSM(PipelineState.FAILED)

    assert fsm.reset() is PipelineState.IDLE
    assert fsm.state is PipelineState.IDLE
    assert fsm.can(PipelineEvent.START) is True
    assert fsm.handle(PipelineEvent.START) is PipelineState.RUNNING


def test_full_successful_run_walks_to_completed():
    """Полный успешный прогон: старт, шаги по одному, финиш на последнем."""
    fsm = PipelineFSM()

    assert fsm.handle(PipelineEvent.START) is PipelineState.RUNNING
    assert fsm.handle(PipelineEvent.ADVANCE) is PipelineState.RUNNING
    assert fsm.handle(PipelineEvent.FINISH) is PipelineState.COMPLETED
    assert fsm.reset() is PipelineState.IDLE
