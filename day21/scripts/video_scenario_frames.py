"""Кадры 0–9 автопроверки сценария видео дня 17 (``docs/usage.md`` §8).

Что это.
    По одной функции на кадр: проверки, которые сценарий обещает зрителю.
    Каждая после заголовка кадра сверяет договор из инструкции с фактическим
    поведением кода — по HTTP (``ApiClient``) и по реальному рендеру интерфейса
    (``video_scenario_ui``). Константы сценария (идентификаторы задач, реплика,
    вопрос про сдачу) живут здесь же: это данные кадров, а не инфраструктуры.

Почему не в точке входа.
    Кадры — самая объёмная часть прогона; вместе с точкой входа модуль выходил
    за лимит 400 строк (``AGENTS.md``). Инфраструктура прогона — в
    ``video_scenario.py`` (CLI и оркестрация), ``video_scenario_client.py``
    (HTTP-клиент и путь БД), ``video_scenario_checks.py`` (печать проверок) и
    ``video_scenario_server.py`` (бэкенд и его жизненный цикл), UI-кадры — в
    ``video_scenario_ui.py``.
"""
from __future__ import annotations

from typing import Any

from video_scenario_checks import VideoChecks
from video_scenario_client import ApiClient

# Задачи и реплики кадров: те же значения, что в §8 инструкции и в отчёте
# ``docs/reports/controlled_transitions_demo.md``.
TASK_ID = "tz-transitions"
PROPOSAL_TASK_ID = "tz-transitions-2"   # вторая задача: первая к кадру 8 уже done
PROPOSAL_PROMPT = "задача завершена, можно сдавать?"
TASK_REPLICA = "подтверждаю"            # реплика кадра 3 (её же набирают на стенде)


def move(checks: VideoChecks, label: str, response, stage: str,
         step: str = "") -> dict:
    """Проверяет шаг сценария: статус 200 и место задачи (этап и шаг)."""
    status, state = response
    place = (state.get("stage"), state.get("current_step"))
    ok = status == 200 and state.get("stage") == stage and (
        not step or state.get("current_step") == step
    )
    checks.check(label, ok, f"статус {status}: {place[0]}/{place[1]}")
    return state


def frame_0_rules(checks: VideoChecks) -> None:
    """Кадр 0: правила допуска как таблицы домена (бэкенд ещё не нужен)."""
    from backend.domain.task_fsm import TaskStage
    from backend.domain.task_state_machine import (
        ALLOWED_TRANSITIONS, GUARDS, _REFUSAL_TEXTS,
    )
    from backend.models.task_state import TaskState, TaskTransition

    checks.frame(0, "интро: граф допуска, guards, тексты отказа и таблицы БД")
    print("ALLOWED_TRANSITIONS (этап → куда разрешено):")
    for stage, targets in ALLOWED_TRANSITIONS.items():
        allowed = ", ".join(sorted(item.value for item in targets)) or "—"
        print(f"  {stage.value}: {allowed}")
    print("GUARDS (переходы, где решает согласование этапа):")
    for source, target in GUARDS:
        print(f"  {source.value} → {target.value}")
    print("_REFUSAL_TEXTS (причина отказа и что сделать):")
    for (source, target), (message, hint) in _REFUSAL_TEXTS.items():
        print(f"  {source.value} → {target.value}: {message} | {hint}")

    checks.check("кадр 0: из этапа done переходов нет",
                 ALLOWED_TRANSITIONS[TaskStage.DONE] == frozenset(),
                 "получено: "
                 f"{sorted(item.value for item in ALLOWED_TRANSITIONS[TaskStage.DONE])}")
    for source, target in ((TaskStage.PLANNING, TaskStage.EXECUTION),
                           (TaskStage.EXECUTION, TaskStage.VALIDATION),
                           (TaskStage.VALIDATION, TaskStage.DONE)):
        checks.check(f"кадр 0: переход {source.value} → {target.value} закрыт guard",
                     GUARDS.get((source, target)) is not None,
                     "в GUARDS нет пары с этим переходом")
    checks.check("кадр 0: текстов отказа ровно три", len(_REFUSAL_TEXTS) == 3,
                 f"получено: {sorted(f'{s.value}→{t.value}' for s, t in _REFUSAL_TEXTS)}")
    checks.check("кадр 0: таблицы состояния и журнала названы",
                 TaskState.__tablename__ == "task_states"
                 and TaskTransition.__tablename__ == "task_transitions",
                 f"{TaskState.__tablename__} / {TaskTransition.__tablename__}")


