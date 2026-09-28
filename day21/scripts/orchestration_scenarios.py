"""Пять сценариев проверки дня 20: демо-кнопка, агент, ошибка шага, рестарт, четвёртый сервер.

Сценарии описаны здесь, а оркестрацию (поднять флот из трёх серверов по stdio,
прогнать, собрать отчёт) делает ``scripts/orchestration_demo.py``. Проверки каждого
сценария — утверждения о наблюдаемом результате: чем закончился прогон, какие
серверы получили вызовы, что записано в шагах, что лежит на диске и что ушло в
промпт агента.

Прогон офлайн и без ключа DeepSeek: данные берутся из jsonplaceholder, сводку
собирает агрегация (``--llm off`` у ``data_server``), а модели в сценарии агента
подменяет офлайн-заглушка (``StubChatClient``) — она доказывает, что блок
результата действительно попал в запрос.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.domain.orchestration_prompt import ORCHESTRATION_BLOCK_HEADER
from backend.domain.orchestration_spec import (
    DEMO_QUERY,
    MSG_COMPLETED,
    demo_arguments,
)
from backend.services.orchestration_service import OrchestrationService

#: Реплика сценария агента: сохранение именно в базу — признак оркестрации.
AGENT_PROMPT = "найди данные про RAG и сохрани в базу"

#: Реплика, не похожая на оркестрацию: прогон не должен запускаться.
PLAIN_PROMPT = "объясни, что такое RAG, в двух предложениях"

#: Инструмент, которого нет ни у одного сервера флота (сценарий ошибки маршрутизации).
UNKNOWN_TOOL = "teleport"

@dataclass
class DemoRun:
    """Один сценарий: имя, проверки, факты прогона и (для отчёта) трассировка."""

    name: str
    checks: list[tuple[str, bool]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Все ли проверки сценария прошли."""
        return all(ok for _, ok in self.checks)

    def check(self, what: str, ok: bool, detail: str = "") -> None:
        """Записывает проверку и печатает её результат."""
        self.checks.append((what, bool(ok)))
        mark = "✓" if ok else "✗"
        print(f"  {mark} {what}" + (f" — {detail}" if detail else ""), flush=True)

    def to_dict(self) -> dict[str, Any]:
        """Данные сценария словарём (режим ``--json``)."""
        data = asdict(self)
        data["ok"] = self.ok
        return data


