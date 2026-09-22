"""Граф допустимых переходов состояния задачи и guard-условия (день 15).

Что это.
    Единственный источник правды о том, КУДА задача имеет право перейти:
    явная таблица ``ALLOWED_TRANSITIONS`` (этап → допустимые этапы),
    guard-условия ``GUARDS`` на флаги контекста и тексты отказа с подсказками,
    которые видит пользователь.

    Граф:

        planning   -> execution (guard: plan_approved) | paused
        execution  -> validation (guard: implementation_complete) | planning | paused
        validation -> done (guard: validation_passed) | execution | paused
        done       -> никуда: этап терминальный
        paused     -> planning | execution | validation (guard: этап паузы)

    Классы этапов (``backend/domain/task_fsm.py``) отвечают только за события и
    шаги внутри этапа; правила допуска живут здесь, чтобы отказ «нельзя» был
    ровно один и с объяснением, а не разбросан по слоям.

Почему флаги, а не «догадки».
    Переход вперёд требует явного согласования этапа: ``plan_approved``,
    ``implementation_complete``, ``validation_passed`` выставляет пользователь
    (чекбоксы панели задачи, ``PATCH /tasks/{task_id}/context``). Попытка
    проскочить этап отклоняется с объяснением, а движение назад сбрасывает
    согласования, которые после отката недействительны (``cleared_flags``).

Как запустить.
    Модуль чистый: только ``enum``-члены ``task_fsm`` и строковые литералы —
    никаких БД, сети, LLM и UI. Побочных эффектов на импорте нет. Проверяется
    тестами:

        # из папки day16
        uv run pytest -q tests/unit/test_task_state_machine.py
"""

from __future__ import annotations

from typing import Callable, Iterable

from .task_fsm import STAGE_ORDER, TaskStage, stage_from_value

__all__ = [
    "ALLOWED_TRANSITIONS",
    "FLAG_IMPLEMENTATION_COMPLETE",
    "FLAG_PLAN_APPROVED",
    "FLAG_VALIDATION_PASSED",
    "GUARDS",
    "STAGE_DISPLAY_ORDER",
    "STAGE_FLAG",
    "TASK_FLAGS",
    "can_transition",
    "cleared_flags",
    "get_allowed_next_stages",
    "get_blocked_stages",
    "guard_context",
    "intent_refusal_notice",
    "is_transition_allowed",
    "transition_error_message",
    "transition_explanation",
    "transition_hint",
]

# Порядок отображения этапов в UI/API: прямой ход плюс пауза в конце (у паузы
# нет своего места в STAGE_ORDER — её место задаёт метка этапа возврата).
STAGE_DISPLAY_ORDER: tuple[TaskStage, ...] = STAGE_ORDER + (TaskStage.PAUSED,)

# Таблица допуска: этап → этапы, куда из него РАЗРЕШЕНО попасть. Отсутствие
# пары здесь — отказ, а не «переход по умолчанию». done терминален: из сданной
# задачи переходов нет вовсе; paused возвращает только в рабочие этапы.
ALLOWED_TRANSITIONS: dict[TaskStage, frozenset[TaskStage]] = {
    TaskStage.PLANNING: frozenset({TaskStage.EXECUTION, TaskStage.PAUSED}),
    TaskStage.EXECUTION: frozenset(
        {TaskStage.VALIDATION, TaskStage.PLANNING, TaskStage.PAUSED}
    ),
    TaskStage.VALIDATION: frozenset(
        {TaskStage.DONE, TaskStage.EXECUTION, TaskStage.PAUSED}
    ),
    TaskStage.DONE: frozenset(),
    TaskStage.PAUSED: frozenset(
        {TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION}
    ),
}

# Флаги контекста задачи — guard-условия переходов вперёд. Значения хранятся в
# task_states.context и приходят из API (bool), а не из текста реплики.
FLAG_PLAN_APPROVED = "plan_approved"
FLAG_IMPLEMENTATION_COMPLETE = "implementation_complete"
FLAG_VALIDATION_PASSED = "validation_passed"
TASK_FLAGS: tuple[str, ...] = (
    FLAG_PLAN_APPROVED,
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_VALIDATION_PASSED,
)

