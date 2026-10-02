"""Сборка отчёта о прогоне сценариев мини-чата (день 25): markdown из готовых строк.

Модуль чистый: ни сети, ни базы — на вход уже посчитанные записи прогона, на выходе
markdown. Так отчёт можно пересобрать и проверить тестом без ключа API (как
``scripts/rag_eval_report.py`` дня 23).

Что измеряет отчёт по заданию:

* сохранилась ли цель диалога — доля слов первой непустой цели сценария, оставшихся
  в текущей цели (порог ``GOAL_SHARE_MIN``): обновление памяти задачи идёт полной
  заменой, поэтому «дрейф цели» видно сразу; сценарий считается сохранившим цель,
  если удержавших реплик не меньше ``GOAL_KEEP_MIN``: единичный шум извлечения —
  ещё не дрейф, а переписанная в большинстве реплик цель — уже он;
* пришли ли ответы с источниками — сколько ответов режима ``rag`` и сколько из них
  непустые;
* обновлялась ли память задачи — сколько сообщений осталось с прошлым состоянием.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence

from backend.domain import rag_quotes

#: Заголовок отчёта: файл собирается скриптом прогона сценариев.
REPORT_TITLE = "# Мини-чат: сценарии проверки цели и источников"

#: Доля слов базовой цели, оставшихся в текущей, ниже которой цель потеряна.
GOAL_SHARE_MIN = 0.5

#: Доля реплик с удержанной целью, ниже которой сценарий считается потерявшим цель.
GOAL_KEEP_MIN = 0.8

#: Длины обрезки: ответ и вопрос — в ячейку, цель — в ячейку памяти.
ANSWER_CELL = 100
QUESTION_CELL = 60
GOAL_CELL = 40

#: Слова короче трёх символов в сравнение целей не берём: предлоги и союзы.
GOAL_WORD_MIN = 3

#: Метки режимов ответа для колонки «Режим».
MODE_LABELS = {"rag": "rag", "dont_know": "не знаю", "error": "ошибка"}

__all__ = ["GOAL_KEEP_MIN", "GOAL_SHARE_MIN", "REPORT_TITLE", "goal_kept", "goal_lost",
           "goal_verdict", "goal_words", "keeps_goal", "memory_cell", "render_report",
           "summary_lines"]


def goal_words(text) -> set:
    """Множество слов цели длиной от ``GOAL_WORD_MIN`` (нормализация дня 24)."""
    normalized = rag_quotes.normalize(str(text or ""))
    return {word for word in re.findall(r"\w+", normalized)
            if len(word) >= GOAL_WORD_MIN}


def goal_lost(baseline, current) -> bool:
    """Потеряна ли цель: пустая текущая при непустой базовой или утрата слов цели.

    Считается доля слов базовой цели, оставшихся в текущей (покрытие). Извлечение
    возвращает пересказ и часто дописывает к цели уточнения из диалога — это не
    потеря цели; потеря — когда слов исходной цели в текущей памяти больше нет.
    """
    base = goal_words(baseline)
    current = goal_words(current)
    if not current:
        return bool(base)
    if not base:
        return False
    return len(base & current) / len(base) < GOAL_SHARE_MIN


def goal_kept(rows: Sequence[dict]) -> tuple:
    """Сколько реплик сценария удержали цель и сколько реплик всего."""
    return sum(1 for row in rows if not row.get("goal_lost")), len(rows)


def keeps_goal(rows: Sequence[dict]) -> bool:
    """Сохранил ли сценарий цель: удержавших реплик не меньше ``GOAL_KEEP_MIN``."""
    kept, total = goal_kept(rows)
    return bool(total) and kept / total >= GOAL_KEEP_MIN


def goal_verdict(rows: Sequence[dict]) -> str:
    """Вывод по цели сценария: состояние и доля удержавших цель реплик."""
    kept, total = goal_kept(rows)
    if not total:
        return "цель не измерена"
    state = "цель сохранена" if keeps_goal(rows) else "цель потеряна"
    return f"{state} ({kept}/{total} реплик)"


def render_report(result: dict, *, config: Dict) -> str:
    """Markdown-отчёт: шапка прогона, таблица на каждый сценарий, выводы и итог."""
    scenarios = list(result.get("scenarios") or [])
    lines = [REPORT_TITLE, ""]
    lines += _params(config, scenarios)
    lines += ["", "Воспроизведение:", "", "```",
              "uv run python scripts/run_mini_chat_scenarios.py", "```", ""]
    for number, scenario in enumerate(scenarios, 1):
        lines += scenario_section(number, scenario)
        lines.append("")
    lines += _totals(scenarios)
    return "\n".join(lines) + "\n"


def scenario_section(number: int, scenario: dict) -> List[str]:
    """Раздел одного сценария: цель, таблица сообщений и вывод одной строкой."""
    rows = list(scenario.get("rows") or [])
    lines = [f"## Сценарий {number}: {scenario.get('title') or '—'}", "",
             f"Цель сценария: {scenario.get('goal') or '—'}", "",
             "| № | Вопрос | Ответ (100) | Источники | Режим | Память задачи после "
             "| Потеря цели |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(_row(row))
    lines += ["", f"**Вывод по сценарию {number}:** {verdict(rows)}"]
    return lines


def verdict(rows: Sequence[dict]) -> str:
    """Строка вывода по сценарию: источники, режим, цель, необновлённая память."""
    total = len(rows)
    sourced = sum(1 for row in rows if (row.get("sources") or 0) > 0)
    rag_rows = sum(1 for row in rows if row.get("mode") == "rag")
    stale = sum(1 for row in rows if row.get("memory_updated") is False)
    goal_state = goal_verdict(rows)
    return (f"ответов с источниками {sourced}/{total}; режим `rag` у {rag_rows}/{total}; "
            f"{goal_state}; сообщений с необновлённой памятью {stale}.")


def summary_lines(result: dict) -> List[str]:
    """Краткая сводка для консоли: одна строка на сценарий."""
    lines = []
    for scenario in result.get("scenarios") or []:
        rows = list(scenario.get("rows") or [])
        sourced = sum(1 for row in rows if (row.get("sources") or 0) > 0)
        lines.append(f"{scenario.get('id')}: сообщений {len(rows)}, "
                     f"с источниками {sourced}, {goal_verdict(rows)}")
    return lines


def _row(row: dict) -> str:
    """Строка таблицы сообщения: вопрос, ответ, источники, режим, память, цель."""
    mode = MODE_LABELS.get(str(row.get("mode") or ""), str(row.get("mode") or "—"))
    cells = [
        str(row.get("number") or "—"),
        _short(row.get("question"), QUESTION_CELL),
        _short(row.get("answer"), ANSWER_CELL),
        str(row.get("sources") or 0),
        mode,
        memory_cell(row.get("memory")),
        _yes(row.get("goal_lost")),
    ]
    return "| " + " | ".join(cells) + " |"


def memory_cell(memory) -> str:
    """Ячейка памяти задачи: цель (обрезанная) и размеры трёх списков."""
    if not isinstance(memory, dict):
        return "—"
    goal = _short(memory.get("goal"), GOAL_CELL) or "—"
    counts = []
    for key in ("terms", "constraints", "clarifications"):
        value = memory.get(key) or []
        counts.append(f"{key}={len(value) if isinstance(value, list) else 0}")
    return f"goal={goal}; " + "; ".join(counts)


def _params(config: Dict, scenarios: Sequence[dict]) -> List[str]:
    """Шапка прогона: дата, модель, отбор, объём и время."""
    messages = sum(len(scenario.get("rows") or []) for scenario in scenarios)
    return [
        "| Параметр | Значение |",
        "|---|---|",
        f"| Дата | {config.get('date') or '—'} |",
        f"| Модель | {_cell(config.get('model') or '—')} |",
        f"| top_k | {config.get('top_k') or '—'} |",
        f"| Порог релевантности | {config.get('threshold') or '—'} |",
        f"| Сценариев | {len(scenarios)} |",
        f"| Сообщений | {messages} |",
        f"| Время прогона | {config.get('seconds', 0.0):.1f} с |",
    ]


def _totals(scenarios: Sequence[dict]) -> List[str]:
    """Раздел «Итог»: сводка по всем сценариям прогона."""
    rows = [row for scenario in scenarios for row in (scenario.get("rows") or [])]
    total = len(rows)
    sourced = sum(1 for row in rows if (row.get("sources") or 0) > 0)
    rag_rows = sum(1 for row in rows if row.get("mode") == "rag")
    stale = sum(1 for row in rows if row.get("memory_updated") is False)
    kept = sum(1 for scenario in scenarios
               if keeps_goal(scenario.get("rows") or []))
    kept_rows = sum(goal_kept(scenario.get("rows") or [])[0] for scenario in scenarios)
    share = f" ({round(100 * sourced / total)} %)" if total else ""
    return [
        "## Итог", "",
        f"* Сценариев {len(scenarios)}, сообщений {total}: ответов с источниками "
        f"{sourced}/{total}{share}, режим `rag` у {rag_rows}/{total}.",
        f"* Цель сохранена в {kept} из {len(scenarios)} сценариев "
        f"({kept_rows}/{total} реплик удержали цель).",
        f"* Память задачи не обновлена у {stale} сообщений.",
    ]


def _short(text, limit: int) -> str:
    """Одна строка без лишних пробелов, обрезанная до ``limit`` с многоточием."""
    value = " ".join(str(text or "").split())
    if len(value) > limit:
        value = value[:limit].rstrip() + "…"
    return _cell(value)


def _cell(text) -> str:
    """Экранирование вертикальной черты: иначе ячейка ломает таблицу markdown."""
    return str(text or "").replace("|", "\\|")


def _yes(value) -> str:
    """Да/нет для колонки «Потеря цели»."""
    return "да" if value else "нет"
