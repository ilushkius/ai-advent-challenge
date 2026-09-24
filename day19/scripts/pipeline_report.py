"""Сборка отчёта о прогоне сценариев дня 19 (``docs/reports/pipeline_demo.md``).

Отчёт собирается ИЗ ДАННЫХ прогона, а не пишется руками: таблица шагов берётся из
журнала (``pipeline_steps``), содержимое файла — с диска, проверки — из сценариев.
Поэтому отчёт нельзя «забыть обновить»: он ровно такой, каким был прогон.

Обязательная таблица дня — «шаг | инструмент | входные данные | выходные данные |
время выполнения | статус»: она и есть доказательство, что данные между
инструментами передались, а не «инструменты просто вызвались по очереди».
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

#: Инструменты композиции и их роль в встроенном пайплайне.
TOOL_ROLES = {
    "search": "шаг 1: находит элементы в источнике (лента API, файл дня, SQLite дня)",
    "summarize": "шаг 2: сводит найденные элементы и выделяет ключевые пункты",
    "save_to_file": "шаг 3: пишет текст сводки в файл каталога output/",
}

#: Колонки обязательной таблицы шагов.
STEP_COLUMNS = ("шаг", "инструмент", "входные данные", "выходные данные",
                "время выполнения", "статус")

#: Колонки обеих таблиц пайплайна (по ORM-классам ``backend/models/pipeline.py``).
RUN_COLUMNS = ("колонка", "тип", "смысл")
RUN_SCHEMA = (
    ("id", "INTEGER PK", "номер запуска (им опрашивают статус)"),
    ("pipeline_name", "VARCHAR(100)", "имя конфигурации пайплайна"),
    ("status", "VARCHAR(16)", "статус: running | completed | stopped | failed"),
    ("started_at", "DATETIME", "когда прогон начался (UTC)"),
    ("finished_at", "DATETIME", "когда завершился (NULL — идёт)"),
    ("total_duration_ms", "INTEGER", "длительность прогона в миллисекундах"),
)
STEP_SCHEMA = (
    ("id", "INTEGER PK", "номер строки журнала"),
    ("run_id", "INTEGER FK → pipeline_runs", "запуск (ON DELETE CASCADE)"),
    ("step_index", "INTEGER", "номер шага в конфигурации (с нуля)"),
    ("tool_name", "VARCHAR(64)", "MCP-инструмент шага"),
    ("input_args", "JSON", "аргументы вызова (ссылки пайплайна уже разрешены)"),
    ("output_result", "JSON", "результат: structured, text, reason_code, is_error, duration_ms"),
    ("duration_ms", "INTEGER", "сколько миллисекунд занял шаг"),
    ("status", "VARCHAR(16)", "статус шага: ok | failed | stopped"),
    ("error_message", "TEXT", "причина остановки или сообщение условия перехода"),
)

#: Что осталось за рамками дня — раздел 9.
OUT_OF_SCOPE = (
    "**Ветвления и параллельные шаги.** Пайплайн — линейная цепочка: шаг идёт за "
    "шагом, а условие может только остановить прогон целиком. Ветки (выбор "
    "продолжения по значению) и параллельный запуск независимых шагов не сделаны.",
    "**Повторы упавших шагов.** Ошибка шага останавливает прогон. Политик retry, "
    "таймаутов на шаг и компенсации побочных эффектов (удалить созданный файл при "
    "отказе) в дне нет.",
    "**Возобновление с места остановки.** Повторный запуск — это новый прогон: "
    "«продолжить с шага 2» по уже записанным результатам не реализовано.",
    "**Векторный источник поиска.** Источник `sqlite:` ищет подстрокой (LIKE), "
    "эмбеддингов и векторного индекса в дне нет: заметки про RAG описывают приём, "
    "а не реализуют его.",
    "**Расписание пайплайнов.** Пайплайн запускается по реплике или через API. "
    "Ставить его в планировщик (день 18) как периодическую задачу день не умеет: "
    "инструменты планировщика вызывают свои действия, а не пайплайн.",
    "**Аутентификация API.** Эндпоинты `/pipelines` открыты, как и остальные: "
    "день рассчитан на локальный запуск.",
)


def write_report(path: Path, runs: Sequence[Any], *, catalog: Sequence[Any] = (),
                 output_dir: Path | None = None, tests_summary: str = "",
                 llm: str = "off") -> Path:
    """Пишет отчёт о прогоне и возвращает путь к нему."""
    parts = [
        "# Композиция MCP-инструментов: прогон четырёх сценариев (день 19)",
        "",
        f"Прогон: {datetime.now(timezone.utc).isoformat(timespec='seconds')} · "
        f"сводка: {'агрегация (LLM выключена)' if llm == 'off' else 'DeepSeek'} · "
        f"источник: заметки дня `mcp_server/data/notes.md`",
        "",
        _checks_section(runs),
        _tools_section(catalog),
        _success_section(runs, output_dir),
        _empty_section(runs),
        _failure_section(runs),
        _agent_section(runs),
        _schema_section(),
        _tests_section(tests_summary),
        _out_of_scope_section(),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


# ---------- 1. проверки ----------
def _checks_section(runs: Sequence[Any]) -> str:
    """Таблица проверок: сценарий, что проверялось, результат."""
    lines = ["## 1. Проверки прогона", "",
             "| сценарий | проверка | результат |", "|---|---|---|"]
    for run in runs:
        for what, ok in run.checks:
            lines.append(f"| {run.name} | {what} | {'✅' if ok else '❌'} |")
    passed = sum(1 for run in runs for _, ok in run.checks if ok)
    total = sum(len(run.checks) for run in runs)
    lines += ["", f"**Итого: {passed} из {total} проверок пройдено.**", ""]
    return "\n".join(lines)


# ---------- 2. инструменты ----------
def _tools_section(catalog: Sequence[Any]) -> str:
    """Таблица трёх инструментов композиции: параметры и роль в пайплайне."""
    lines = ["## 2. Инструменты композиции", "",
             "Сервер дня публикует девять инструментов; пайплайн использует три из "
             "них (остальные шесть — данные и планировщик дней 17–18).", "",
             "| инструмент | параметры | что возвращает | роль в пайплайне |",
             "|---|---|---|---|"]
    for tool in catalog:
        if tool.name not in TOOL_ROLES:
            continue
        properties = (tool.input_schema or {}).get("properties") or {}
        required = set((tool.input_schema or {}).get("required") or [])
        params = ", ".join(
            f"`{name}`{'*' if name in required else ''}: {_json_type(spec)}"
            for name, spec in properties.items()
        )
        returns = ", ".join(
            (tool.output_schema or {}).get("properties", {}).keys()
        ) or "—"
        lines.append(f"| `{tool.name}` | {params or '—'} | {returns} | "
                     f"{TOOL_ROLES[tool.name]} |")
    lines += ["", "`*` — обязательный параметр (`inputSchema.required`).", ""]
    return "\n".join(lines)


def _json_type(spec: Any) -> str:
    """Тип параметра из JSON Schema (``array<object>`` — для списка словарей)."""
    if not isinstance(spec, dict):
        return "—"
    kind = str(spec.get("type") or "—")
    items = spec.get("items")
    if kind == "array" and isinstance(items, dict):
        return f"array<{items.get('type', '—')}>"
    return kind


# ---------- 3. успешный прогон ----------
def _success_section(runs: Sequence[Any], output_dir: Path | None) -> str:
    """Обязательная таблица шагов успешного прогона и содержимое файла."""
    run = _find(runs, "1.")
    lines = ["## 3. Сценарий 1: успешный пайплайн (search → summarize → save_to_file)", ""]
    if run is None:
        return "\n".join(lines + ["Сценарий не выполнялся.", ""])
    report = run.report
    lines += [
        f"Прогон №{report.get('run_id')} · статус `{report.get('status')}` · "
        f"длительность {report.get('total_duration_ms')} мс · "
        f"итог: {report.get('message') or '—'}",
        "",
        "### Трассировка шагов",
        "",
        "| " + " | ".join(STEP_COLUMNS) + " |",
        "|" + "---|" * len(STEP_COLUMNS),
    ]
    for step in run.steps:
        lines.append(
            f"| {step['step_index']} | `{step['tool_name']}` | "
            f"{_cell(step['input_args'])} | {_cell(_output(step))} | "
            f"{step['duration_ms']} мс | {_status(step['status'])} |"
        )
    saved = (run.facts or {}).get("saved_file") or {}
    lines += [
        "",
        "Данные между инструментами передаются маппингом: поле "
        "`$steps.0.structured.items` — это найденные элементы (первый шаг), "
        "`$steps.1.structured.summary_text` — текст сводки (второй шаг). Каждый шаг "
        "видит только выходы предыдущих, поэтому порядок в конфигурации и есть "
        "поток данных.",
        "",
        "### Сохранённый файл (пример из day19/output/)",
        "",
        f"Файл `{saved.get('filename')}` · {saved.get('size_bytes')} байт · "
        f"формат `{saved.get('format')}` · записан {saved.get('saved_at')}",
        "",
        "```markdown",
        str((run.facts or {}).get("file_text") or "").rstrip(),
        "```",
        "",
    ]
    if output_dir is not None:
        lines += [f"Каталог вывода прогона: `{output_dir.as_posix()}`.", ""]
    return "\n".join(lines)


# ---------- 4. пустой поиск ----------
def _empty_section(runs: Sequence[Any]) -> str:
    """Досрочное завершение: условие шага не выполнено, инструмент не вызывался."""
    run = _find(runs, "2.")
    lines = ["## 4. Сценарий 2: пустой результат поиска — досрочное завершение", ""]
    if run is None:
        return "\n".join(lines + ["Сценарий не выполнялся.", ""])
    report = run.report
    lines += [
        f"Запрос `квантовые вычисления` в заметках дня не встречается, поэтому "
        f"первый шаг вернул пустой список, а условие шага `summarize` "
        f"(`$steps.0.structured.items` + `non_empty`) не выполнилось.",
        "",
        "| что | значение |", "|---|---|",
        f"| статус прогона | `{report.get('status')}` |",
        f"| итоговое сообщение | {report.get('message')} |",
        f"| номер упавшего шага | {report.get('failed_at_step')} (None — это не ошибка) |",
        f"| последний шаг | `{run.steps[-1]['tool_name']}` — {_status(run.steps[-1]['status'])} |",
        f"| сообщение шага | {run.steps[-1].get('error_message')} |",
        f"| файл создан | нет |",
        "",
        "Разница между `stopped` и `failed` — содержательная: нечего сводить это не "
        "сбой инструмента, а решение не звать его вовсе, и в промпт агента такое "
        "досрочное завершение попадает как итог прогона (модель не должна отвечать "
        "так, будто сводка есть).",
        "",
    ]
    return "\n".join(lines)


# ---------- 5. ошибка шага ----------
def _failure_section(runs: Sequence[Any]) -> str:
    """Ошибка на втором шаге: отказ по аргументам и ошибка инструмента."""
    run = _find(runs, "3.")
    lines = ["## 5. Сценарий 3: ошибка на втором шаге (summarize)", ""]
    if run is None:
        return "\n".join(lines + ["Сценарий не выполнялся.", ""])
    report = run.report
    lines += [
        "Две причины остановки на одном и том же шаге — до вызова и внутри вызова:",
        "",
        "| причина | что произошло | как видно в журнале |", "|---|---|---|",
        "| негодные аргументы | шаг просит `items`, а маппинг отдал строку запроса "
        "(`$steps.0.structured.query`) | `reason_code = bad_arguments`, вызов до "
        "сервера не дошёл |",
        "| ошибка инструмента | аргументы верные, стиль `exotic` не поддержан | "
        "`is_error = true`, текст причины в `output_result.text` и `error` шага |",
        "",
        "| " + " | ".join(STEP_COLUMNS) + " |",
        "|" + "---|" * len(STEP_COLUMNS),
    ]
    for step in run.steps:
        lines.append(
            f"| {step['step_index']} | `{step['tool_name']}` | "
            f"{_cell(step['input_args'])} | {_cell(_output(step))} | "
            f"{step['duration_ms']} мс | {_status(step['status'])} |"
        )
    tool_error = (run.facts or {}).get("tool_error") or {}
    lines += [
        "",
        f"Статус прогона: `{report.get('status')}`, остановился на шаге "
        f"{report.get('failed_at_step')}; третий шаг не запускался — ошибка любого "
        "шага останавливает пайплайн и логируется с контекстом (входные аргументы, "
        "результат, время, текст ошибки).",
        "",
        f"Вариант с ошибкой инструмента: `{tool_error.get('status')}`, текст "
        f"причины — `{tool_error.get('error')}`.",
        "",
    ]
    return "\n".join(lines)


# ---------- 6. агент ----------
def _agent_section(runs: Sequence[Any]) -> str:
    """Запуск пайплайна репликой: отчёт хода и блок в системном промпте."""
    run = _find(runs, "4.")
    lines = ["## 6. Сценарий 4: запуск пайплайна через агента", ""]
    if run is None:
        return "\n".join(lines + ["Сценарий не выполнялся.", ""])
    report = run.report
    plain = (run.facts or {}).get("plain") or {}
    lines += [
        "Реплика: `найди статьи про RAG, сделай сводку и сохрани в файл`. Эвристика "
        "домена находит фразы всех трёх действий (поиск, сводка, сохранение) и "
        "запускает встроенный пайплайн синхронно — ответ агента должен опираться на "
        "данные этого же хода.",
        "",
        "| что | значение |", "|---|---|",
        f"| пайплайн распознан | `{report.get('detected')}` |",
        f"| статус прогона | `{report.get('status')}` |",
        f"| результат ушёл в промпт | `{report.get('used_in_prompt')}` |",
        f"| добавлено токенов | {report.get('added_tokens')} |",
        f"| одиночный вызов инструмента | не понадобился (`record['mcp']` = None) |",
        f"| обычная реплика | пайплайн не запущен "
        f"(`detected = {plain.get('detected')}`) |",
        "",
        "Блок, который увидела модель (фрагмент системного промпта):",
        "",
        "```",
        str((run.facts or {}).get("response") or "").strip()[:600],
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------- 7. схема таблиц ----------
def _schema_section() -> str:
    """Таблицы журнала прогона: ``pipeline_runs`` и ``pipeline_steps``."""
    lines = ["## 7. Схема таблиц пайплайна", ""]
    for title, columns, rows in (
        ("### `pipeline_runs` — запуски пайплайна", RUN_COLUMNS, RUN_SCHEMA),
        ("### `pipeline_steps` — шаги прогона", RUN_COLUMNS, STEP_SCHEMA),
    ):
        lines += [title, "",
                  "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        for name, kind, meaning in rows:
            lines.append(f"| `{name}` | {kind} | {meaning} |")
        lines.append("")
    lines += [
        "Связь: `pipeline_steps.run_id` → `pipeline_runs.id` с `ON DELETE CASCADE` "
        "(удаление запуска уносит его шаги). Прогон идёт в фоновом потоке бэкенда, "
        "поэтому журнал лежит в SQLite: интерфейс опрашивает статус и видит прогресс, "
        "пока шаги выполняются.",
        "",
    ]
    return "\n".join(lines)


# ---------- 8. автотесты ----------
def _tests_section(tests_summary: str) -> str:
    """Итог автотестов дня (в отчёт попадает, только если их запускали)."""
    lines = ["## 8. Автотесты дня", ""]
    if not tests_summary:
        lines += ["Прогон запускался без `--tests`: сводка pytest в отчёт не попала.", ""]
        return "\n".join(lines)
    lines += ["```", tests_summary, "```", ""]
    return "\n".join(lines)


# ---------- 9. рамки дня ----------
def _out_of_scope_section() -> str:
    """Что осталось за рамками дня."""
    lines = ["## 9. Что осталось за рамками дня", ""]
    lines += [f"{item}\n" for item in OUT_OF_SCOPE]
    return "\n".join(lines)


# ---------- помощники ----------
def _find(runs: Sequence[Any], prefix: str):
    """Сценарий по началу его имени (``None`` — не выполнялся)."""
    for run in runs:
        if str(run.name).startswith(prefix):
            return run
    return None


def _output(step: dict[str, Any]) -> dict[str, Any]:
    """Результат шага для таблицы, без служебного поля ``duration_ms``."""
    output = dict(step.get("output_result") or {})
    output.pop("duration_ms", None)
    return output


def _cell(value: Any, limit: int = 220) -> str:
    """Значение для ячейки таблицы: компактный JSON без переносов строк."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("|", "\\|").replace("\n", " ")
    return f"`{text if len(text) <= limit else text[:limit] + '…'}`"


def _status(status: str) -> str:
    """Статус шага подписью интерфейса."""
    return {"ok": "✅ ok", "failed": "❌ failed", "stopped": "⏹ stopped"}.get(
        status, status or "—"
    )
