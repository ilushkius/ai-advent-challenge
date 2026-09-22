"""Сквозная демонстрация дня 17: свой MCP-сервер, вызов инструмента и агент.

Прогон показывает весь путь целиком, не требуя ключа DeepSeek:

1. подключение к своему MCP-серверу (``mcp_server/server.py``, транспорт stdio) и
   каталог ``tools/list``: имя, описание, ``input_schema`` и ``output_schema``;
2. три успешных вызова ``tools/call`` через ``MCPToolRunner`` — пользователь, пост
   и посты пользователя;
3. отказные вызовы: неизвестный инструмент, нет обязательного аргумента,
   несуществующий id (инструмент отвечает ошибкой, а не исключением);
4. агент: «Найди информацию о пользователе с ID 1» — инструмент вызывается по
   ключевым словам реплики, данные уходят блоком в системный промпт, и в отчёте
   хода (``record["mcp"]``) видно, что именно произошло. Второй вопрос — без
   ключевых слов: инструмент не вызывается.

Офлайн-поведение агента: без ``--live`` клиент DeepSeek подменяется заглушкой,
которая отвечает ПО БЛОКУ ДАННЫХ из системного промпта — поэтому ответ агента сам
доказывает, что результат инструмента дошёл до запроса.

Запуск из папки day17/:

    uv run python scripts/mcp_tool_demo.py
    uv run python scripts/mcp_tool_demo.py --json
    uv run python scripts/mcp_tool_demo.py --report docs/reports/mcp_tool_demo.md
    uv run python scripts/mcp_tool_demo.py --api-base http://127.0.0.1:8080
    uv run python scripts/mcp_tool_demo.py --live        # настоящий DeepSeek, если есть ключ
"""
import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

# Скрипты лежат в day17/scripts/, а пакеты backend и mcp_server — в корне дня:
# добавляем корень дня в sys.path, чтобы запуск работал из любой директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.agents.agent_manager import AgentManager  # noqa: E402
from backend.core import config  # noqa: E402
from backend.domain.mcp_tool_call import MCPToolCallState  # noqa: E402
from backend.schemas import AgentConfig  # noqa: E402
from backend.services.mcp_client import MCPClient, MCPError  # noqa: E402
from backend.services.mcp_registry import MCPRegistry  # noqa: E402
from backend.services.mcp_tool_runner import MCPToolRunner  # noqa: E402
from backend.storage.database import init_db, make_engine, make_session_factory  # noqa: E402
from mcp_server.config import DEFAULT_API_BASE  # noqa: E402

#: Цель по умолчанию — свой сервер дня; аргумент ``--api-base`` дописывается к ней.
DEFAULT_TARGET = config.MCP_DEFAULT_TARGET

#: Вопросы агента: с ключевыми словами вызова и без них.
AGENT_QUESTION = "Найди информацию о пользователе с ID 1"
PLAIN_QUESTION = "Сколько будет 2+2?"

#: Первая строка блока данных MCP в системном промпте (см. mcp_prompt).
BLOCK_HEADER = "## Данные MCP-инструмента"

#: Команда автотестов дня (секция «Автотесты» отчёта).
TESTS_COMMAND = "uv run pytest -q"


@dataclass
class DemoRun:
    """Собранные данные прогона: их печатает консоль, из них собирается отчёт."""

    target: str = ""
    api_base: str = DEFAULT_API_BASE
    transport: str = ""
    server_name: str = ""
    server_version: str = ""
    protocol: str = ""
    tools: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    agent: dict = field(default_factory=dict)
    agent_plain: dict = field(default_factory=dict)
    offline: bool = True
    tests_command: str = TESTS_COMMAND
    tests_summary: str = ""
    outside: str = ""

    def to_dict(self) -> dict:
        """Данные прогона как словарь (режим ``--json``)."""
        return asdict(self)


