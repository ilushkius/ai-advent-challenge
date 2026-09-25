"""Сквозной прогон дня 20: пять сценариев флота MCP-серверов и отчёт.

Что проверяется — пять сценариев из задания (демо-кнопка, произвольный запрос через
агента, ошибка на шаге, перезапуск приложения, четвёртый сервер правкой файла) —
описано в ``scripts/orchestration_scenarios.py`` и ``scripts/orchestration_fleet.py``.
Здесь только оркестрация:

* собрать временный ``mcp_servers.json`` с ТРЕМЯ настоящими серверами дня
  (``mcp_servers/search_server``, ``data_server``, ``storage_server``) и поднять их
  по stdio — вызовы идут по-настоящему, как в приложении;
* прогнать сценарии на временной БД: журнал запусков и шагов — настоящий SQLite;
* собрать отчёт ``docs/reports/orchestration_demo.md``.

Прогон офлайн и без ключа DeepSeek: ``data_server`` запускается с ``--llm off``
(сводку собирает агрегация), план строит эвристика домена, а модель в сценарии
агента подменяет офлайн-заглушка.

Запуск из папки day20/::

    uv run python scripts/orchestration_demo.py --report docs/reports/orchestration_demo.md
    uv run python scripts/orchestration_demo.py --tests --report docs/reports/orchestration_demo.md
    uv run python scripts/orchestration_demo.py --json --no-report
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Скрипты лежат в day20/scripts/, а пакеты backend и mcp_servers — в корне дня:
# добавляем в sys.path и корень дня (для пакетов), и scripts/ (для соседей).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.agents.agent_manager import AgentManager  # noqa: E402
from backend.schemas import AgentConfig  # noqa: E402
from backend.services.mcp_client import MCPError  # noqa: E402
from backend.services.mcp_registry import MCPRegistry  # noqa: E402
from backend.services.orchestration_service import OrchestrationService  # noqa: E402
from backend.services.orchestrator import Orchestrator  # noqa: E402
from backend.services.pipeline import Pipeline  # noqa: E402
from backend.services.pipeline_service import PipelineService  # noqa: E402
from backend.storage.database import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)
from backend.storage.orchestration_store import OrchestrationStore  # noqa: E402
from backend.storage.pipeline_store import PipelineStore  # noqa: E402
from orchestration_fleet import scenario_new_server, scenario_restart  # noqa: E402
from orchestration_scenarios import (  # noqa: E402
    AGENT_PROMPT,
    DemoRun,
    StubChatClient,
    demo_arguments,
    plan_size,
    print_summary,
    scenario_agent,
    scenario_demo_button,
    scenario_step_failure,
)

#: Серверы дня по stdio: имя пакета → путь к точке входа.
SERVER_SCRIPTS = {
    "search_server": DAY_ROOT / "mcp_servers" / "search_server" / "server.py",
    "data_server": DAY_ROOT / "mcp_servers" / "data_server" / "server.py",
    "storage_server": DAY_ROOT / "mcp_servers" / "storage_server" / "server.py",
}

#: Сервер-эхо для сценария 5 (ассет тестов дня 17, живёт в tests/).
ECHO_SERVER = DAY_ROOT / "tests" / "mcp_echo_server.py"

#: Адрес внешнего API: jsonplaceholder, ключ и регистрация не нужны.
API_BASE = "https://jsonplaceholder.typicode.com"


def main(argv=None) -> int:
    """Разбирает аргументы, прогоняет пять сценариев и (по запросу) собирает отчёт."""
    parser = argparse.ArgumentParser(
        description="Сценарии оркестрации дня 20: кнопка, агент, ошибка шага, "
                    "перезапуск, четвёртый сервер.",
    )
    parser.add_argument("--report", default="docs/reports/orchestration_demo.md",
                        help="куда записать markdown-отчёт")
    parser.add_argument("--no-report", action="store_true", help="не писать отчёт")
    parser.add_argument("--output-dir", default=str(DAY_ROOT / "output"),
                        help="каталог, куда save_to_file пишет файлы (по умолчанию day20/output)")
    parser.add_argument("--db", default=None,
                        help="файл БД прогона (по умолчанию временный каталог)")
    parser.add_argument("--servers-file", default=None,
                        help="файл конфигурации флота (по умолчанию временный)")
    parser.add_argument("--llm", choices=("off", "auto"), default="off",
                        help="off — сводка агрегацией (по умолчанию, без ключа и сети)")
    parser.add_argument("--screenshot", default=None,
                        help="снимок интерфейса для отчёта (путь от корня дня; "
                             "кладётся в раздел сценария 1)")
    parser.add_argument("--json", action="store_true", help="напечатать итог как JSON")
    parser.add_argument("--tests", action="store_true",
                        help="прогнать автотесты дня и записать их сводку в отчёт")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="day20-orchestration-demo-"))
    db_path = _absolute(args.db) if args.db else workdir / "orchestration.db"
    output_dir = _absolute(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    servers_file = _absolute(args.servers_file) if args.servers_file else \
        workdir / "mcp_servers.json"

    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    store = OrchestrationStore(session_factory=make_session_factory(engine))
    registry = MCPRegistry(servers_file=servers_file, cwd=str(DAY_ROOT))
    service = OrchestrationService(
        orchestrator=Orchestrator(registry=registry, store=store), store=store)
    runs: list[DemoRun] = []
    catalog: list[str] = []
    try:
        write_servers_file(servers_file, output_dir, db_path, args.llm)
        registry.connect_all()  # сценарии идут по реальному флоту: серверы по stdio
        status = registry.fleet_status()
        catalog = [tool.name for tool in registry.list_all_tools()]
        print(f"флот: {status['count']} серверов, подключено {status['connected']}, "
              f"инструментов {status['total_tools']}", flush=True)
        print(f"инструменты: {', '.join(catalog)}", flush=True)

        runs.append(scenario_demo_button(service, output_dir, db_path))
        runs.append(_agent_run(engine, registry, store))
        runs.append(scenario_step_failure(service, plan_size(_demo_plan())))
        runs.append(scenario_restart(registry, service, servers_file))
        runs.append(scenario_new_server(registry, servers_file, ECHO_SERVER, workdir))
    except MCPError as exc:
        print(f"ОШИБКА MCP: {exc}", file=sys.stderr)
        return 1
    finally:
        registry.close()  # серверы-stdio не остаются висеть дочерними процессами
        engine.dispose()
        if not args.db:
            shutil.rmtree(workdir, ignore_errors=True)

    tests_summary = _run_tests() if args.tests else ""
    print_reports(runs)
    print_summary(runs)
    if args.report and not args.no_report:
        from orchestration_report import write_report  # импорт по месту: отчёт не обязателен

        path = write_report(Path(args.report), runs, catalog=catalog,
                            output_dir=output_dir, tests_summary=tests_summary,
                            llm=args.llm, servers_file=servers_file.as_posix(),
                            screenshot=args.screenshot or "")
        print(f"\nотчёт записан: {path}")
    if args.json:
        print(json.dumps([run.to_dict() for run in runs],
                         ensure_ascii=False, indent=2, default=str))
    return 0 if all(run.ok for run in runs) else 1


def _absolute(value: str) -> Path:
    """Путь из аргументов: относительный считается от корня дня."""
    path = Path(value)
    return path if path.is_absolute() else DAY_ROOT / path


def write_servers_file(path: Path, output_dir: Path, db_path: Path, llm: str) -> Path:
    """Пишет конфигурацию флота из трёх НАСТОЯЩИХ серверов дня (абсолютные пути).

    Команда запуска — тот же интерпретатор (``sys.executable``), что и у прогона:
    серверы поднимаются по stdio без ``uv`` и без сети. Каждый получает свои
    аргументы прогона: ``search_server`` — корень источников и адрес внешнего API,
    ``data_server`` — режим LLM, ``storage_server`` — каталог файлов и базу строк.
    """
    servers = [
        {
            "name": "search_server",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPTS["search_server"]), "--file-root", str(DAY_ROOT),
                     "--api-base", API_BASE, "--timeout", "20"],
            "description": "Поиск данных: search_web (jsonplaceholder), search_local "
                           "(файл дня), fetch_url",
            "tools_cache": [],
        },
        {
            "name": "data_server",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPTS["data_server"]), "--llm", llm, "--timeout", "20"],
            "description": "Обработка данных: summarize (агрегация без ключа), "
                           "extract_keywords, filter_by_date, aggregate",
            "tools_cache": [],
        },
        {
            "name": "storage_server",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPTS["storage_server"]),
                     "--output-dir", str(output_dir), "--db-path", str(db_path)],
            "description": "Сохранение и выдача: save_to_file (output/), save_to_db "
                           "(база прогона), list_saved, load_from_file",
            "tools_cache": [],
        },
    ]
    path.write_text(json.dumps({"servers": servers}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _demo_plan() -> dict:
    """Демо-план из домена (сколько в нём шагов — проверяет сценарий 3)."""
    from backend.domain.orchestration_spec import DEMO_PLAN

    return DEMO_PLAN


def _agent_run(engine, registry: MCPRegistry,
               store: OrchestrationStore) -> DemoRun:
    """Сценарий 2: агент на временной БД, службы дня — на том же журнале и флоте."""
    factory = make_session_factory(engine)
    pipeline = PipelineService(pipeline=Pipeline(store=PipelineStore(session_factory=factory)),
                               store=PipelineStore(session_factory=factory))
    manager = AgentManager(
        session_factory=factory,
        mcp_registry=registry,
        pipeline_service=pipeline,
        orchestration_service=OrchestrationService(
            orchestrator=Orchestrator(registry=registry, store=store), store=store),
    )
    agent_id = manager.create_agent(AgentConfig(name="Агент дня 20"))
    agent = manager.require_agent(agent_id)
    agent._make_client = lambda: StubChatClient()  # noqa: SLF001 — офлайн-заглушка
    return scenario_agent(manager, agent_id, AGENT_PROMPT)


def print_reports(runs: list[DemoRun]) -> None:
    """Печатает трассировку шагов каждого сценария (что и на каком сервере вызвано)."""
    for run in runs:
        steps = run.steps or (run.report.get("steps")
                              if isinstance(run.report, dict) else [])
        if not steps:
            continue
        print(f"\n{run.name}:", flush=True)
        for step in steps:
            reason = (step.get("output_result") or {}).get("reason_code") or "—"
            print(f"  шаг {step.get('step_index')}: {step.get('server_name')} · "
                  f"{step.get('tool_name')} [{step.get('status')}] "
                  f"{step.get('duration_ms')} мс (reason_code={reason})", flush=True)


def _run_tests() -> str:
    """Сводка ``pytest`` дня: строка итога или текст ошибки (без падения прогона)."""
    try:
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                                   cwd=str(DAY_ROOT), capture_output=True, text=True,
                                   timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"автотесты не запустились: {exc}"
    tail = [line for line in completed.stdout.strip().splitlines() if line.strip()]
    return tail[-1] if tail else f"pytest завершился с кодом {completed.returncode}"


if __name__ == "__main__":
    raise SystemExit(main())
