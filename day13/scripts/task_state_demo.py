"""Демонстрация дня 13: состояние задачи переживает перезапуск процесса.

Запуск из папки дня (обязательно: пути к БД и .env считаются от ``backend/``):

    python scripts/task_state_demo.py --reset          # удалить демо-БД и завести отчёт
    python scripts/task_state_demo.py --phase 2        # одна фаза в отдельном процессе
    python scripts/task_state_demo.py --all            # все фазы, каждая — новый процесс
    python scripts/task_state_demo.py --all --no-api   # то же офлайн, без сети

Зачем фазы в отдельных процессах.

    Главное утверждение дня — состояние задачи живёт в SQLite, а не в памяти
    процесса: после паузы и перезапуска агент продолжает с того же этапа и шага
    без повторных объяснений. Поэтому ``--all`` запускает каждую фазу
    ``subprocess``-ом: новый процесс не наследует ни объектов ``Agent``, ни
    состояния задачи, и всё, что он видит, он читает из файла БД.

Каждая фаза дописывает в ``docs/reports/task_state_demo.md`` раздел ``## Фаза N``: таблицу
переходов «из → в, причина», ответ агента (обрезанный), блок состояния из
системного промпта запроса и строку-доказательство с pid процесса.

Офлайн-режим (``--no-api``) подменяет клиент DeepSeek заглушкой
(``comparison_stub.StubClient``): прогон проверяет сам скрипт и работает без
ключа API; в шапке отчёта режим помечается явно.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Скрипт лежит в day13/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.core import config
from backend.agents.agent_manager import AgentManager
from backend.storage.database import AgentRecord, init_db, make_engine, make_session_factory
from backend.domain.task_fsm import TaskStage, TaskStep
from comparison_stub import StubClient
from task_demo_report import append, proof, reply_block, state_line, transitions_table

DEMO_DB = DAY_ROOT / "task_state_demo.db"
REPORT = DAY_ROOT / "docs" / "reports" / "task_state_demo.md"

AGENT_ID = "demo13"
TASK_ID = "tz-portal"
SESSION_ID = "demo13a"

PHASES = 5


# ---------- инфраструктура прогона ----------
def prepare(offline: bool, reset: bool = False):
    """Демо-БД, менеджер и живой агент (строка agents — как в tests/support)."""
    if reset and DEMO_DB.exists():
        DEMO_DB.unlink()
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
                agent_id=AGENT_ID, name="Демо-агент дня 13",
                model=config.MODEL_CHAT, temperature=0.0, system_prompt="",
                max_tokens=512, current_session_id=SESSION_ID,
                current_task_id=TASK_ID,
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()

    # Тот же путь, которым приложение восстанавливает агентов при старте.
    manager.restore_from_db()
    agent = manager.require_agent(AGENT_ID)
    if offline:
        agent._make_client = lambda: StubClient()  # noqa: SLF001
    return manager, agent


def history(manager) -> list:
    """Журнал переходов задачи (пустой список — задачи ещё нет)."""
    if manager.get_task_state(TASK_ID) is None:
        return []
    return manager.get_task_history(TASK_ID)


def show(manager, prefix: str) -> str:
    """Строка-доказательство для текущего процесса."""
    return proof(manager, TASK_ID, DEMO_DB.name, prefix, os.getpid())


# ---------- фазы ----------
def phase_1(manager, agent) -> list:
    """planning: создание задачи, продвижение по реплике и пауза."""
    lines = [f"## Фаза 1 — постановка задачи и пауза (pid {os.getpid()})", ""]
    created = manager.create_task(AGENT_ID, TASK_ID, TaskStage.PLANNING.value)
    lines += [
        f"Задача `{TASK_ID}` заведена: **{created['stage']}/{created['current_step']}**, "
        f"ожидаемое действие — {created['expected_action']}.",
        "",
    ]

    plain = agent.generate("Собери требования к задаче")
    lines += reply_block("Шаг 1 — обычная реплика (намерения нет)", "Собери требования к задаче", plain)

    advanced = agent.generate("подтверждаю")
    lines += reply_block("Шаг 2 — реплика «подтверждаю» двигает шаг", "подтверждаю", advanced)

    manager.advance_task_step(TASK_ID)
    lines += [
        "Прямой вызов `advance_task_step` (кнопка «Следующий шаг»): "
        f"**{state_line(manager, TASK_ID)}**.",
        "",
    ]

    paused = agent.generate("поставь задачу на паузу")
    lines += reply_block("Шаг 3 — реплика «поставь задачу на паузу»", "поставь задачу на паузу", paused)

    state = manager.get_task_state(TASK_ID)
    lines += [
        "Итог фазы (состояние ПЕРЕД перезапуском процесса): этап "
        f"**{state['stage']}**, шаг **{state['current_step']}** сохранён для "
        "продолжения.",
        "",
        show(manager, "После фазы 1"),
        "",
    ]
    return lines


def phase_2(manager, agent) -> list:
    """Продолжение после паузы в новом процессе."""
    paused = manager.get_task_state(TASK_ID)
    lines = [
        f"## Фаза 2 — продолжение после перезапуска (pid {os.getpid()})",
        "",
        f"Состояние ДО любой реплики в этом процессе: **{paused['stage']}/"
        f"{paused['current_step']}**, `paused_from_stage` = "
        f"`{paused['paused_from_stage']}`.",
        "",
        show(manager, "Старт фазы 2"),
        "",
    ]
    assert paused["stage"] == TaskStage.PAUSED.value, paused
    assert paused["current_step"] == TaskStep.CREATE_PLAN.value, paused

    resumed = agent.generate("продолжи")
    lines += reply_block("Шаг 1 — реплика «продолжи»", "продолжи", resumed)
    assert resumed["task_state"]["stage"] == TaskStage.PLANNING.value, resumed

    manager.advance_task_step(TASK_ID)
    lines += [
        f"Прямой вызов `advance_task_step`: **{state_line(manager, TASK_ID)}** — задача "
        "вернулась на сохранённый шаг планирования, затем пошла дальше.",
        "",
    ]
    return lines


def phase_3(manager, agent) -> list:
    """execution → validation по реплике."""
    lines = [f"## Фаза 3 — выполнение и выход на валидацию (pid {os.getpid()})", ""]
    lines += [show(manager, "Старт фазы 3"), ""]

    manager.advance_task_step(TASK_ID)
    lines += [
        f"`advance_task_step`: **{state_line(manager, TASK_ID)}** — локальная проверка.",
        "",
    ]
    done = agent.generate("готово")
    lines += reply_block("Шаг 1 — реплика «готово»", "готово", done)
    assert done["task_state"]["stage"] == TaskStage.VALIDATION.value, done
    return lines


def phase_4(manager, agent) -> list:
    """validation: откат на execution, возврат и завершение задачи."""
    lines = [f"## Фаза 4 — откат, возврат и завершение (pid {os.getpid()})", ""]
    lines += [show(manager, "Старт фазы 4"), ""]

    manager.advance_task_step(TASK_ID)
    lines += [f"`advance_task_step`: **{state_line(manager, TASK_ID)}** — прогон тестов.", ""]

    rolled = manager.rollback_task(TASK_ID, TaskStage.EXECUTION.value)
    lines += [
        f"`rollback_task(execution)`: **{rolled['stage']}/{rolled['current_step']}** "
        "— шаг сброшен на первый шаг этапа выполнения.",
        "",
    ]
    assert rolled["current_step"] == TaskStep.IMPLEMENT.value, rolled

    for _ in range(4):
        manager.advance_task_step(TASK_ID)
    lines += [
        f"Четыре `advance_task_step` после отката: **{state_line(manager, TASK_ID)}** "
        "(implement → test_locally → review → run_tests → finalize).",
        "",
    ]

    finished = manager.transition_task(
        TASK_ID, TaskStage.DONE.value, reason="задача завершена"
    )
    lines += [
        f"`transition_task(done)`: **{finished['stage']}/{finished['current_step']}**, "
        f"задача активна: **{finished['is_active']}**.",
        "",
        "Задача завершена — в журнале это отдельная причина, а не серия шагов.",
        "",
    ]
    return lines


def phase_5(manager, agent) -> list:
    """Чтение итога в новом процессе: журнал, список активных задач, вывод."""
    entries = history(manager)
    state = manager.get_task_state(TASK_ID)
    active = [item["task_id"] for item in manager.list_active_tasks(AGENT_ID)]

    lines = [
        f"## Фаза 5 — итог после пяти запусков (pid {os.getpid()})",
        "",
        show(manager, "Старт фазы 5"),
        "",
        f"Текущее состояние: **{state['stage']}/{state['current_step']}**, "
        f"ожидаемое действие — {state['expected_action']}.",
        "",
        f"Задача в списке активных задач агента: **{TASK_ID in active}** "
        f"(список активных: {active or 'пуст'}).",
        "",
        "### Полный журнал переходов",
        "",
    ]
    lines += transitions_table(entries)
    lines += [
        "",
        f"Всего переходов в журнале: **{len(entries)}**.",
        "",
        "### Вывод",
        "",
        "Состояние задачи сохранено между пятью запусками процесса: фаза 1 "
        "оставила задачу на паузе в `paused/create_plan`, фаза 2 в новом "
        "процессе продолжила её с этого же шага, фазы 3–4 довели до `done`, а "
        "фаза 5 прочитала итог из `task_state_demo.db`. Ни один процесс не "
        "держал состояние в памяти: всё, что видно в журнале, — строки таблиц "
        "`task_states` и `task_transitions`.",
        "",
        "Воспроизведение:",
        "",
        "```bash",
        "cd day13",
        "python scripts/task_state_demo.py --all           # нужен DEEPSEEK_API_KEY в day13/.env",
        "python scripts/task_state_demo.py --all --no-api  # офлайн-заглушка, без сети",
        "```",
        "",
    ]
    return lines


PHASE_RUNNERS = {1: phase_1, 2: phase_2, 3: phase_3, 4: phase_4, 5: phase_5}


# ---------- CLI ----------
def write_header(offline: bool) -> None:
    """Шапка отчёта: команды прогона, путь к БД и режим."""
    mode = ("офлайн-заглушка (`--no-api`, без сети)" if offline
            else "реальные запросы к DeepSeek (`deepseek-chat`)")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    REPORT.write_text(
        "\n".join([
            "# Отчёт дня 13 — состояние задачи как FSM",
            "",
            f"Прогон: {now} · режим: {mode} · модель: **{config.MODEL_CHAT}**",
            "",
            f"Демо-база: `{DEMO_DB.name}` · агент `{AGENT_ID}` · задача `{TASK_ID}`.",
            "",
            "Каждая фаза — ОТДЕЛЬНЫЙ процесс (`subprocess`), поэтому отчёт "
            "проверяет главное утверждение дня: состояние задачи читается из "
            "SQLite, а не из памяти процесса.",
            "",
            "Запуск:",
            "",
            "```bash",
            "cd day13",
            "python scripts/task_state_demo.py --all           # с API-ключом",
            "python scripts/task_state_demo.py --all --no-api  # офлайн, без сети",
            "python scripts/task_state_demo.py --phase 2       # одна фаза",
            "python scripts/task_state_demo.py --reset         # очистить БД и отчёт",
            "```",
            "",
        ]) + "\n",
        encoding="utf-8",
    )


def run_all(offline: bool) -> int:
    """Прогоняет все фазы отдельными процессами (--reset + фазы 1..5)."""
    prepare(offline, reset=True)
    write_header(offline)
    for number in range(1, PHASES + 1):
        extra = ["--no-api"] if offline else []
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--phase", str(number), *extra],
            check=False,
        )
        if result.returncode != 0:
            print(f"фаза {number} завершилась с кодом {result.returncode}", file=sys.stderr)
            return result.returncode
    print(f"отчёт записан: {REPORT}")
    return 0


def main(argv: list) -> int:
    offline = "--no-api" in argv
    if "--reset" in argv:
        if DEMO_DB.exists():
            DEMO_DB.unlink()
        write_header(offline)
        print(f"демо-база и отчёт пересозданы: {REPORT}")
        return 0
    if "--all" in argv:
        if not offline and not config.resolve_api_key():
            print(
                "Нет ключа DEEPSEEK_API_KEY (day13/.env или переменная окружения). "
                "Запустите с --no-api для офлайн-прогона.",
                file=sys.stderr,
            )
            return 2
        return run_all(offline)
    if "--phase" in argv:
        number = int(argv[argv.index("--phase") + 1])
        if number not in PHASE_RUNNERS:
            print(f"фаза должна быть в 1..{PHASES}", file=sys.stderr)
            return 2
        manager, agent = prepare(offline)
        lines = PHASE_RUNNERS[number](manager, agent)
        append(REPORT, lines)
        print(f"фаза {number}: {state_line(manager, TASK_ID)} (pid {os.getpid()})")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