def frame_1(checks: VideoChecks, client: ApiClient, ui: Any) -> str:
    """Кадр 1: завести задачу через форму панели и сверить с правилами."""
    checks.frame(1, "завести задачу: planning, один доступный переход, "
                    "три причины отказа")
    status, agent = client.create_agent()
    checks.check("кадр 1: агент создан через POST /agents",
                 status == 201 and bool(agent.get("agent_id")),
                 f"статус {status}, agent_id {agent.get('agent_id')}")
    agent_id = agent["agent_id"]

    # UI-часть кадра 0 и кадр 1 идут после старта бэкенда: без него интерфейс
    # рисует «бэкенд недоступен», а переключатель разделов не появляется.
    ui.frame_0_sections(None, checks.check)
    ui.frame_1_create_task(agent_id, TASK_ID, checks.check)

    status, state = client.state(TASK_ID)
    checks.check("кадр 1: API видит ту же задачу на planning",
                 status == 200 and state.get("stage") == "planning",
                 f"статус {status}: {state.get('stage')}")
    checks.check("кадр 1: шаг задачи — gather_requirements",
                 state.get("current_step") == "gather_requirements",
                 f"получено: {state.get('current_step')}")
    checks.check("кадр 1: доступен только этап paused",
                 state.get("allowed_next") == ["paused"],
                 f"получено: {state.get('allowed_next')}")
    blocked = state.get("blocked") or []
    checks.check("кадр 1: недоступны execution, validation и done",
                 [item.get("stage") for item in blocked]
                 == ["execution", "validation", "done"],
                 f"получено: {[item.get('stage') for item in blocked]}")
    reasons = [item.get("reason") for item in blocked]
    checks.check("кадр 1: причины отказа совпадают со сценарием",
                 reasons == [
                     "Нельзя перейти в execution: план не утверждён",
                     "Нельзя перейти из planning в validation: пропущен этап execution",
                     "Нельзя перейти из planning в done: пропущены этапы execution "
                     "и validation",
                 ], f"получено: {reasons}")
    return agent_id


def frame_2(checks: VideoChecks, client: ApiClient, agent_id: str, ui: Any) -> None:
    """Кадр 2: «Следующий шаг» упирается в guard и оставляет состояние прежним."""
    checks.frame(2, "«Следующий шаг» упирается в guard: состояние не меняется")
    ui.frame_2_step_refusal(agent_id, TASK_ID, checks.check)

    status, journal = client.history(TASK_ID)
    entries = journal.get("entries") or []
    last = entries[-1] if entries else {}
    checks.check("кадр 2: последняя запись журнала — отклонённая попытка",
                 status == 200 and last.get("accepted") is False,
                 f"статус {status}: {last}")
    checks.check("кадр 2: попытка назвала цель execution и причину отказа",
                 last.get("to_stage") == "execution"
                 and last.get("reason")
                 == "Нельзя перейти в execution: план не утверждён",
                 f"получено: {last.get('to_stage')} / {last.get('reason')}")
    status, state = client.state(TASK_ID)
    checks.check("кадр 2: состояние задачи прежнее",
                 (state.get("stage"), state.get("current_step"))
                 == ("planning", "create_plan"),
                 f"получено: {state.get('stage')}/{state.get('current_step')}")


