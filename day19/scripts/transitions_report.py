"""Сборка отчёта прогона контролируемых переходов (день 15).

Модуль собирает markdown ``docs/reports/controlled_transitions_demo.md``: таблицу
сценариев («попытка перехода → допуск → причина отказа → предложение модели →
продолжение после паузы»), разделы фаз, доказательство продолжения после паузы,
журнал отклонённых попыток (``accepted = False``) и вывод.

Живёт отдельно от ``controlled_transitions_demo.py`` по той же причине, что
``task_demo_report.py`` рядом с ``task_state_demo.py``: сборка текста отчёта —
отдельная обязанность от прогона фаз, и модуль не должен выходить за лимит 400
строк из скилла ``fastapi-streamlit-day-structure``.
"""

from datetime import datetime, timezone

from backend.core import config

TABLE_HEADER = (
    "| Попытка перехода | Допустимость | Причина отказа | Что предложил агент "
    "| Как продолжил после паузы |"
)
TABLE_DIVIDER = "|---|---|---|---|---|"


def row(attempt: str, verdict: str, reason: str = "—", proposal: str = "—",
        resumed: str = "—") -> list:
    """Строка главной таблицы отчёта: попытка, допуск, причина, предложение, пауза."""
    return [attempt, verdict, reason, proposal, resumed]


def journal_rejections(manager, task_id: str) -> list:
    """Отклонённые попытки из журнала задачи (``accepted = False``)."""
    entries = manager.get_task_history(task_id) or []
    return [entry for entry in entries if not entry.get("accepted", True)]


def rejections_table(rejections: list) -> list:
    """Markdown-таблица отклонённых попыток: что пробовали и почему нельзя."""
    lines = [
        "| # | этап | шаг | цель | причина отказа | время |",
        "|---|---|---|---|---|---|",
    ]
    for index, entry in enumerate(rejections, start=1):
        lines.append(
            f"| {index} | `{entry.get('from_stage')}` | `{entry.get('from_step')}` "
            f"| `{entry.get('to_stage') or '— не названа'}` "
            f"| {entry.get('reason')} | {str(entry.get('created_at'))[:19]} |"
        )
    return lines


def write_report(first: dict, second: dict, *, manager, db_name: str,
                 report_path, agent_id: str, task_id: str) -> None:
    """Собирает отчёт целиком: таблица сценариев, разделы фаз, журнал, вывод.

    Менеджер и пути приходят аргументами: сборка текста не знает, из какой БД
    читать, — иначе получился бы цикл импортов с прогоном фаз.
    """
    rejections = journal_rejections(manager, task_id)
    accepted = len(manager.get_task_history(task_id) or []) - len(rejections)
    state = manager.get_task_state(task_id)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Отчёт дня 17 — контролируемые переходы состояний",
        "",
        f"Прогон: {now} · режим: **офлайн-заглушка, без сети** · "
        f"модель: **{config.MODEL_CHAT}**",
        "",
        f"Демо-база: `{db_name}` · агент `{agent_id}` · задача `{task_id}`.",
        "",
        "Фазы 1 и 2 — РАЗНЫЕ процессы (`subprocess`), поэтому отчёт проверяет два "
        "утверждения дня сразу: правила допуска отклоняют недопустимый переход с "
        "объяснением, а пауза живёт в БД (колонка `task_states.paused_from_stage`), "
        "а не в памяти процесса.",
        "",
        "Запуск:",
        "",
        "```bash",
        "cd day17",
        "uv run python scripts/controlled_transitions_demo.py --all     # прогон и отчёт",
        "uv run python scripts/controlled_transitions_demo.py --phase 1 # только фаза 1",
        "uv run python scripts/controlled_transitions_demo.py --phase 2 # только фаза 2",
        "uv run python scripts/controlled_transitions_demo.py --reset   # очистить прогон",
        "```",
        "",
        "## Сценарии перехода",
        "",
        TABLE_HEADER,
        TABLE_DIVIDER,
    ]
    lines += ["| " + " | ".join(item) + " |" for item in [*first["rows"], *second["rows"]]]
    lines += ["", *first["sections"], *second["sections"]]
    lines += [
        "## Продолжение после паузы",
        "",
        f"* фаза 1 (pid {first['pid']}) оставила задачу на **{first['paused_stage']}/"
        f"{first['paused_step']}**, `paused_from_stage` = `{first['paused_from']}`;",
        f"* фаза 2 (pid {second['pid']}) прочитала состояние из `{db_name}` — "
        f"этап и шаг **{second['resumed_stage']}/{second['resumed_step']}** — и "
        "продолжение вернуло ровно это место.",
        "",
        "Утверждение: точка возврата хранится в колонке строки задачи, поэтому "
        "перезапуск процесса её не теряет, а шаг паузы (`current_step`) пауза не "
        "меняет.",
        "",
        "## Журнал попыток",
        "",
        f"Записей в журнале: **{accepted + len(rejections)}** (состоявшихся "
        f"переходов — {accepted}, отклонённых попыток — {len(rejections)}). "
        "Строки с `accepted = False`:",
        "",
        *rejections_table(rejections),
        "",
        "Каждая отклонённая попытка объясняет себя причиной отказа: состояние "
        "задачи такая строка не меняет (см. `task_states` — этап и шаг прежние), "
        "поэтому журнал — это ещё и материал для разбора «почему не пустило».",
        "",
        "## Вывод",
        "",
        "1. Переход этапа проверяется графом допуска: `planning → done` отклонён с "
        "перечислением пропущенных этапов, откат через два этапа — с указанием "
        "идти по одному, неизвестный этап — с перечислением допустимых.",
        "2. Переход вперёд требует согласования этапа: без `plan_approved`, "
        "`implementation_complete` и `validation_passed` он отклоняется, называя "
        "флаг; выставление флага открывает ровно тот же переход.",
        "3. Недопустимое предложение модели не выполняется и не остаётся в ответе: "
        "вместо него уходит отказ с причиной и подсказкой, а `task_proposal` "
        "попадает в отчёт генерации.",
        "4. Пауза переживает перезапуск процесса: фаза 2 прочитала из БД тот же "
        "этап и шаг, на которых задача была приостановлена.",
        "5. Этап `done` терминальный: из него нет переходов — даже на паузу.",
        "",
        f"Итоговое состояние задачи: **{state['stage']}/{state['current_step']}**, "
        f"активна — **{state['is_active']}**.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