# «Этап → его флаг»: по этой таблице сбрасываются согласования при движении
# назад (см. ``cleared_flags``).
STAGE_FLAG: dict[TaskStage, str] = {
    TaskStage.PLANNING: FLAG_PLAN_APPROVED,
    TaskStage.EXECUTION: FLAG_IMPLEMENTATION_COMPLETE,
    TaskStage.VALIDATION: FLAG_VALIDATION_PASSED,
}

# Подсказка к отказу выхода из паузы: пользователь должен понимать, что пауза
# не «теряет» место задачи, а лишь откладывает её.
_PAUSED_REFUSAL_HINT = (
    "Продолжите задачу в этап, откуда её поставили на паузу "
    "(или в доступный следующий этап)."
)

# Тексты отказа для пар, где решение принимает guard, а не граф. Подсказка
# называет конкретный флаг: пользователю нужно действие, а не описание.
_REFUSAL_TEXTS: dict[tuple[TaskStage, TaskStage], tuple[str, str]] = {
    (TaskStage.PLANNING, TaskStage.EXECUTION): (
        "Нельзя перейти в execution: план не утверждён",
        "Утвердите план: отметьте флаг «📝 План утверждён» в панели задачи.",
    ),
    (TaskStage.EXECUTION, TaskStage.VALIDATION): (
        "Нельзя перейти в validation: реализация не завершена",
        "Отметьте флаг «⚙️ Реализация завершена» в панели задачи.",
    ),
    (TaskStage.VALIDATION, TaskStage.DONE): (
        "Нельзя перейти в done: валидация не пройдена",
        "Отметьте флаг «✅ Валидация пройдена» в панели задачи.",
    ),
}


def _stage(value: str | TaskStage) -> TaskStage:
    """Этап из строки (БД/API) или из члена Enum; неизвестный — ValueError."""
    return stage_from_value(value) if isinstance(value, str) else value


def _flag_guard(flag: str) -> Callable[[dict], bool]:
    """Guard «флаг выставлен именно в ``True``».

    Проверка именно ``is True``, а не «истинно»: строка ``"true"`` из JSON или
    ``1`` из ручной правки БД согласием не считаются — иначе согласование
    проходило бы мимо интерфейса.
    """
    return lambda context: context.get(flag) is True


def _resume_guard(target: TaskStage) -> Callable[[dict], bool]:
    """Guard выхода из паузы: свой этап или доступный следующий из этапа паузы.

    «Свой этап» — обычное продолжение (задача возвращается туда, где встала).
    Другой этап разрешён, только если он и так достижим из этапа паузы: тогда
    это явный запрос пользователя продолжить в следующий этап, а не прыжок
    через этап. Без сохранённого этапа паузы продолжать некуда — ``False``.
    """

    def guard(context: dict) -> bool:
        paused_from = context.get("paused_from_stage")
        if not paused_from:
            return False
        try:
            pause_stage = stage_from_value(paused_from)
        except ValueError:
            return False
        if target is pause_stage:
            return True
        # paused в списке не появится: target — один из рабочих этапов.
        return target in get_allowed_next_stages(pause_stage, context)

    return guard


# Guard-условия: у трёх прямых переходов и у трёх выходов из паузы. Пары,
# которых здесь нет, решает только ALLOWED_TRANSITIONS (откаты и пауза).
GUARDS: dict[tuple[TaskStage, TaskStage], Callable[[dict], bool]] = {
    (TaskStage.PLANNING, TaskStage.EXECUTION): _flag_guard(FLAG_PLAN_APPROVED),
    (TaskStage.EXECUTION, TaskStage.VALIDATION): _flag_guard(FLAG_IMPLEMENTATION_COMPLETE),
    (TaskStage.VALIDATION, TaskStage.DONE): _flag_guard(FLAG_VALIDATION_PASSED),
    **{
        (TaskStage.PAUSED, target): _resume_guard(target)
        for target in (TaskStage.PLANNING, TaskStage.EXECUTION, TaskStage.VALIDATION)
    },
}