class ToolStubClient:
    """Офлайн-заглушка DeepSeek: отвечает по блоку данных MCP из системного промпта.

    Не имитирует модель, а доказывает главное: результат инструмента действительно
    попал в запрос. Если блока в промпте нет, заглушка честно говорит и об этом.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        system = next(
            (item.get("content", "") for item in messages if item.get("role") == "system"),
            "",
        )
        payload = _payload_from_block(system)
        content = (
            "[офлайн-заглушка] данные MCP-инструмента в запросе: " + json.dumps(
                payload, ensure_ascii=False)
            if payload is not None
            else "[офлайн-заглушка] блока данных MCP в запросе нет"
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=len(system) // 4,
                completion_tokens=len(content) // 4,
                total_tokens=(len(system) + len(content)) // 4,
            ),
        )


def _payload_from_block(system: str):
    """Разбирает строку «Результат (JSON): …» из системного промпта (None — нет блока)."""
    if BLOCK_HEADER not in system:
        return None
    for line in system.splitlines():
        if line.startswith("Результат (JSON): "):
            return json.loads(line[len("Результат (JSON): "):])
    return None


def build_target(target: str, api_base: str) -> str:
    """Дописывает ``--api-base`` к цели дня (у чужой цели аргумент не принимается)."""
    if api_base == DEFAULT_API_BASE or target != DEFAULT_TARGET:
        return target
    return f"{target} --api-base {api_base}"


def scenario_catalog(run: DemoRun, client: MCPClient) -> None:
    """1. Подключение и каталог инструментов с обеими схемами."""
    print("=== 1. Каталог инструментов своего MCP-сервера ===")
    client.connect()
    tools = client.list_tools()
    run.transport = client.target.transport.label
    run.server_name = client.server_info.get("name", "")
    run.server_version = client.server_info.get("version", "")
    run.protocol = client.server_info.get("protocol", "")
    print(f"цель:        {client.target.label()}")
    print(f"транспорт:   {run.transport}")
    print(f"сервер:      {run.server_name} {run.server_version} "
          f"(протокол {run.protocol or '—'})")
    print(f"инструментов: {len(tools)}")
    for tool in tools:
        item = tool.to_dict()
        run.tools.append(item)
        print(f"\n  • {item['name']} — {item['description'].splitlines()[0]}")
        print(f"    input_schema:  {json.dumps(item['input_schema'], ensure_ascii=False)}")
        print(f"    output_schema: {json.dumps(item['output_schema'], ensure_ascii=False)}")


def _call_record(tool: str, arguments: dict, outcome) -> dict:
    """Запись о вызове для отчёта: успех и неудача описываются одним словарём."""
    return {
        "tool": tool,
        "arguments": arguments,
        "state": outcome.state.value,
        "accepted": outcome.accepted,
        "duration_ms": outcome.duration_ms,
        "structured": (outcome.result.structured if outcome.result else None),
        "is_error": outcome.is_error,
        "reason_code": outcome.reason_code,
        "error": outcome.error,
    }


def _store(run: DemoRun, record: dict, outcome) -> None:
    """Кладёт вызов в успешные или в отказные — по фактическому состоянию.

    Разделение по состоянию, а не по сценарию: если инструмент вдруг ответит
    ошибкой, отчёт не назовёт это успехом.
    """
    target = run.calls if outcome.state is MCPToolCallState.DONE else run.refusals
    target.append(record)


def scenario_calls(run: DemoRun, runner: MCPToolRunner) -> None:
    """2. Три успешных вызова: инструмент отвечает структурированными данными."""
    print("\n=== 2. Вызовы инструмента (tools/call) ===")
    for tool, arguments in (
        ("get_user", {"user_id": 1}),
        ("get_post", {"post_id": 1}),
        ("list_user_posts", {"user_id": 1, "limit": 3}),
    ):
        outcome = runner.call(tool, arguments)
        record = _call_record(tool, arguments, outcome)
        _store(run, record, outcome)
        print(f"\n  {tool}({json.dumps(arguments, ensure_ascii=False)}) → "
              f"{outcome.state.value}, {outcome.duration_ms} мс")
        print("    " + json.dumps(record["structured"], ensure_ascii=False))
        if record["error"]:
            print("    " + record["error"])


def scenario_refusals(run: DemoRun, runner: MCPToolRunner) -> None:
    """3. Отказы: правила допуска и ошибка самого инструмента."""
    print("\n=== 3. Отказные вызовы ===")
    scenarios = (
        ("no_such_tool", {}),
        ("get_user", {}),
        ("get_user", {"user_id": 999}),
    )
    for tool, arguments in scenarios:
        outcome = runner.call(tool, arguments)
        record = _call_record(tool, arguments, outcome)
        _store(run, record, outcome)
        print(f"\n  {tool}({json.dumps(arguments, ensure_ascii=False)}) → "
              f"{record['state']} · {record['reason_code']}")
        print(f"    {record['error']}")


def scenario_agent(run: DemoRun, registry: MCPRegistry, live: bool) -> None:
    """4. Агент: сам вызывает инструмент по реплике и отвечает по его данным."""
    print("\n=== 4. Шаг MCP в работе агента ===")
    run.offline = not live
    # Временный каталог: БД прогона не должна оставаться в папке дня. На Windows
    # файл SQLite держит движок, поэтому его закрываем до выхода из контекста, а
    # ошибки очистки не считаем сбоем прогона.
    with tempfile.TemporaryDirectory(prefix="day17-mcp-demo-",
                                     ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "mcp_tool_demo.db"
        engine = make_engine(f"sqlite:///{db_path.as_posix()}")
        init_db(engine)
        manager = AgentManager(session_factory=make_session_factory(engine),
                              mcp_registry=registry)
        try:
            agent_id = manager.create_agent(AgentConfig(name="Агент дня 17"))
            agent = manager.require_agent(agent_id)
            if not live:
                agent._make_client = lambda: ToolStubClient()  # noqa: SLF001
            _ask(run, agent, "agent", AGENT_QUESTION)
            _ask(run, agent, "agent_plain", PLAIN_QUESTION)
        finally:
            engine.dispose()


def _ask(run: DemoRun, agent, key: str, question: str) -> None:
    """Задаёт агенту вопрос и записывает отчёт хода (включая системный промпт)."""
    record = agent.generate(question)
    report = record.get("mcp") or {}
    payload = {
        "question": question,
        "status": record.get("status"),
        "response": record.get("response"),
        "error": record.get("error"),
        "mcp": report,
        "system_prompt": record.get("system_prompt") or "",
    }
    setattr(run, key, payload)
    print(f"\n  вопрос: {question}")
    print(f"  статус: {payload['status']}")
    print(f"  mcp: инструмент {report.get('tool')!r}, аргументы "
          f"{json.dumps(report.get('arguments') or {}, ensure_ascii=False)}, "
          f"состояние {report.get('state')!r}, вызван: {report.get('called')}, "
          f"данные в промпте: {report.get('used_in_prompt')} "
          f"(+{report.get('added_tokens')} токенов)")
    if report.get("error"):
        print(f"  ошибка вызова: {report['error']}")
    if payload["response"]:
        print(f"  ответ: {payload['response'].splitlines()[0]}")
    block = payload["system_prompt"]
    if BLOCK_HEADER in block:
        start = block.index(BLOCK_HEADER)
        print("  блок данных в системном промпте:")
        for line in block[start:].splitlines()[:4]:
            print(f"    {line}")


def print_summary(run: DemoRun) -> None:
    """Итог прогона одной строкой: что проверено и чем закончилось."""
    print("\n=== Итог ===")
    print(f"инструментов: {len(run.tools)}; успешных вызовов: {len(run.calls)}; "
          f"отказов: {len(run.refusals)}")
    mcp_report = (run.agent or {}).get("mcp") or {}
    print(f"агент: инструмент {mcp_report.get('tool')!r}, состояние "
          f"{mcp_report.get('state')!r}, данные в промпте: "
          f"{mcp_report.get('used_in_prompt')}")
    plain = (run.agent_plain or {}).get("mcp") or {}
    print(f"вопрос без ключевых слов: инструмент вызывался — {plain.get('called')}")


def main(argv=None) -> int:
    """Разбирает аргументы, прогоняет сценарии и (по запросу) собирает отчёт."""
    parser = argparse.ArgumentParser(
        description="Свой MCP-сервер дня 17: каталог, вызовы инструментов и шаг MCP в агенте.",
    )
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help=f"цель подключения (по умолчанию {DEFAULT_TARGET!r})")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE,
                        help=f"адрес внешнего API для своего сервера (по умолчанию {DEFAULT_API_BASE})")
    parser.add_argument("--timeout", type=float, default=config.MCP_TIMEOUT,
                        help=f"таймаут подключения и запросов, с (по умолчанию {config.MCP_TIMEOUT:g})")
    parser.add_argument("--live", action="store_true",
                        help="использовать настоящий DeepSeek (нужен ключ в day17/.env)")
    parser.add_argument("--tests", action="store_true",
                        help="прогнать автотесты дня и записать их сводку в отчёт")
    parser.add_argument("--json", action="store_true", help="напечатать итог как JSON")
    parser.add_argument("--report", default=None,
                        help="собрать markdown-отчёт по прогону в указанный файл")
    args = parser.parse_args(argv)

    run = DemoRun(target=build_target(args.target, args.api_base), api_base=args.api_base)
    # Реестр — тот же путь, что в приложении: одно соединение процесса, из него же
    # берут инструменты агент и ручные вызовы. Таймаут прокидывается фабрикой.
    registry = MCPRegistry(
        client_factory=lambda target, **kwargs: MCPClient(
            target, timeout=args.timeout, **kwargs),
    )
    try:
        client = registry.connect(run.target)
        scenario_catalog(run, client)
        runner = MCPToolRunner(registry)
        scenario_calls(run, runner)
        scenario_refusals(run, runner)
        scenario_agent(run, registry, args.live)
    except MCPError as exc:
        print(f"ОШИБКА подключения: {exc}", file=sys.stderr)
        return 1
    finally:
        registry.close()  # сервер-stdio не остаётся висеть дочерним процессом

    print_summary(run)
    if args.tests:
        run.tests_summary = _run_tests()
        print(f"\nавтотесты: {run.tests_summary}")
    if args.report:
        from mcp_tool_report import write_report  # рядом лежащий модуль дня

        path = Path(args.report)
        write_report(path, run)
        print(f"\nотчёт: {path}")
    if args.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _run_tests() -> str:
    """Сводка ``pytest`` дня: строка итога или текст ошибки (без падения прогона)."""
    import subprocess

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header"], cwd=DAY_ROOT,
        capture_output=True, text=True,
    )
    tail = [line for line in completed.stdout.strip().splitlines() if line.strip()]
    summary = tail[-1] if tail else "нет вывода"
    if completed.returncode != 0:
        summary = f"КОД {completed.returncode}: {summary}"
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
