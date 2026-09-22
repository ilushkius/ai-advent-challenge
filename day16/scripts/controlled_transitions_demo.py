"""Прогон контролируемых переходов и отчёт ``docs/reports/controlled_transitions_demo.md``.

Запуск из папки дня (обязательно: пути к БД и .env считаются от ``backend/``):

    uv run python scripts/controlled_transitions_demo.py --all     # прогон и отчёт
    uv run python scripts/controlled_transitions_demo.py --phase 1 # только фаза 1
    uv run python scripts/controlled_transitions_demo.py --phase 2 # только фаза 2
    uv run python scripts/controlled_transitions_demo.py --reset   # очистить прогон

Что показывает скрипт.

    Правила допуска в работе: ``planning → done`` отклоняется с перечислением
    пропущенных этапов, ``planning → execution`` — без флага «план утверждён»,
    выход из этапа на последнем шаге — без согласования этапа, неизвестный этап —
    с отказом. Каждая отклонённая попытка лежит в журнале ``task_transitions`` со
    ``accepted = False``, состояние задачи при отказе не меняется. Отдельно
    показаны отказ агента на предложение модели и уведомление о неприменённой
    реплике пользователя.

Почему две фазы.

    Фаза 1 доводит задачу до паузы, фаза 2 запускается ОТДЕЛЬНЫМ процессом,
    читает состояние из ``controlled_transitions_demo.db`` и продолжает задачу с
    того же этапа и шага: пауза живёт в колонке ``task_states.paused_from_stage``,
    а не в памяти процесса.

Режим.

    Прогон офлайн по замыслу: клиент DeepSeek подменяется заглушкой
    (``ProposalStubClient``) с фиксированной фразой — этого достаточно, чтобы
    показать отказ на предложение модели. Ключ API и сеть не нужны.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Скрипт лежит в day16/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.core import config
from backend.agents.agent_manager import AgentManager
from backend.domain.task_fsm import InvalidTransitionError, TaskStage, TaskStep
from backend.domain.task_state_machine import (
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_PLAN_APPROVED,
    FLAG_VALIDATION_PASSED,
)
from backend.storage.database import AgentRecord, init_db, make_engine, make_session_factory
from transitions_report import row, write_report

DEMO_DB = DAY_ROOT / "controlled_transitions_demo.db"
REPORT = DAY_ROOT / "docs" / "reports" / "controlled_transitions_demo.md"

AGENT_ID = "demo15"
TASK_ID = "tz-transitions"
SESSION_ID = "demo15a"

# Фраза заглушки: выглядит как предложение перехода в done.
PROPOSAL_REPLY = "Задача завершена, можно сдавать."

# Нейтральный ответ модели: им проверяется отдельно уведомление о неприменённой
# реплике, чтобы в ответе не оказалось сразу двух разных объяснений.
NEUTRAL_REPLY = "Принято, продолжаю по плану."

class ProposalStubClient:
    """Заглушка DeepSeek: отвечает фразой-предложением перехода.

    Не имитирует модель, а позволяет показать отказ агента без сети: ответ
    содержит фразу, которую ``detect_stage_proposal`` распознаёт как предложение
    перейти в другой этап.
    """

    def __init__(self, reply: str = PROPOSAL_REPLY) -> None:
        self.reply = reply
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        content = self.reply
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=64, completion_tokens=len(content) // 4,
                total_tokens=64 + len(content) // 4,
            ),
        )


# ---------- инфраструктура прогона ----------
def reset_outputs() -> None:
    """Чистый прогон: демо-БД и отчёт удаляются."""
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    if REPORT.exists():
        REPORT.unlink()


def prepare() -> tuple[AgentManager, object]:
    """Менеджер и живой агент на демо-БД (строка agents — как при старте бэкенда)."""
    engine = make_engine(f"sqlite:///{DEMO_DB.as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    manager = AgentManager(session_factory=factory)

    with factory() as session:
        existing = (
            session.query(AgentRecord)
            .filter(AgentRecord.agent_id == AGENT_ID)
            .first()
        )
        if existing is None:
            session.add(AgentRecord(
                agent_id=AGENT_ID, name="Демо-агент дня 16",
                model=config.MODEL_CHAT, temperature=0.0, system_prompt="",
                max_tokens=512, summary_enabled=False, keep_last_messages=6,
                summarize_every=10, strategy="sliding_window", window_size=6,
                current_session_id=SESSION_ID, current_task_id=TASK_ID,
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()

    manager.restore_from_db()
    agent = manager.require_agent(AGENT_ID)
    agent._make_client = lambda: ProposalStubClient()  # noqa: SLF001
    return manager, agent


def refused(call) -> str:
    """Выполняет попытку перехода и возвращает причину отказа (``""`` — прошла)."""
    try:
        call()
    except InvalidTransitionError as exc:
        return str(exc)
    return ""


def where(manager) -> str:
    """Этап и шаг задачи одной строкой."""
    state = manager.get_task_state(TASK_ID)
    return f"{state['stage']}/{state['current_step']}" if state else "состояния нет"


# ---------- фаза 1: правила допуска и пауза ----------
def phase_1(emit: bool = False) -> dict:
    """Отказы правил, флаг, открывающий переход, и пауза на валидации."""
    manager, agent = prepare()
    rows: list = []
    sections: list = [f"## Фаза 1 — правила допуска в работе (pid {os.getpid()})", ""]

    created = manager.create_task(AGENT_ID, TASK_ID, TaskStage.PLANNING.value)
    sections += [
        f"Задача `{TASK_ID}` заведена: **{created['stage']}/{created['current_step']}**. "
        f"Допустимые следующие этапы: "
        f"{', '.join(f'`{item}`' for item in created['allowed_next'])} — всё "
        "остальное отклоняется с причиной.",
        "",
    ]

    reason = refused(lambda: manager.transition_task(TASK_ID, TaskStage.DONE.value))
    rows.append(row("`planning → done`", "недопустим", f"«{reason}»"))

    reason = refused(
        lambda: manager.transition_task(TASK_ID, TaskStage.EXECUTION.value)
    )
    rows.append(row(
        "`planning → execution` без согласования плана", "недопустим", f"«{reason}»",
    ))

    # То же самое, но репликой: пользователь получает уведомление в ответе.
    # Ответ модели здесь нейтральный — иначе в одной реплике смешались бы два
    # разных объяснения (неприменённое намерение и предложение модели).
    agent._make_client = lambda: ProposalStubClient(reply=NEUTRAL_REPLY)  # noqa: SLF001
    for _ in range(2):
        manager.advance_task_step(TASK_ID)  # planning: define_scope → create_plan
    reply = agent.generate("подтверждаю")
    intent = reply.get("task_intent") or {}
    rows.append(row(
        "реплика «подтверждаю» на последнем шаге планирования",
        "недопустим", f"«{intent.get('reason')}»",
    ))
    sections += [
        "Ответ агента на реплику, которую правила не пустили (состояние задачи "
        "не изменилось):",
        "",
        "```text",
        (reply.get("response") or "").strip(),
        "```",
        "",
        f"Состояние после отклонённой реплики: **{where(manager)}**; "
        f"`task_intent` = `{json.dumps(intent, ensure_ascii=False)}`.",
        "",
    ]

    # Флаг открывает тот же переход: подтверждение этапа — действие пользователя.
    manager.set_task_flags(TASK_ID, {FLAG_PLAN_APPROVED: True})
    moved = manager.transition_task(TASK_ID, TaskStage.EXECUTION.value)
    rows.append(row("`planning → execution` после флага `plan_approved`", "допустим"))
    sections += [
        f"Флаг «план утверждён» выставлен — переход выполнен: "
        f"**{moved['stage']}/{moved['current_step']}**.",
        "",
    ]

    manager.advance_task_step(TASK_ID)  # execution: implement → test_locally
    reason = refused(
        lambda: manager.transition_task(TASK_ID, TaskStage.VALIDATION.value)
    )
    rows.append(row(
        "`execution → validation` без согласования реализации",
        "недопустим", f"«{reason}»",
    ))

    reason = refused(lambda: manager.transition_task(TASK_ID, "нет-такого"))
    rows.append(row(
        "`execution → нет-такого`", "недопустим", f"«{reason}»",
        resumed="HTTP-контракт отклоняет такой этап кодом 422 (проверка схемы)",
    ))

    manager.set_task_flags(TASK_ID, {FLAG_IMPLEMENTATION_COMPLETE: True})
    manager.transition_task(TASK_ID, TaskStage.VALIDATION.value)
    rows.append(row(
        "`execution → validation` после флага `implementation_complete`", "допустим",
    ))

    paused = manager.pause_task(TASK_ID)
    rows.append(row(
        "`validation → paused`", "допустим",
        resumed=(
            f"пауза с этапа `{paused['paused_from_stage']}` на шаге "
            f"`{paused['current_step']}` (сохранён в `current_step`)"
        ),
    ))
    sections += [
        f"Задача поставлена на паузу в процессе (pid {os.getpid()}): "
        f"**{paused['stage']}/{paused['current_step']}**, "
        f"`paused_from_stage` = `{paused['paused_from_stage']}`.",
        "",
    ]

    payload = {
        "rows": rows,
        "sections": sections,
        "pid": os.getpid(),
        "paused_stage": paused["stage"],
        "paused_step": paused["current_step"],
        "paused_from": paused["paused_from_stage"],
    }
    print(f"фаза 1: {where(manager)} (pid {os.getpid()})")
    if emit:
        print("PHASE_PAYLOAD " + json.dumps(payload, ensure_ascii=False))
    return payload


# ---------- фаза 2: продолжение в новом процессе ----------
def phase_2(emit: bool = False) -> dict:
    """Продолжение из паузы в новом процессе и отказ на предложение модели."""
    manager, agent = prepare()
    rows: list = []
    sections: list = [f"## Фаза 2 — продолжение в новом процессе (pid {os.getpid()})", ""]

    before = manager.get_task_state(TASK_ID)
    sections += [
        f"Состояние до любой реплики в этом процессе: **{before['stage']}/"
        f"{before['current_step']}**, `paused_from_stage` = "
        f"`{before['paused_from_stage']}` — прочитано из "
        f"`{DEMO_DB.name}`, а не из памяти предыдущего процесса.",
        "",
    ]

    resumed = manager.resume_task(TASK_ID)
    rows.append(row(
        f"`paused → {before['paused_from_stage']}` (продолжение)", "допустим",
        resumed=(
            f"новый процесс вернул тот же этап и шаг: "
            f"`{resumed['stage']}/{resumed['current_step']}`"
        ),
    ))

    # Предложение модели: заглушка отвечает фразой «задача завершена».
    record = agent.generate("как дела с задачей?")
    proposal = record.get("task_proposal") or {}
    rows.append(row(
        "предложение модели в ответе на этапе валидации", "недопустим",
        f"«{proposal.get('reason')}»",
        proposal=f"«{PROPOSAL_REPLY}» → `{proposal.get('proposed')}`",
    ))
    sections += [
        "Отказ на предложение модели (ответ заглушки «" + PROPOSAL_REPLY + "») — "
        "переход не выполнен, вместо предложения уходит объяснение:",
        "",
        "```text",
        (record.get("response") or "").strip(),
        "```",
        "",
        f"`task_proposal` = `{json.dumps(proposal, ensure_ascii=False)}`, "
        f"состояние по-прежнему **{where(manager)}**.",
        "",
    ]

    manager.set_task_flags(TASK_ID, {FLAG_VALIDATION_PASSED: True})
    finished = manager.transition_task(
        TASK_ID, TaskStage.DONE.value, reason="задача завершена"
    )
    rows.append(row(
        "`validation → done` после флага `validation_passed`", "допустим",
    ))
    reason = refused(
        lambda: manager.pause_task(TASK_ID)
    )
    rows.append(row(
        "`done → paused`", "недопустим", f"«{reason}»",
        resumed="этап `done` терминальный: переходов из него нет вовсе",
    ))
    sections += [
        f"Валидация согласована, задача завершена: **{finished['stage']}/"
        f"{finished['current_step']}**, активна — **{finished['is_active']}**. "
        f"Попытка приостановить завершённую задачу отклонена: «{reason}».",
        "",
    ]

    payload = {
        "rows": rows,
        "sections": sections,
        "pid": os.getpid(),
        "resumed_stage": resumed["stage"],
        "resumed_step": resumed["current_step"],
        "proposal": proposal,
    }
    print(f"фаза 2: {where(manager)} (pid {os.getpid()})")
    if emit:
        print("PHASE_PAYLOAD " + json.dumps(payload, ensure_ascii=False))
    return payload


PHASE_RUNNERS = {1: phase_1, 2: phase_2}


# ---------- CLI ----------
def run_child(number: int) -> dict:
    """Запускает фазу отдельным процессом и возвращает её отчёт (JSON)."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()),
         "--phase", str(number), "--emit"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"фаза {number} завершилась с кодом {result.returncode}:\n{result.stderr}"
        )
    marker = "PHASE_PAYLOAD "
    payloads = [
        line for line in result.stdout.splitlines() if line.startswith(marker)
    ]
    if not payloads:
        raise SystemExit(f"фаза {number} не вернула отчёт о прогоне")
    return json.loads(payloads[-1][len(marker):])


def main(argv: list) -> int:
    if "--reset" in argv:
        reset_outputs()
        print("демо-БД и отчёт удалены")
        return 0
    if "--phase" in argv:
        number = int(argv[argv.index("--phase") + 1])
        if number not in PHASE_RUNNERS:
            print(f"фаза должна быть в {sorted(PHASE_RUNNERS)}", file=sys.stderr)
            return 2
        PHASE_RUNNERS[number](emit="--emit" in argv)
        return 0
    if "--all" in argv:
        reset_outputs()
        first = run_child(1)
        second = run_child(2)
        manager, _ = prepare()  # читаем итог из БД — после обеих фаз
        write_report(
            first, second, manager=manager, db_name=DEMO_DB.name,
            report_path=REPORT, agent_id=AGENT_ID, task_id=TASK_ID,
        )
        print(f"отчёт записан: {REPORT}")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
