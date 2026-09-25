"""Сквозной прогон дня 18: оркестрация четырёх сценариев планировщика и отчёт.

Что проверяется — четыре сценария из задания (напоминание через 30 секунд,
периодический сбор каждые 10 секунд, регулярная сводка каждые 20 секунд,
восстановление задач после перезапуска) — и как результат печатается, описано в
``scripts/scheduler_scenarios.py``. Здесь только оркестрация:

* поднять ИЗОЛИРОВАННЫЙ бэкенд отдельным процессом (``scripts/scheduler_stand.py``:
  своя БД, офлайн-заглушка модели, детерминированный источник данных);
* подключить свой MCP-сервер по stdio (``mcp_server/server.py``) и вызывать
  инструменты ПО-НАСТОЯЩЕМУ — так же, как это делает агент в приложении;
* прогнать сценарии и собрать отчёт ``docs/reports/scheduler_demo.md``.

Запуск из папки day20/::

    uv run python scripts/scheduler_demo.py --report docs/reports/scheduler_demo.md
    uv run python scripts/scheduler_demo.py --tests --report docs/reports/scheduler_demo.md
    uv run python scripts/scheduler_demo.py --source-url https://jsonplaceholder.typicode.com/posts
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Скрипты лежат в day20/scripts/, а пакеты backend и mcp_server — в корне дня:
# добавляем в sys.path и корень дня (для пакетов), и scripts/ (для соседей).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.services.mcp_client import MCPError  # noqa: E402
from backend.services.mcp_registry import MCPRegistry  # noqa: E402
from backend.services.mcp_tool_runner import MCPToolRunner  # noqa: E402
from scheduler_scenarios import (  # noqa: E402
    ApiClient,
    DemoRun,
    print_summary,
    scenario_collect,
    scenario_reminder,
    scenario_restart,
    scenario_summary,
)
from scheduler_stand import (  # noqa: E402
    LIVE_SOURCE_URL,
    STAND_SOURCE_URL,
    StandProcess,
    find_free_port,
)

#: Свой MCP-сервер дня (вызовы инструментов идут через него по stdio).
MCP_SERVER = DAY_ROOT / "mcp_server" / "server.py"


def main(argv=None) -> int:
    """Разбирает аргументы, прогоняет четыре сценария и (по запросу) собирает отчёт."""
    parser = argparse.ArgumentParser(
        description="Сценарии планировщика дня 18: напоминание, сбор, сводка, перезапуск.",
    )
    parser.add_argument("--source-url", default="",
                        help=("настоящий адрес источника данных (например, "
                              f"{LIVE_SOURCE_URL}); без него стенд отдаёт "
                              "детерминированные данные и сеть не нужна"))
    parser.add_argument("--db", default=None,
                        help="файл БД прогона (по умолчанию временный каталог)")
    parser.add_argument("--keep-db", action="store_true",
                        help="не удалять БД прогона после завершения")
    parser.add_argument("--tests", action="store_true",
                        help="прогнать автотесты дня и записать их сводку в отчёт")
    parser.add_argument("--json", action="store_true", help="напечатать итог как JSON")
    parser.add_argument("--report", default=None,
                        help="собрать markdown-отчёт по прогону в указанный файл")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="day20-scheduler-demo-"))
    db_path = Path(args.db) if args.db else workdir / "scheduler_run.db"
    if not db_path.is_absolute():
        db_path = DAY_ROOT / db_path
    source_url = args.source_url or STAND_SOURCE_URL
    stand = StandProcess(db_path, find_free_port(), args.source_url)
    client = ApiClient(stand.base_url)
    registry = MCPRegistry()
    # В отчёт идёт ТОТ адрес, который получает инструмент сбора: подменённый
    # (`http://stand.local/posts`) или настоящий, если прогон запущен с
    # `--source-url`. Иначе заголовок отчёта противоречил бы примеру вывода.
    run = DemoRun(backend_url=stand.base_url, source_url=source_url)
    try:
        stand.start()
        stand.wait_ready(client.request)
        # Инструменты вызываются по-настоящему: свой MCP-сервер по stdio, а его
        # тела — HTTP-запросы к стенду (тот же путь, что у агента в приложении).
        registry.connect(
            f'{sys.executable} "{MCP_SERVER}" --backend-url {stand.base_url}')
        runner = MCPToolRunner(registry)
        run.tools = [tool.name for tool in registry.tools()]
        print(f"инструменты сервера: {', '.join(run.tools)}", flush=True)

        scenario_reminder(run, client, runner)
        scenario_collect(run, client, runner, source_url)
        scenario_summary(run, client, runner)
        scenario_restart(run, client, stand)
        run.pids = list(stand.pids)
    except MCPError as exc:
        print(f"ОШИБКА MCP: {exc}", file=sys.stderr)
        return 1
    finally:
        registry.close()  # сервер-stdio не остаётся висеть дочерним процессом
        stand.stop()
        if args.tests:
            run.tests_summary = _run_tests()
        if not args.keep_db:
            shutil.rmtree(workdir, ignore_errors=True)

    print_summary(run)
    if args.report:
        from scheduler_report import write_report  # импорт по месту: отчёт не обязателен

        path = write_report(Path(args.report), run)
        print(f"\nотчёт записан: {path}")
    if args.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 0 if all(item["ok"] for item in run.checks) else 1


def _run_tests() -> str:
    """Сводка ``pytest`` дня: строка итога или текст ошибки (без падения прогона)."""
    try:
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                                   cwd=str(DAY_ROOT), capture_output=True, text=True,
                                   timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"автотесты не запустились: {exc}"
    tail = [line for line in completed.stdout.strip().splitlines() if line.strip()]
    return tail[-1] if tail else f"pytest завершился с кодом {completed.returncode}"


if __name__ == "__main__":
    raise SystemExit(main())
