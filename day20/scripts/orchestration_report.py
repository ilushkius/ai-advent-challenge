"""Сборка отчёта о прогоне сценариев дня 20 (``docs/reports/orchestration_demo.md``).

Отчёт собирается ИЗ ДАННЫХ прогона (проверки — ``DemoRun.checks``, шаги — журнал
``orchestration_steps``, файл и строка базы — ``DemoRun.facts``, состав флота —
``servers_file`` и ``catalog``), поэтому его нельзя «забыть обновить». Правила подписи
ребра повторены из ``frontend/orchestration_steps`` — импорт интерфейса притянул бы
streamlit. Чего в данных нет, того нет и в отчёте: там стоит «—».
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Скрипты лежат в day20/scripts/, а пакеты backend и mcp_servers — в корне дня:
# добавляем в sys.path и корень дня (для пакетов), и scripts/ (для соседей).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import orchestration_report_flow as flow

from backend.domain.orchestration_prompt import (  # noqa: E402
    render_orchestration_block,
)

#: Колонки обязательной таблицы шагов — дословно требование дня, порядок тот же.
STEP_COLUMNS = ("шаг", "сервер", "инструмент", "входные данные",
                "выходные данные", "время выполнения", "статус")
#: Подписи статусов шага — те же, что в интерфейсе (``orchestration_steps``).
#: Колонки записи ``saved_records`` сервера хранения (строка пятого шага сценария 1).
SAVED_RECORD_COLUMNS = ("id", "kind", "title", "content", "source", "metadata",
                        "created_at")
#: Запасной источник флота — файл дня: файл прогона временный, ``orchestration_demo.main``
#: удаляет его рабочий каталог ДО сборки отчёта, а записи дня описывают те же серверы.
FLEET_FILE = DAY_ROOT / "mcp_servers.json"

#: Схема таблиц журнала — по ORM-классам ``backend/models/orchestration.py``.
SCHEMA_COLUMNS = ("колонка", "тип", "назначение")
RUN_SCHEMA = (
    ("id", "INTEGER PK", "номер запуска (им опрашивают статус)"),
    ("query", "VARCHAR(500)", "реплика-запрос, из которой собран план"),
    ("plan", "JSON", "план шагов целиком: имя, шаги, аргументы, условия"),
    ("status", "VARCHAR(16)", "running | completed | stopped | failed"),
    ("started_at", "DATETIME", "когда прогон начался (UTC)"),
    ("finished_at", "DATETIME", "когда завершился (NULL — идёт)"),
    ("total_duration_ms", "INTEGER", "длительность прогона в миллисекундах"),
    ("servers_used", "JSON", "серверы прогона в порядке первого появления"),
)
STEP_SCHEMA = (
    ("id", "INTEGER PK", "номер строки журнала"),
    ("run_id", "INTEGER FK → orchestration_runs", "запуск (ON DELETE CASCADE)"),
    ("step_index", "INTEGER", "номер шага в плане (с нуля)"),
    ("server_name", "VARCHAR(64)", "сервер флота, получивший вызов"),
    ("tool_name", "VARCHAR(64)", "MCP-инструмент шага"),
    ("input_args", "JSON", "аргументы вызова (ссылки плана уже разрешены)"),
    ("output_result", "JSON", "structured, text, reason_code, is_error, duration_ms"),
    ("duration_ms", "INTEGER", "сколько миллисекунд занял шаг"),
    ("status", "VARCHAR(16)", "статус шага: ok | failed | stopped"),
    ("error_message", "TEXT", "причина остановки или сообщение условия перехода"),
)
#: Что осталось за рамками дня — раздел 12.
OUT_OF_SCOPE = (
    "**Планировщик DeepSeek не задействован.** Ключа нет, план собрала эвристика дня, и "
    "ответ модели на промпт выбора инструментов проверить нечем.",
    "**Данные внешние, сводка офлайн.** Поиск идёт в jsonplaceholder (ключ не нужен), а "
    "`--llm off` выключает DeepSeek в `data_server`: сводку делает агрегация.",
    "**Рендер mermaid не проверен:** в headless-браузере этого окружения диаграмма не "
    "отрисовывается, поэтому рядом с ней стоит текстовая схема того же потока.",
    "**Хранилище и политики.** `storage.db` не коммитится (`*.db` в `.gitignore`), дубли "
    "имён инструментов разрешены (первый сервер в порядке файла), повторов нет.",
)

def write_report(path: Path, runs: Sequence[Any], *, catalog: Sequence[Any] = (),
                 output_dir: Path | None = None, tests_summary: str = "",
                 llm: str = "off", servers_file: str = "",
                 screenshot: str = "") -> Path:
    """Пишет отчёт о прогоне в ``path`` и возвращает этот путь (источники чисел —
    ``DemoRun.checks``, журнал шагов, ``DemoRun.facts``, ``catalog`` и ORM дня).
    ``screenshot`` — путь к снимку интерфейса для раздела сценария 1.
    """
    records, fleet_note = _fleet_records(servers_file)
    tools = [str(getattr(tool, "name", tool)) for tool in catalog]
    passed = sum(1 for run in runs for _, ok in run.checks if ok)
    total = sum(len(run.checks) for run in runs)
    servers = len(records) or len(_observed_tools(runs))
    engines = "агрегация (LLM выключена: `--llm off`)" if llm == "off" else "DeepSeek"
    names = "; ".join(str(run.name) for run in runs) or "—"
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    intro = "\n".join([
        "# Оркестрация MCP-серверов: прогон пяти сценариев (день 20)", "",
        f"Прогон: {stamp} · сводка данных: {engines}", "",
        f"Сценариев: {len(runs)} — {names}. Флот дня: {servers or '—'} MCP-сервера по "
        f"stdio, публикуют {len(tools) or '—'} инструментов; каждый шаг — строка журнала.", "",
        f"**проверок пройдено: {passed}/{total}**"])
    parts = [intro + "\n", _checks_section(runs),
             _servers_section(records, tools, runs, fleet_note),
             _scenario_sections(runs, records, tools, output_dir, screenshot),
            _schema_section(),
             _flow_section(_find(runs, "1.")), _tests_section(tests_summary),
             _section("## 12. Что осталось за рамками", "\n\n".join(OUT_OF_SCOPE))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path

def _checks_section(runs: Sequence[Any]) -> str:
    """Проверки прогона: сводная таблица и дословный текст каждой проверки."""
    rows = [(str(run.name), f"{sum(1 for _, ok in run.checks if ok)}/{len(run.checks)}",
             "✅" if run.ok else "❌") for run in runs]
    blocks = [_table(("сценарий", "пройдено", "вердикт"), rows)]
    for run in runs:
        blocks += [f"### {run.name}"] + [f"- {'✓' if ok else '✗'} {what}"
                                        for what, ok in run.checks]
    passed = sum(1 for run in runs for _, ok in run.checks if ok)
    return _section("## 2. Проверки прогона",
                    "Проверки — утверждения сценариев, напечатанные в консоль прогона.",
                    *blocks, f"Итог: {passed} из {sum(len(r.checks) for r in runs)} проверок.")

def _servers_section(records: Sequence[Mapping[str, Any]], tools: Sequence[str],
                     runs: Sequence[Any], note: str) -> str:
    """Таблица «сервер | команда запуска | инструменты» по файлу флота и журналу.

    Кэш инструментов наполняет ``refresh_tools``; имя, увиденное только в журнале шагов,
    помечено ``†`` — ничего не додумано.
    """
    observed = _observed_tools(runs)
    names = [str(r.get("name") or "—") for r in records] or list(observed)
    rows, listed = [], set()
    for name in names:
        record = next((r for r in records if r.get("name") == name), {})
        cached = [str(t.get("name") if isinstance(t, Mapping) else t)
                  for t in record.get("tools_cache") or []]
        called = [t for t in observed.get(name, []) if t not in cached]
        listed.update(cached + called)
        seen = [f"`{t}`" for t in cached] + [f"`{t}`†" for t in called]
        command = " ".join([str(record.get("command") or "—")]
                           + [str(arg) for arg in record.get("args") or []])
        rows.append((f"`{name}`", f"`{command}`" if record else "—", ", ".join(seen) or "—"))
    missing = [t for t in tools if t not in listed]
    tail = (f" Не вызывались и не попали в кэш: {', '.join(missing)}." if missing else "")
    catalog = (f"Каталог флота (`catalog`, порядок реестра): {', '.join(tools)}.{tail}"
               if tools else "")
    return _section(
        "## 3. Три MCP-сервера и их инструменты", note,
        "Команды и кэш — из файла конфигурации (`servers_file`); инструменты сверены с "
        "каталогом реестра и журналом шагов (`server_name`); `†` — вызов без кэша.",
        _table(("сервер", "команда запуска", "инструменты"), rows), catalog)

def _scenario_sections(runs: Sequence[Any], records: Sequence[Mapping[str, Any]],
                       tools: Sequence[str], output_dir: Path | None,
                       screenshot: str = "") -> str:
    """Разделы 4–8: кнопка, агент, ошибка шага, перезапуск, четвёртый сервер.

    Шаги — из ``run.steps``; числа, которых нет в ``run.facts``, заменены «—», а не выдуманы.
    """
    out: list[str] = []

    def sec(number: int, heading: str, *blocks: str) -> None:
        """Раздел сценария с номером (нумерация — порядок разделов отчёта)."""
        out.append(_section(f"## {number}. {heading}", *blocks))

    demo, agent, failure = _find(runs, "1."), _find(runs, "2."), _find(runs, "3.")
    restart, extra = _find(runs, "4."), _find(runs, "5.")
    if demo is not None:
        r, f = demo.report or {}, demo.facts or {}
        row = f.get("saverow") or {}
        where = f" · каталог вывода: `{output_dir.as_posix()}`" if output_dir else ""
        sec(4, "Сценарий 1 — демо-сценарий одной кнопкой",
            f"Прогон №{r.get('run_id', '—')}, статус `{r.get('status') or '—'}`, "
            f"{r.get('total_duration_ms', '—')} мс; строки таблицы — журнал шагов:",
            _steps_table(demo.steps or []),
            f"Файл: `{f.get('file_path') or '—'}`{where}",
            "```markdown\n" + str(f.get("file_text") or "").rstrip() + "\n```",
            f"Строка в базе (`saved_records`, база `{f.get('db_path') or '—'}`):",
            _table(("колонка", "значение"), [(f"`{k}`", _cell(row.get(k), 200))
                                             for k in SAVED_RECORD_COLUMNS]),
            _screenshot_block(screenshot))
    else:
        sec(4, "Сценарий 1 — демо-сценарий одной кнопкой", "Сценарий не выполнялся.")
    if agent is not None:
        r, f = agent.report or {}, agent.facts or {}
        plain = f.get("plain") or {}
        stub = ("[офлайн-заглушка] результат оркестрации в запросе:\n"
                + render_orchestration_block({**r, "detected": True}))
        sec(5, "Сценарий 2 — произвольный запрос через агента",
            f"Реплика: `{r.get('query') or '—'}` распознана доменом, источник плана "
            f"`{r.get('plan_source') or '—'}` — ключа DeepSeek нет, план от эвристики дня:",
            _table(("что", "значение"), [
                ("серверы", _cell(r.get("servers_used"), 200)),
                ("инструменты", _cell(f.get("tools_used"), 200)),
                ("результат ушёл в промпт", _cell(r.get("used_in_prompt"), 200)),
                ("добавлено токенов", _cell(r.get("added_tokens"), 200)),
                ("обычная реплика запускает", _cell(plain.get("detected"), 200))]),
            "```\n" + stub.strip()[:700] + "\n```")
    else:
        sec(5, "Сценарий 2 — произвольный запрос через агента", "Сценарий не выполнялся.")
    if failure is not None:
        r, steps = failure.report or {}, failure.steps or []
        first = steps[1] if len(steps) > 1 else {}
        err = (failure.facts or {}).get("tool_error") or {}
        cases = [("А: инструмента нет ни у одного сервера", r.get("status"),
                  r.get("failed_at_step"), (first.get("output_result") or {}).get("reason_code"),
                  ", ".join(str(s.get("status") or "—") for s in steps),
                  first.get("error_message")),
                 ("Б: инструмент вернул ошибку", err.get("status"), None, err.get("reason_code"),
                  "— (см. проверки, раздел 2)", err.get("error"))]
        sec(6, "Сценарий 3 — ошибка на шаге",
            "Ошибка шага логируется строкой журнала (сервер, инструмент, аргументы, "
            "результат, время, текст ошибки); трассировка случая А — из журнала:",
            _table(("случай", "статус", "шаг", "код причины", "статусы шагов", "текст"),
                   [(c, _cell(s), _cell(n), _cell(rc), _cell(st), _cell(t, 200))
                    for c, s, n, rc, st, t in cases]),
            _steps_table(steps))
    else:
        sec(6, "Сценарий 3 — ошибка на шаге", "Сценарий не выполнялся.")
    if restart is not None:
        cache = [f"`{r.get('name')}` — {len(r.get('tools_cache') or [])} шт."
                 for r in records]
        sec(7, "Сценарий 4 — перезапуск приложения",
            "Перезапуск — новый реестр на том же файле конфигурации и та же служба.",
            _table(("что пережило перезапуск", "источник", "значение"), [
                ("история запусков и шаги", "`orchestration_runs`/`_steps`", "— (раздел 2)"),
                ("статистика", "`OrchestrationStore.stats()`", "— (раздел 2)"),
                ("состав флота", "записи `mcp_servers.json`", f"{len(records) or '—'} сервера"),
                ("кэш инструментов", "`tools_cache` записей", ", ".join(cache) or "—")]))
    else:
        sec(7, "Сценарий 4 — перезапуск приложения", "Сценарий не выполнялся.")
    if extra is not None:
        f = extra.facts or {}
        servers = [str(name) for name in f.get("servers") or []]
        found = [str(name) for name in f.get("tools") or []]
        known = [str(r.get("name")) for r in records] or list(_observed_tools([extra]))
        routed = [what for what, ok in extra.checks
                  if ok and ("маршрут" in what or "нового инструмента" in what)]
        added = ", ".join(n for n in servers if n not in known)
        newest = ", ".join(n for n in found if n not in tools)
        sec(8, "Сценарий 5 — четвёртый сервер без правки кода",
            "Файл флота скопировали во временный каталог и дописали запись — код не менялся.",
            _table(("что", "значение"), [
                ("добавленный сервер", _cell(added, 200)),
                ("запись целиком", "— (копия файла удалена с каталогом)"),
                ("серверов во флоте", _cell(len(servers) or None, 200)),
                ("инструментов во флоте", _cell(len(found) or None, 200)),
                ("новые инструменты", _cell(newest, 200)),
                ("результат маршрутизации", "✅ " + "; ".join(routed) if routed else "—")]))
    else:
        sec(8, "Сценарий 5 — четвёртый сервер без правки кода", "Сценарий не выполнялся.")
    return "".join(out)

def _screenshot_block(screenshot: str) -> str:
    """Снимок интерфейса в разделе сценария 1 (``""`` — снимка нет)."""
    if not screenshot:
        return ""
    name = Path(screenshot).as_posix()
    return f"Снимок интерфейса (живой прогон): `{name}`\n\n![Раздел «Оркестрация»]({name})"


def _schema_section() -> str:
    """Схема таблиц журнала: ``orchestration_runs`` и ``orchestration_steps``."""
    blocks = ["Колонки и назначение — по ORM-классам `backend/models/orchestration.py`."]
    for title, rows in (("### `orchestration_runs` — запуски", RUN_SCHEMA),
                        ("### `orchestration_steps` — шаги запуска", STEP_SCHEMA)):
        blocks += [title, _table(SCHEMA_COLUMNS, [(f"`{n}`", k, v) for n, k, v in rows])]
    return _section(
        "## 9. Схема таблиц `orchestration_runs` / `orchestration_steps`", *blocks,
        "Связь: `orchestration_steps.run_id` → `orchestration_runs.id` с "
        "`ON DELETE CASCADE`; журнал в SQLite — интерфейс видит прогресс, а история "
        "переживает рестарт.")

def _flow_section(run: Any) -> str:
    """Схема флоу: mermaid и та же схема текстом (правила — как в интерфейсе).
    ``frontend`` (streamlit) не импортируется: правила подписи ребра повторены, а mermaid
    в headless-браузере не рисуется (проверено) — текстовая форма обязательна.
    """
    steps = (run.steps or []) if run is not None else []
    if not steps:
        return _section("## 10. Диаграмма флоу",
                        "Сценарий 1 не выполнялся — рисовать нечего.")
    return _section(
        "## 10. Диаграмма флоу",
        "По журналу сценария 1: узел на шаг (`сервер<br/>инструмент`), подпись ребра — "
        "объём данных, ушедший следующему серверу.",
        "```mermaid\n" + flow.flow_diagram(steps) + "\n```",
        "То же текстом: эта форма читается всегда, в том числе там, где mermaid не рисуется:",
        "```\n" + flow.flow_text(steps) + "\n```")

def _tests_section(tests_summary: str) -> str:
    """Итог автотестов дня (``--tests`` включает прогон)."""
    text = f"```\n{tests_summary}\n```" if tests_summary else "не запускались (без `--tests`)."
    return _section("## 11. Автотесты дня", text)

def _section(title: str, *blocks: str) -> str:
    """Раздел отчёта: заголовок, затем непустые блоки через пустую строку."""
    return "\n\n".join([title, *[block for block in blocks if block]]) + "\n"

def _table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Markdown-таблица (``|`` в значениях экранируется, иначе ломается разметка)."""
    head = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    cells = ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(head + cells)