def frame_3(checks: VideoChecks, client: ApiClient, agent_id: str, ui: Any) -> None:
    """Кадр 3: реплика «подтверждаю» не подставляет флаг согласования."""
    checks.frame(3, "реплика не подставляет флаг: согласие — это данные")
    ui.frame_3_chat_replica(agent_id, checks.check)

    status, state = client.state(TASK_ID)
    checks.check("кадр 3: реплика не изменила состояние задачи",
                 (state.get("stage"), state.get("current_step"))
                 == ("planning", "create_plan"),
                 f"получено: {state.get('stage')}/{state.get('current_step')}")


def frame_4(checks: VideoChecks, client: ApiClient, agent_id: str, ui: Any) -> None:
    """Кадр 4: флаг «План утверждён» открывает ровно переход в execution."""
    checks.frame(4, "флаг открывает ровно тот же переход, что просил сценарий")
    ui.frame_4_flags_open_transition(agent_id, TASK_ID, checks.check)

    status, state = client.state(TASK_ID)
    checks.check("кадр 4: флаг сохранён в строке задачи",
                 (state.get("context") or {}).get("plan_approved") is True,
                 f"получено: {state.get('context')}")
    checks.check("кадр 4: задача в execution на шаге test_locally",
                 (state.get("stage"), state.get("current_step"))
                 == ("execution", "test_locally"),
                 f"получено: {state.get('stage')}/{state.get('current_step')}")


def frame_5(checks: VideoChecks, client: ApiClient, agent_id: str,
            backend: Any, ui: Any) -> None:
    """Кадр 5: пауза переживает перезапуск бэкенда (два разных процесса)."""
    checks.frame(5, "пауза переживает перезапуск бэкенда")
    ui.frame_5_pause(agent_id, TASK_ID, checks.check)

    first_pid = backend.pid
    print(f"  процесс 1 (pid {first_pid}) остановлен", flush=True)
    backend.stop()
    checks.check("кадр 5: процесс 1 завершён",
                 backend.process.poll() is not None,
                 f"код возврата {backend.process.returncode}")

    second_pid = backend.restart(client)
    print(f"  процесс 2 (pid {second_pid}) поднят на той же БД {backend.db.name}",
          flush=True)
    checks.check("кадр 5: перезапуск дал ДРУГОЙ процесс на той же БД",
                 second_pid != first_pid, f"pid {first_pid} → {second_pid}")
    status, state = client.state(TASK_ID)
    checks.check("кадр 5: состояние прочитано новым процессом из SQLite",
                 (state.get("stage"), state.get("paused_from_stage"),
                  state.get("current_step"))
                 == ("paused", "execution", "test_locally"),
                 f"получено: {state.get('stage')} / "
                 f"{state.get('paused_from_stage')} / {state.get('current_step')}")

    ui.frame_5_resume(agent_id, TASK_ID, checks.check)
    status, state = client.state(TASK_ID)
    checks.check("кадр 5: продолжение вернуло execution/test_locally",
                 (state.get("stage"), state.get("current_step"))
                 == ("execution", "test_locally"),
                 f"получено: {state.get('stage')}/{state.get('current_step')}")