def can_transition(from_stage: str | TaskStage, to_stage: str | TaskStage) -> bool:
    """Проверка ТОЛЬКО по графу ``ALLOWED_TRANSITIONS`` (без guard-условий).

    Неизвестный этап — явный ``ValueError``: «False по умолчанию» скрыло бы
    опечатку в этапе, а не отсутствие перехода.
    """
    return _stage(to_stage) in ALLOWED_TRANSITIONS[_stage(from_stage)]


def guard_context(state: dict) -> dict:
    """Контекст для guards из словаря состояния задачи.

    Кроме флагов (они в ``context`` строки) guard-условиям нужны этап, шаг и
    метка паузы — они лежат в самой строке, а не в ``context``. Возвращается
    копия: guards не имеют права менять состояние задачи.
    """
    context = dict(state.get("context") or {})
    context["stage"] = state.get("stage")
    context["current_step"] = state.get("current_step")
    context["paused_from_stage"] = state.get("paused_from_stage")
    return context


def is_transition_allowed(
    from_stage: str | TaskStage, to_stage: str | TaskStage, context: dict
) -> bool:
    """Полная проверка допуска: граф, затем guard-условие (если оно есть)."""
    if not can_transition(from_stage, to_stage):
        return False
    guard = GUARDS.get((_stage(from_stage), _stage(to_stage)))
    return True if guard is None else bool(guard(context))


def get_allowed_next_stages(
    current_stage: str | TaskStage, context: dict
) -> list[TaskStage]:
    """Этапы, доступные из текущего с учётом guards, в порядке отображения."""
    current = _stage(current_stage)
    return [
        stage
        for stage in STAGE_DISPLAY_ORDER
        if stage is not current and is_transition_allowed(current, stage, context)
    ]


def get_blocked_stages(
    current_stage: str | TaskStage, context: dict
) -> list[tuple[TaskStage, str]]:
    """Все недоступные этапы с короткой причиной отказа (для подсказок UI)."""
    current = _stage(current_stage)
    allowed = set(get_allowed_next_stages(current, context))
    return [
        (stage, transition_error_message(current, stage, context))
        for stage in STAGE_DISPLAY_ORDER
        if stage is not current and stage not in allowed
    ]


def _join_stages(values: list[str]) -> str:
    """Перечисление этапов по-русски: «execution и validation»."""
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + " и " + values[-1]


def _guard_refusal_or_ok(
    source: TaskStage, target: TaskStage, context: dict
) -> tuple[str, str]:
    """Разрешает пару графом и спрашивает guard: он и решает исход."""
    guard = GUARDS.get((source, target))
    if guard is None or guard(context):
        return ("", "")
    return _refusal(source, target, context)


def _refusal(
    source: TaskStage, target: TaskStage, context: dict
) -> tuple[str, str]:
    """Тексты отказа для пары, которую закрыл guard."""
    fixed = _REFUSAL_TEXTS.get((source, target))
    if fixed is not None:
        return fixed
    paused_from = context.get("paused_from_stage")
    if not paused_from:
        message = f"Нельзя перейти из paused в {target.value}: не сохранён этап паузы"
    else:
        message = (
            f"Нельзя перейти из paused в {target.value}: "
            f"пауза была на этапе {paused_from}"
        )
    return (message, _PAUSED_REFUSAL_HINT)


