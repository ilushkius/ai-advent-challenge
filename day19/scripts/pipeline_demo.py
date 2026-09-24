"""Сквозной прогон дня 19: четыре сценария пайплайна и отчёт.

Что проверяется — четыре сценария из задания: успешный пайплайн, пустой результат
поиска (досрочное завершение), ошибка на втором шаге и запуск пайплайна через
агента — описано в ``scripts/pipeline_scenarios.py``. Здесь только оркестрация:

* поднять свой MCP-сервер дня по stdio (``mcp_server/server.py``) и вызывать
  инструменты ПО-НАСТОЯЩЕМУ — так же, как это делает приложение;
* прогнать сценарии на временной БД (журнал запусков и шагов — настоящий SQLite);
* собрать отчёт ``docs/reports/pipeline_demo.md``.

Прогон офлайн: источник по умолчанию — заметки дня, LLM внутри ``summarize``
выключена (``--llm off``), поэтому ни ключ, ни сеть не нужны.

Запуск из папки day19/::

    uv run python scripts/pipeline_demo.py --report docs/reports/pipeline_demo.md
    uv run python scripts/pipeline_demo.py --llm auto      # настоящая сводка от LLM
    uv run python scripts/pipeline_demo.py --tests --report docs/reports/pipeline_demo.md
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Скрипты лежат в day19/scripts/, а пакеты backend и mcp_server — в корне дня:
# добавляем в sys.path и корень дня (для пакетов), и scripts/ (для соседей).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.services.mcp_client import MCPError  # noqa: E402
from backend.services.mcp_registry import MCPRegistry  # noqa: E402
from backend.services.mcp_tool_runner import MCPToolRunner  # noqa: E402
from backend.services.pipeline import Pipeline  # noqa: E402
from backend.services.pipeline_service import PipelineService  # noqa: E402
from backend.storage.database import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)
from backend.storage.pipeline_store import PipelineStore  # noqa: E402
from backend.agents.agent_manager import AgentManager  # noqa: E402
from backend.schemas import AgentConfig  # noqa: E402
from pipeline_scenarios import (  # noqa: E402
    AGENT_PROMPT,
    DemoRun,
    StubChatClient,
    print_summary,
    scenario_agent,
    scenario_empty_search,
    scenario_step_failure,
    scenario_success,
)

#: Свой MCP-сервер дня (вызовы инструментов идут через него по stdio).
MCP_SERVER = DAY_ROOT / "mcp_server" / "server.py"

#: Адрес внешнего API: в офлайн-сценариях не используется (источник — файл дня).
API_BASE = "https://jsonplaceholder.typicode.com"


def main(argv=None) -> int:
    """Разбирает аргументы, прогоняет четыре сценария и (по запросу) собирает отчёт."""
    parser = argparse.ArgumentParser(
        description="Сценарии пайплайна дня 19: успех, пустой поиск, ошибка шага, агент.",
    )
    parser.add_argument("--report", default="docs/reports/pipeline_demo.md",
                        help="куда записать markdown-отчёт (пусто — не писать)")
    parser.add_argument("--output-dir", default=str(DAY_ROOT / "output"),
                        help="каталог, куда save_to_file пишет файлы (по умолчанию day19/output)")
    parser.add_argument("--llm", choices=("off", "auto"), default="off",
                        help="off — сводка агрегацией (по умолчанию, без ключа и сети)")
    parser.add_argument("--db", default=None,
                        help="файл БД прогона (по умолчанию временный каталог)")
    parser.add_argument("--json", action="store_true", help="напечатать итог как JSON")
    parser.add_argument("--tests", action="store_true",
                        help="прогнать автотесты дня и записать их сводку в отчёт")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="day19-pipeline-demo-"))
    db_path = Path(args.db) if args.db else workdir / "pipeline.db"
    if not db_path.is_absolute():
        db_path = DAY_ROOT / db_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = DAY_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    registry = MCPRegistry()
    runs: list[DemoRun] = []
    catalog: list = []
    try:
        # Инструменты вызываются по-настоящему: свой MCP-сервер по stdio, а его
        # тела читают файл дня и пишут в каталог вывода — тот же путь, что в приложении.
        registry.connect(_server_target(output_dir, db_path, args.llm))
        catalog = registry.tools()
        print(f"инструменты сервера: {', '.join(tool.name for tool in catalog)}",
              flush=True)
        store = PipelineStore(session_factory=make_session_factory(engine))
        pipeline = Pipeline(runner=MCPToolRunner(registry), store=store)
        runs.append(scenario_success(pipeline, registry, output_dir))
        runs.append(scenario_empty_search(pipeline, registry, output_dir))
        runs.append(scenario_step_failure(pipeline, registry, output_dir))
        runs.append(_agent_run(engine, registry, pipeline, store))
    except MCPError as exc:
        print(f"ОШИБКА MCP: {exc}", file=sys.stderr)
        return 1
    finally:
        registry.close()  # сервер-stdio не остаётся висеть дочерним процессом
        engine.dispose()
        if not args.db:
            shutil.rmtree(workdir, ignore_errors=True)

    tests_summary = _run_tests() if args.tests else ""
    _print_reports(runs)
    print_summary(runs)
    if args.report:
        from pipeline_report import write_report  # импорт по месту: отчёт не обязателен

        path = write_report(Path(args.report), runs, catalog=catalog,
                            output_dir=output_dir, tests_summary=tests_summary,
                            llm=args.llm)
        print(f"\nотчёт записан: {path}")
    if args.json:
        print(json.dumps([run.to_dict() for run in runs],
                         ensure_ascii=False, indent=2, default=str))
    return 0 if all(run.ok for run in runs) else 1


def _server_target(output_dir: Path, db_path: Path, llm: str) -> str:
    """Команда запуска своего MCP-сервера с аргументами прогона."""
    return (
        f'{sys.executable} "{MCP_SERVER}" --llm {llm} '
        f'--output-dir "{output_dir}" --file-root "{DAY_ROOT}" '
        f'--db-path "{db_path}" --api-base {API_BASE}'
    )


def _agent_run(engine, registry, pipeline: Pipeline, store: PipelineStore) -> DemoRun:
    """Сценарий 4: агент на временной БД, служба пайплайна — на том же журнале."""
    manager = AgentManager(
        session_factory=make_session_factory(engine),
        mcp_registry=registry,
        pipeline_service=PipelineService(pipeline=pipeline, store=store),
    )
    agent_id = manager.create_agent(AgentConfig(name="Агент дня 19"))
    agent = manager.require_agent(agent_id)
    agent._make_client = lambda: StubChatClient()  # noqa: SLF001 — офлайн-заглушка
    return scenario_agent(manager, agent_id, AGENT_PROMPT)


def _print_reports(runs: list[DemoRun]) -> None:
    """Печатает трассировку шагов каждого сценария (что и с чем вызвано)."""
    for run in runs:
        steps = run.steps or (run.report.get("steps") if isinstance(run.report, dict) else [])
        if not steps:
            continue
        print(f"\n{run.name}:", flush=True)
        for step in steps:
            reason = (step.get("output_result") or {}).get("reason_code") or "—"
            print(f"  шаг {step.get('step_index')}: {step.get('tool_name')} "
                  f"[{step.get('status')}] {step.get('duration_ms')} мс "
                  f"(reason_code={reason})", flush=True)


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