def frame_6(checks: VideoChecks, client: ApiClient) -> None:
    """Кадр 6: откат с validation на execution сбрасывает согласования."""
    checks.frame(6, "откат сбрасывает согласования: старое согласие "
                    "недействительно")
    move(checks, "кадр 6: согласование реализации выставлено",
         client.set_flags(TASK_ID, implementation_complete=True),
         "execution", "test_locally")
    move(checks, "кадр 6: переход в validation выполнен",
         client.transition(TASK_ID, "validation"), "validation", "review")
    move(checks, "кадр 6: шаг вперёд дал run_tests",
         client.advance(TASK_ID), "validation", "run_tests")
    state = move(checks, "кадр 6: откат вернул задачу в execution",
                 client.transition(TASK_ID, "execution"), "execution", "implement")

    context = state.get("context") or {}
    checks.check("кадр 6: согласование реализации сброшено",
                 "implementation_complete" not in context, f"получено: {context}")
    checks.check("кадр 6: согласование валидации сброшено",
                 "validation_passed" not in context, f"получено: {context}")
    checks.check("кадр 6: утверждение плана сохранено",
                 context.get("plan_approved") is True, f"получено: {context}")
    blocked = {item.get("stage"): item.get("reason")
               for item in state.get("blocked") or []}
    checks.check("кадр 6: кнопка validation снова погашена с причиной",
                 blocked.get("validation")
                 == "Нельзя перейти в validation: реализация не завершена",
                 f"получено: {blocked.get('validation')}")


def frame_7(checks: VideoChecks, client: ApiClient, agent_id: str, ui: Any) -> None:
    """Кадр 7: done терминален — переходов из него нет вовсе."""
    checks.frame(7, "done терминален: погашены все кнопки и отклонена пауза")
    move(checks, "кадр 7: согласование реализации выставлено заново",
         client.set_flags(TASK_ID, implementation_complete=True),
         "execution", "implement")
    move(checks, "кадр 7: задача вернулась в validation",
         client.transition(TASK_ID, "validation"), "validation", "review")
    move(checks, "кадр 7: согласование валидации выставлено",
         client.set_flags(TASK_ID, validation_passed=True), "validation", "review")
    state = move(checks, "кадр 7: задача завершена",
                 client.transition(TASK_ID, "done"), "done", "finalize")

    checks.check("кадр 7: задача больше не активна", state.get("is_active") is False,
                 f"получено: {state.get('is_active')}")
    checks.check("кадр 7: допустимых следующих этапов нет",
                 state.get("allowed_next") == [],
                 f"получено: {state.get('allowed_next')}")
    reasons = {item.get("reason") for item in state.get("blocked") or []}
    checks.check("кадр 7: все четыре перехода отклонены как терминальные",
                 reasons == {"Нельзя перейти из done: этап done терминальный"},
                 f"получено: {sorted(reasons)}")
    status, body = client.transition(TASK_ID, "paused")
    checks.check("кадр 7: попытка паузы из done — 400 с причиной",
                 status == 400 and str(body.get("detail", "")).startswith(
                     "Нельзя перейти из done: этап done терминальный"),
                 f"статус {status}: {body.get('detail')}")

    ui.frame_7_done_terminal(agent_id, TASK_ID, checks.check)