def transition_explanation(
    from_stage: str | TaskStage, to_stage: str | TaskStage, context: dict
) -> tuple[str, str]:
    """Причина отказа и что сделать: ``("", "")`` — переход разрешён.

    Порядок правил важен и читается сверху вниз: сначала «уже здесь» и
    «терминальный этап», затем запреты паузы, затем граф (пропуск этапа или
    откат не по одному этапу) и только потом guard-условия.
    """
    source = _stage(from_stage)
    target = _stage(to_stage)

    if source is target:
        return (
            f"Нельзя перейти из {source.value} в {target.value}: задача уже на этом этапе",
            "Выберите другой этап.",
        )
    if source is TaskStage.DONE:
        return (
            "Нельзя перейти из done: этап done терминальный",
            "Завершённая задача изменению не подлежит: заведите новую задачу.",
        )
    if source is TaskStage.PAUSED:
        if target not in ALLOWED_TRANSITIONS[TaskStage.PAUSED]:
            return (
                f"Нельзя перейти из paused в {target.value}: из паузы возвращаются "
                "только в planning, execution или validation",
                "Продолжите задачу в этап, откуда её поставили на паузу, и доведите "
                "до нужного этапа.",
            )
        return _guard_refusal_or_ok(source, target, context)

    if target in ALLOWED_TRANSITIONS[source]:
        return _guard_refusal_or_ok(source, target, context)

    source_index = STAGE_ORDER.index(source)
    target_index = STAGE_ORDER.index(target)
    if target_index > source_index:
        skipped = [stage.value for stage in STAGE_ORDER[source_index + 1:target_index]]
        word = "пропущен этап" if len(skipped) == 1 else "пропущены этапы"
        return (
            f"Нельзя перейти из {source.value} в {target.value}: "
            f"{word} {_join_stages(skipped)}",
            f"Сначала перейдите в {STAGE_ORDER[source_index + 1].value} и пройдите "
            "этапы по порядку.",
        )
    return (
        f"Нельзя перейти из {source.value} в {target.value}: откат идёт по одному "
        f"этапу (сначала {STAGE_ORDER[source_index - 1].value})",
        "Откатывайтесь по одному этапу (кнопка «Откат»).",
    )


def transition_error_message(
    from_stage: str | TaskStage, to_stage: str | TaskStage, context: dict
) -> str:
    """Короткая причина отказа: журнал, текст исключения, подсказка кнопки."""
    return transition_explanation(from_stage, to_stage, context)[0]


def transition_hint(
    from_stage: str | TaskStage, to_stage: str | TaskStage, context: dict
) -> str:
    """Что сделать, чтобы переход стал возможен (пусто — переход разрешён)."""
    return transition_explanation(from_stage, to_stage, context)[1]


def intent_refusal_notice(intent: str, reason: str, allowed_next: Iterable[str]) -> str:
    """Ответ агента, когда реплика-намерение не привела к переходу.

    Пользователь должен увидеть три вещи: что именно не сработало, почему и
    куда задача может перейти сейчас, — иначе «нажал, ничего не произошло»
    вынуждает угадывать состояние.
    """
    allowed = ", ".join(allowed_next) or "нет"
    return (
        f"⚠️ Переход по реплике «{intent}» не выполнен: {reason} "
        f"Доступные следующие этапы: {allowed}."
    )


def cleared_flags(
    from_stage: str | TaskStage, to_stage: str | TaskStage
) -> tuple[str, ...]:
    """Флаги, сбрасываемые при движении НАЗАД по прямому ходу.

    Возврат назад отменяет согласования этапа-цели и всех последующих этапов:
    после отката «план утверждён» или «валидация пройдена» уже не факт, и
    оставлять их выставленными — значит пропустить этап при следующем
    движении вперёд. Движение вперёд, пауза и переход «в себя» флагов не
    трогают.
    """
    try:
        source = _stage(from_stage)
        target = _stage(to_stage)
    except ValueError:
        return ()
    if source not in STAGE_ORDER or target not in STAGE_ORDER:
        return ()
    target_index = STAGE_ORDER.index(target)
    if target_index >= STAGE_ORDER.index(source):
        return ()
    return tuple(
        STAGE_FLAG[stage]
        for stage in STAGE_ORDER[target_index:]
        if stage in STAGE_FLAG
    )