def _cell(value: Any, limit: int = 60) -> str:
    """Значение для ячейки: без переносов строк, «—» вместо пустого, обрезка по пределу."""
    if isinstance(value, (list, tuple)):
        value = ", ".join(map(str, value))
    if value is None:
        return "`—`"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", " ")
    return f"`{text if len(text) <= limit else text[:limit] + '…'}`"

def _steps_table(steps: Sequence[Mapping[str, Any]]) -> str:
    """Обязательная таблица шагов: значения из журнала, ячейки сокращены до ~60 знаков."""
    rows = []
    for step in steps:
        output, status = step.get("output_result") or {}, str(step.get("status") or "—")
        result = output.get("structured") or step.get("error_message") or output.get("text")
        rows.append((step.get("step_index", "—"), _cell(step.get("server_name") or "—"),
                     _cell(step.get("tool_name") or "—"),
                     _cell(step.get("input_args") or {}), _cell(result or "—"),
                     f"{step.get('duration_ms', 0)} мс",
                     f"{flow.STEP_MARKS.get(status, '')} {status}".strip()))
    return _table(STEP_COLUMNS, rows)

def _fleet_records(servers_file: str) -> tuple[list[dict[str, Any]], str]:
    """Записи серверов из файла прогона, иначе — из файла дня, и пометка об этом.
    Файл прогона временный (``orchestration_demo.main`` удаляет рабочий каталог до сборки
    отчёта), поэтому раздел о серверах обязан читаться и без него.
    """
    for index, candidate in enumerate((servers_file, FLEET_FILE.as_posix())):
        try:
            payload = json.loads(Path(candidate).read_text(encoding="utf-8"))
            records = [dict(item) for item in (payload.get("servers") or [])
                       if isinstance(item, Mapping)]
        except (OSError, ValueError, TypeError):
            continue
        if not records:
            continue
        return records, "" if not index else (
            f"Файл прогона `{servers_file or '—'}` недоступен (временный каталог "
            f"прогона удалён вместе с ним), поэтому команды и кэш — из файла дня "
            f"`{FLEET_FILE.name}`.")
    return [], ""

def _observed_tools(runs: Sequence[Any]) -> dict[str, list[str]]:
    """Инструменты по серверам: что реально вызывалось в журнале шагов прогона.
    Шаг с пустым ``server_name`` (неизвестный инструмент, невыполненное условие, ошибка
    маппинга) пропускается: сервера у него нет, приписывать вызов некому.
    """
    seen: dict[str, list[str]] = {}
    for run in runs:
        for step in run.steps or []:
            key, tool = str(step.get("server_name") or ""), str(step.get("tool_name") or "")
            if key and tool and tool not in seen.setdefault(key, []):
                seen[key].append(tool)
    return seen

def _find(runs: Sequence[Any], prefix: str) -> Any:
    """Сценарий по началу его имени (``None`` — не выполнялся)."""
    found = [run for run in runs if str(run.name).startswith(prefix)]
    return found[0] if found else None