def structured(steps: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """Структурированный выход шага по номеру (``{}`` — шага или результата нет).

    Общий помощник сценариев: журнал отдаёт результат инструмента полем
    ``output_result``, а проверкам нужна именно структура ответа — по ней видно,
    что данные доехали из сервера в сервер.
    """
    if index >= len(steps):
        return {}
    output = steps[index].get("output_result") or {}
    result = output.get("structured")
    return result if isinstance(result, dict) else {}


def print_summary(runs: list[DemoRun]) -> None:
    """Печатает итог по пяти сценариям и завершает вывод строкой со счётом."""
    print("\n=== Итог ===")
    for run in runs:
        passed = sum(1 for _, ok in run.checks if ok)
        mark = "✓" if run.ok else "✗"
        print(f"  {mark} {run.name}: {passed}/{len(run.checks)} проверок")
    total = sum(len(run.checks) for run in runs)
    passed = sum(1 for run in runs for _, ok in run.checks if ok)
    print(f"  проверок пройдено: {passed}/{total}")


# ---------- сценарий 1: демо-сценарий одной кнопкой ----------
def scenario_demo_button(service: OrchestrationService, output_dir: Path,
                         db_path: Path) -> DemoRun:
    """Демо-сценарий: пять шагов по трём серверам, файл на диске и строка в базе."""
    run = DemoRun(name="1. Демо-сценарий кнопкой (5 шагов по трём серверам)")
    report = service.start_demo(background=False)
    steps = report["steps"]
    run.report = report
    run.steps = steps
    run.check("прогон завершён со статусом completed",
              report["status"] == "completed", report["status"])
    run.check("шагов ровно пять и все ok",
              len(steps) == 5 and all(step["status"] == "ok" for step in steps),
              ", ".join(f"{step['tool_name']}={step['status']}" for step in steps))
    run.check("задействованы три сервера",
              report["servers_used"] == ["search_server", "data_server",
                                         "storage_server"],
              ", ".join(report["servers_used"]))
    run.check("каждый шаг ушёл своему серверу",
              [step["server_name"] for step in steps] == [
                  "search_server", "data_server", "data_server", "storage_server",
                  "storage_server"],
              " → ".join(step["server_name"] for step in steps))
    run.check("реплика запуска — демо-запрос", report["query"] == DEMO_QUERY)
    run.check("итоговое сообщение — «выполнена»",
              report["message"] == MSG_COMPLETED, report["message"])

    found = structured(steps, 0)
    run.check("поиск вернул элементы", bool(found.get("items")),
              f"{found.get('count', 0)} шт.")
    run.check("выход шага 1 стал входом шага 2 (данные перешли по ссылке)",
              steps[1]["input_args"].get("items") == found.get("items"))
    keywords = structured(steps, 2)
    run.check("ключевые слова выделены из сводки",
              bool(keywords.get("keywords")),
              ", ".join(keywords.get("keywords") or [])[:80])

    saved = structured(steps, 3)
    path = output_dir / str(saved.get("filename") or "")
    exists = path.is_file()
    run.check("файл сохранён в каталоге вывода", exists, path.as_posix())
    size = path.stat().st_size if exists else 0
    run.check("размер файла совпадает с ответом инструмента",
              exists and size == saved.get("size_bytes"), f"{size} байт")
    run.facts["file_text"] = path.read_text(encoding="utf-8") if exists else ""
    run.facts["file_path"] = path.as_posix()

    row = structured(steps, 4)
    run.check("строка записана в базу (номер строки получен)",
              bool(row.get("row_id")), f"row_id={row.get('row_id')}")
    run.check("в базе лежит именно эта запись",
              _row_exists(db_path, row.get("row_id"), str(saved.get("filepath") or "")),
              str(db_path.as_posix()))
    run.facts["row"] = row
    run.facts["db_path"] = db_path.as_posix()
    run.facts["saverow"] = _read_row(db_path, row.get("row_id"))
    return run


# ---------- сценарий 2: произвольный запрос через агента ----------
def scenario_agent(manager, agent_id: str, prompt: str = AGENT_PROMPT) -> DemoRun:
    """Реплика про базу запускает флоу, а его результат уходит в системный промпт."""
    run = DemoRun(name="2. Произвольный запрос через агента (реплика → флот)")
    agent = manager.require_agent(agent_id)
    stub = StubChatClient()
    agent._make_client = lambda: stub  # noqa: SLF001 — офлайн-заглушка модели
    record = agent.generate(prompt)
    report = record.get("orchestration") or {}
    run.report = report
    run.steps = report.get("steps") or []
    run.check("оркестрация распознана в реплике", bool(report.get("detected")))
    run.check("прогон завершён успешно",
              report.get("status") == "completed", str(report.get("status")))
    run.check("план построен эвристикой (ключа DeepSeek нет)",
              report.get("plan_source") == "heuristic", str(report.get("plan_source")))
    run.check("задействованы три сервера",
              report.get("servers_used") == ["search_server", "data_server",
                                             "storage_server"],
              ", ".join(report.get("servers_used") or []))
    run.check("результат прогона ушёл в системный промпт",
              bool(report.get("used_in_prompt")) and report.get("added_tokens", 0) > 0,
              f"{report.get('added_tokens', 0)} токенов")
    run.check("блок оркестрации виден в системном промпте",
              ORCHESTRATION_BLOCK_HEADER in (record.get("system_prompt") or ""))
    run.check("модель получила блок в запросе",
              ORCHESTRATION_BLOCK_HEADER in (record.get("response") or ""))
    run.check("один ход — один автоматизм: пайплайн и одиночный вызов пропущены",
              not (record.get("pipeline") or {}).get("detected")
              and record.get("mcp") is None)
    run.check("ответ агента получен (офлайн-заглушка)",
              record.get("status") == "ok", str(record.get("error") or ""))

    plain = agent.generate(PLAIN_PROMPT)
    run.facts["plain"] = plain.get("orchestration") or {}
    run.check("обычная реплика оркестрацию не запускает",
              not (plain.get("orchestration") or {}).get("detected"))
    run.facts["tools_used"] = report.get("tools_used") or []
    return run


# ---------- сценарий 3: ошибка на шаге ----------
def scenario_step_failure(service: OrchestrationService, plan_size: int) -> DemoRun:
    """Две ошибки: неизвестный инструмент и ошибка инструмента (текст длиннее предела)."""
    run = DemoRun(name="3. Ошибка на шаге (маршрутизация и ошибка инструмента)")

    unknown = {"name": "неизвестный инструмент", "steps": [
        {"tool": "search_web", "args": {"query": "", "source": "posts", "limit": 2}},
        {"tool": UNKNOWN_TOOL, "args": {}}]}
    report = service.start_run("проверка маршрутизации", plan=unknown, background=False)
    steps = report["steps"]
    run.report = report
    run.steps = steps
    run.check("неизвестный инструмент: прогон failed",
              report["status"] == "failed", report["status"])
    run.check("останов на втором шаге", report["failed_at_step"] == 1,
              str(report["failed_at_step"]))
    run.check("код причины — unknown_tool",
              (steps[1]["output_result"] or {}).get("reason_code") == "unknown_tool",
              str((steps[1]["output_result"] or {}).get("reason_code")))
    run.check("текст отказа перечисляет известные инструменты",
              "search_web" in str(steps[1]["error_message"]),
              str(steps[1]["error_message"])[:90])
    run.check("первый шаг остался ok",
              steps and steps[0]["status"] == "ok")
    run.check("оставшиеся шаги плана не выполнялись",
              len(steps) < plan_size, f"{len(steps)} из {plan_size}")

    # Второй вариант: шаг доходит до инструмента, но тот отвечает ошибкой.
    huge = "я" * 20001
    too_long = {"name": "слишком длинный текст", "steps": [
        {"tool": "search_web", "args": {"query": "", "source": "posts", "limit": 1}},
        {"tool": "save_to_file",
         "args": {"content": "{huge}", "filename": "too-long.md", "format": "md"}}]}
    failed = service.start_run("проверка ошибки инструмента", plan=too_long,
                               initial_args={"huge": huge}, background=False)
    steps = failed["steps"]
    run.check("ошибка инструмента — тоже данные: прогон failed",
              failed["status"] == "failed", failed["status"])
    run.check("код причины — tool_error",
              (steps[1]["output_result"] or {}).get("reason_code") == "tool_error",
              str((steps[1]["output_result"] or {}).get("reason_code")))
    run.check("в шаге виден признак ошибки инструмента",
              (steps[1]["output_result"] or {}).get("is_error") is True)
    run.check("предыдущие шаги остались ok в журнале",
              [step["status"] for step in steps] == ["ok", "failed"],
              ", ".join(step["status"] for step in steps))
    run.check("текст причины объясняет длину",
              "20000" in str(steps[1]["error_message"]),
              str(steps[1]["error_message"])[:90])
    run.facts["tool_error"] = {
        "status": failed["status"],
        "error": failed["error"],
        "reason_code": (steps[1]["output_result"] or {}).get("reason_code"),
    }
    return run


# ---------- общее ----------
class StubChatClient:
    """Офлайн-заглушка DeepSeek (интерфейс OpenAI SDK) для сценария агента.

    Не имитирует модель, а доказывает главное: результат оркестрации действительно
    попал в запрос. Если блока в системном промпте нет, заглушка честно говорит и
    об этом — по такому ответу сразу видно, что шаг оркестрации не сработал.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        """Возвращает ответ, собранный из системного сообщения запроса."""
        system = next(
            (item.get("content", "") for item in messages if item.get("role") == "system"),
            "",
        )
        block = _orchestration_block(system)
        content = (
            "[офлайн-заглушка] результат оркестрации в запросе:\n" + block
            if block else "[офлайн-заглушка] блока оркестрации в запросе нет"
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


def _orchestration_block(system: str) -> str:
    """Вырезает блок «## Результат оркестрации» из промпта (``""`` — нет)."""
    if ORCHESTRATION_BLOCK_HEADER not in system:
        return ""
    tail = system.split(ORCHESTRATION_BLOCK_HEADER, 1)[1]
    return ORCHESTRATION_BLOCK_HEADER + tail.split("\n\n", 1)[0]


def _row_exists(db_path: Path, row_id: Any, filepath: str) -> bool:
    """Есть ли в базе строка с этим номером и путём файла в метаданных.

    Проверка «строка в базе» нужна не по факту ответа инструмента, а по самому файлу
    SQLite: сервер — отдельный процесс, и только чтение его базы доказывает, что
    запись действительно сделана.
    """
    row = _read_row(db_path, row_id)
    if not row:
        return False
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except ValueError:
        return False
    return str(metadata.get("file") or "") == filepath


def _read_row(db_path: Path, row_id: Any) -> dict[str, Any]:
    """Строка ``saved_records`` по номеру (``{}`` — базы, таблицы или строки нет).

    Колонки читаются из ``PRAGMA table_info``: сценарий не должен ломаться, если
    хранилище дня добавит колонку — отчёт тогда покажет и её.
    """
    if row_id is None or not Path(db_path).is_file():
        return {}
    try:
        connection = sqlite3.connect(Path(db_path).as_posix())
    except sqlite3.Error:
        return {}
    try:
        columns = [item[1] for item in connection.execute(
            "PRAGMA table_info(saved_records)")]
        if not columns:
            return {}
        row = connection.execute(
            f"SELECT {', '.join(columns)} FROM saved_records WHERE id = ?", (row_id,)
        ).fetchone()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return dict(zip(columns, row)) if row else {}


def plan_size(plan: dict[str, Any] | None) -> int:
    """Сколько шагов в плане (для проверок «остальные шаги не выполнялись»)."""
    return len((plan or {}).get("steps") or [])


__all__ = [
    "AGENT_PROMPT",
    "PLAIN_PROMPT",
    "UNKNOWN_TOOL",
    "DemoRun",
    "StubChatClient",
    "demo_arguments",
    "plan_size",
    "print_summary",
    "structured",
    "scenario_agent",
    "scenario_demo_button",
    "scenario_step_failure",
    "structured",
]