def frame_8(checks: VideoChecks, client: ApiClient, agent_id: str) -> None:
    """Кадр 8: предложение модели перейти в done не выполняется."""
    checks.frame(8, "предложение модели не выполняется: ответ заменён отказом")
    status, state = client.create_task(agent_id, PROPOSAL_TASK_ID)
    checks.check("кадр 8: заведена вторая задача — первая уже терминальна",
                 status == 201 and state.get("stage") == "planning",
                 f"статус {status}: {state.get('stage')}")
    move(checks, "кадр 8: второй шаг планирования",
         client.advance(PROPOSAL_TASK_ID), "planning", "define_scope")
    move(checks, "кадр 8: план второй задачи описан",
         client.advance(PROPOSAL_TASK_ID), "planning", "create_plan")
    move(checks, "кадр 8: план второй задачи утверждён",
         client.set_flags(PROPOSAL_TASK_ID, plan_approved=True),
         "planning", "create_plan")
    move(checks, "кадр 8: вторая задача в execution",
         client.transition(PROPOSAL_TASK_ID, "execution"), "execution", "implement")
    move(checks, "кадр 8: реализация второй задачи проверена локально",
         client.advance(PROPOSAL_TASK_ID), "execution", "test_locally")
    move(checks, "кадр 8: реализация второй задачи согласована",
         client.set_flags(PROPOSAL_TASK_ID, implementation_complete=True),
         "execution", "test_locally")
    move(checks, "кадр 8: вторая задача на валидации",
         client.transition(PROPOSAL_TASK_ID, "validation"), "validation", "review")

    status, record = client.generate(agent_id, PROPOSAL_PROMPT)
    proposal = record.get("task_proposal") or {}
    checks.check("кадр 8: предложение модели распознано как переход в done",
                 status == 200 and proposal.get("proposed") == "done",
                 f"статус {status}: {proposal}")
    checks.check("кадр 8: причина отказа названа в отчёте генерации",
                 proposal.get("reason")
                 == "Нельзя перейти в done: валидация не пройдена",
                 f"получено: {proposal.get('reason')}")
    response = record.get("response") or ""
    checks.check("кадр 8: ответ заменён отказом с подсказкой",
                 response.startswith(
                     "🚧 Ответ предлагает переход в done, но это недопустимо. "
                     "Нельзя перейти в done: валидация не пройдена "
                     "Отметьте флаг «✅ Валидация пройдена» в панели задачи."),
                 f"ответ: {response}")
    status, state = client.state(PROPOSAL_TASK_ID)
    checks.check("кадр 8: состояние задачи не изменилось",
                 (state.get("stage"), state.get("current_step"))
                 == ("validation", "review"),
                 f"получено: {state.get('stage')}/{state.get('current_step')}")


def frame_9(checks: VideoChecks, client: ApiClient, agent_id: str, ui: Any) -> None:
    """Кадр 9: журнал задачи, отказы и отчёт прогона."""
    checks.frame(9, "журнал задачи: состоявшиеся переходы и отклонённые попытки")
    status, journal = client.history(TASK_ID)
    entries = journal.get("entries") or []
    rejected = [item for item in entries if item.get("accepted") is False]
    reasons = [item.get("reason") for item in rejected]
    checks.check("кадр 9: в журнале первой задачи есть отклонённые попытки",
                 len(rejected) >= 2,
                 f"записей {len(entries)}, отклонённых {len(rejected)}")
    for label, reason in (
        ("кадр 9: отказ «план не утверждён» попал в журнал",
         "Нельзя перейти в execution: план не утверждён"),
        ("кадр 9: отказ «этап done терминальный» попал в журнал",
         "Нельзя перейти из done: этап done терминальный"),
    ):
        checks.check(label, reason in reasons,
                     f"найдено среди {len(rejected)} отказов" if reason in reasons
                     else f"получено: {reasons}")

    status, second = client.history(PROPOSAL_TASK_ID)
    moves = [(item.get("from_stage"), item.get("to_stage"))
             for item in second.get("entries") or [] if item.get("accepted")]
    checks.check("кадр 9: во второй задаче состоялись planning → execution "
                 "и execution → validation",
                 ("planning", "execution") in moves
                 and ("execution", "validation") in moves, f"получено: {moves}")
    for task_id, rows in ((TASK_ID, entries),
                          (PROPOSAL_TASK_ID, second.get("entries") or [])):
        accepted = sum(1 for item in rows if item.get("accepted"))
        print(f"  задача {task_id}: всего записей {len(rows)}, состоявшихся "
              f"{accepted}, отклонённых {len(rows) - accepted}", flush=True)

    # Панель показывает активную задачу агента: возвращаем её на первую, иначе
    # вкладки отказов рисовались бы по второй задаче, где отказов не было.
    status, _ = client.set_active_task(agent_id, TASK_ID)
    checks.check("кадр 9: панель переключена на задачу прогона", status == 200,
                 f"статус {status}")
    ui.frame_9_journal_tabs(agent_id, TASK_ID, checks.check)
    print("  отчёт docs/reports/controlled_transitions_demo.md этим прогоном "
          "не перегенерируется: его числа даёт uv run python "
          "scripts/controlled_transitions_demo.py --all", flush=True)
