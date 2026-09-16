"""Отрисовка отчёта демонстрации состояния задачи (день 13).

Модуль собирает markdown-фрагменты для ``task_state_demo.md``: таблицу переходов,
раздел про один ход агента (реплика, ответ, блок состояния из системного промпта)
и строку-доказательство о том, какой процесс и откуда прочитал состояние.

Живёт отдельно от ``task_state_demo.py`` по той же причине, что
``comparison_report.py`` рядом с ``personalization_comparison.py`` в дне 12:
сборка текста отчёта — отдельная обязанность от прогона фаз (лимит 400 строк на
модуль из скилла ``fastapi-streamlit-day-structure``).
"""

# Сколько символов ответа агента попадает в отчёт (полный ответ в отчёте не нужен).
ANSWER_PREVIEW = 700


def state_line(manager, task_id: str) -> str:
    """Текущий этап и шаг задачи одной строкой (для логов и отчёта)."""
    state = manager.get_task_state(task_id)
    if state is None:
        return "состояния нет"
    return f"{state['stage']}/{state['current_step']}"


def proof(manager, task_id: str, db_name: str, prefix: str, pid: int) -> str:
    """Строка-доказательство: какой процесс и откуда прочитал состояние."""
    return (f"{prefix}: новый процесс (pid {pid}), состояние прочитано из "
            f"`{db_name}` — **{state_line(manager, task_id)}**")


def transitions_table(entries: list) -> list:
    """Markdown-таблица переходов «из → в, причина, время»."""
    lines = ["| # | из | в | причина | время |", "|---|---|---|---|---|"]
    for index, entry in enumerate(entries, start=1):
        source = (f"`{entry['from_stage']}/{entry['from_step']}`"
                  if entry.get("from_stage") else "— (создание)")
        target = f"`{entry['to_stage']}/{entry['to_step']}`"
        lines.append(
            f"| {index} | {source} | {target} | {entry['reason']} "
            f"| {str(entry.get('created_at'))[:19]} |"
        )
    return lines


def reply_block(step: str, prompt: str, record: dict) -> list:
    """Раздел отчёта про один ход агента: реплика, ответ и блок состояния.

    Блок состояния берётся из итогового системного промпта запроса: он собран
    последним блоком системного сообщения, поэтому в отчёт попадает его хвост —
    ровно тот текст, который увидела модель.
    """
    state = record.get("task_state") or {}
    return [
        f"### {step}",
        "",
        f"Реплика: `{prompt}`",
        "",
        "Ответ агента (обрезан):",
        "",
        "```text",
        (record.get("response") or "")[:ANSWER_PREVIEW],
        "```",
        "",
        f"Состояние задачи после реплики: **{state.get('stage')}/"
        f"{state.get('current_step')}**",
        "",
        "Блок состояния в системном промпте запроса:",
        "",
        "```text",
        (record.get("system_prompt") or "").split("\n\n")[-1],
        "```",
        "",
    ]


def append(report_path, chunks: list) -> None:
    """Дописывает раздел отчёта в файл."""
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(chunks) + "\n")
