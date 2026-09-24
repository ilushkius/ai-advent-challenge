"""Четыре сценария дня 19: успех, пустой поиск, ошибка шага и прогон из чата.

Сценарии описаны здесь, а оркестрацию (поднять свой MCP-сервер, прогнать, собрать
отчёт) делает ``scripts/pipeline_demo.py``. Проверки каждого сценария — это
утверждения о наблюдаемом результате: чем закончился прогон, что записано в шагах,
что лежит на диске и что ушло в промпт агента.

Сценарии офлайн: источник по умолчанию — заметки дня
(``mcp_server/data/notes.md``), LLM внутри ``summarize`` выключена (``--llm off``),
поэтому сводку собирает агрегация, а сеть не нужна вовсе.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.domain.pipeline_prompt import PIPELINE_BLOCK_HEADER
from backend.domain.pipeline_spec import (
    DEFAULT_PIPELINE,
    FILE_SOURCE_DEFAULT,
    MSG_NO_DATA,
    STEP_FAILED,
    STEP_OK,
    STEP_STOPPED,
)
from backend.services.pipeline import Pipeline

#: Реплика сценария 4 — пайплайн целиком: поиск, сводка и сохранение файла.
AGENT_PROMPT = "найди статьи про RAG, сделай сводку и сохрани в файл"

#: Реплика, не похожая на композицию: пайплайн запускаться не должен.
PLAIN_PROMPT = "объясни, что такое RAG, в двух предложениях"

#: Аргументы запуска сценария 1 (и его вариантов).
SUCCESS_ARGS = {
    "query": "RAG",
    "source": FILE_SOURCE_DEFAULT,
    "limit": 5,
    "style": "short",
    "max_length": 600,
    "filename": "run-success.md",
    "format": "md",
}

#: Запрос, которого в заметках дня нет: поиск вернёт пустой список.
EMPTY_QUERY = "квантовые вычисления"

#: Стиль, которого нет у инструмента ``summarize``: шаг отвечает ошибкой.
BAD_STYLE = "exotic"


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
        """Данные сценария словарём (режим ``--json`` сценария)."""
        data = asdict(self)
        data["ok"] = self.ok
        return data


def print_summary(runs: list[DemoRun]) -> None:
    """Печатает итог по четырём сценариям и завершает вывод строкой со счётом."""
    print("\n=== Итог ===")
    for run in runs:
        passed = sum(1 for _, ok in run.checks if ok)
        mark = "✓" if run.ok else "✗"
        print(f"  {mark} {run.name}: {passed}/{len(run.checks)} проверок")
    total = sum(len(run.checks) for run in runs)
    passed = sum(1 for run in runs for _, ok in run.checks if ok)
    print(f"  проверок пройдено: {passed}/{total}")


# ---------- сценарий 1: успешный прогон ----------
def scenario_success(pipeline: Pipeline, runner, output_dir: Path) -> DemoRun:
    """Полный пайплайн: три шага ``ok``, файл сохранён и его размер сходится."""
    run = DemoRun(name="1. Успешный пайплайн (search → summarize → save_to_file)")
    report = pipeline.run_pipeline(DEFAULT_PIPELINE, dict(SUCCESS_ARGS))
    steps = report["steps"]
    run.report = report
    run.steps = steps
    saved = _structured(steps, "save_to_file")
    run.facts["saved_file"] = saved
    run.facts["tool_calls"] = [step["tool_name"] for step in steps]
    run.check("прогон завершён со статусом completed",
              report["status"] == "completed", report["status"])
    run.check("шагов ровно три и все со статусом ok",
              len(steps) == 3 and all(step["status"] == STEP_OK for step in steps),
              ", ".join(f"{step['tool_name']}={step['status']}" for step in steps))
    run.check("данные доехали до второго шага (items непусты)",
              bool(_structured(steps, "search").get("items")))
    run.check("сводку собрал движок агрегации",
              _structured(steps, "summarize").get("engine") == "aggregation",
              str(_structured(steps, "summarize").get("engine")))
    path = output_dir / str(saved.get("filename") or "")
    exists = path.is_file()
    size = path.stat().st_size if exists else 0
    run.check("файл сохранён в каталоге вывода", exists, path.as_posix())
    run.check("размер файла совпадает с ответом инструмента",
              exists and size == saved.get("size_bytes"), f"{size} байт")
    run.facts["file_text"] = path.read_text(encoding="utf-8") if exists else ""
    return run


# ---------- сценарий 2: пустой поиск ----------
def scenario_empty_search(pipeline: Pipeline, runner, output_dir: Path) -> DemoRun:
    """Условие ``non_empty`` останавливает прогон: досрочное завершение, не ошибка."""
    run = DemoRun(name="2. Пустой результат поиска — досрочное завершение")
    args = {**SUCCESS_ARGS, "query": EMPTY_QUERY, "filename": "run-stopped.md"}
    report = pipeline.run_pipeline(DEFAULT_PIPELINE, args)
    steps = report["steps"]
    run.report = report
    run.steps = steps
    run.check("прогон завершён со статусом stopped",
              report["status"] == "stopped", report["status"])
    run.check("ошибки шага нет (это не сбой, а решение не звать инструмент)",
              report["failed_at_step"] is None and not report["error"],
              str(report["failed_at_step"]))
    run.check("третий шаг не запускался (в журнале два шага)",
              len(steps) == 2 and [step["tool_name"] for step in steps]
              == ["search", "summarize"],
              " → ".join(step["tool_name"] for step in steps))
    run.check("шаг summarize остановлен условием «нет данных для обработки»",
              steps and steps[1]["status"] == STEP_STOPPED
              and steps[1]["error_message"] == MSG_NO_DATA,
              str(steps[1]["error_message"]) if len(steps) > 1 else "")
    run.check("итоговое сообщение — сообщение условия",
              report["message"] == MSG_NO_DATA, report["message"])
    run.check("файл не создан",
              not (output_dir / "run-stopped.md").exists())
    return run


# ---------- сценарий 3: ошибка шага ----------
def scenario_step_failure(pipeline: Pipeline, runner, output_dir: Path) -> DemoRun:
    """Две причины падения второго шага: негодные аргументы и ошибка инструмента."""
    run = DemoRun(name="3. Ошибка на втором шаге (summarize)")

    broken = copy.deepcopy(DEFAULT_PIPELINE)
    # Шаг summarize ждёт массив элементов, а получает строку запроса: правила
    # допуска отвергают вызов по input_schema ещё до сервера (bad_arguments).
    broken["steps"][1]["args"]["items"] = "$steps.0.structured.query"
    failed_args = {**SUCCESS_ARGS, "filename": "run-failed.md"}
    report = pipeline.run_pipeline(broken, dict(failed_args))
    steps = report["steps"]
    run.report = report
    run.steps = steps
    run.check("прогон остановлен со статусом failed",
              report["status"] == "failed", report["status"])
    run.check("прогон остановился на шаге 1",
              report["failed_at_step"] == 1, str(report["failed_at_step"]))
    run.check("первый шаг остался успешным",
              steps and steps[0]["status"] == STEP_OK,
              steps[0]["status"] if steps else "")
    run.check("второй шаг не выполнен (отказ по аргументам)",
              len(steps) > 1 and steps[1]["status"] == STEP_FAILED
              and (steps[1]["output_result"] or {}).get("reason_code") == "bad_arguments",
              str((steps[1]["output_result"] or {}).get("reason_code"))
              if len(steps) > 1 else "")
    run.check("третий шаг не запускался (шагов два)",
              len(steps) == 2, str(len(steps)))
    run.check("файл не создан", not (output_dir / "run-failed.md").exists())

    # Второй вариант: аргументы верные, но инструмент отвечает ошибкой (isError).
    bad_style = pipeline.run_pipeline(
        DEFAULT_PIPELINE, {**failed_args, "style": BAD_STYLE})
    steps = bad_style["steps"]
    run.facts["tool_error"] = {
        "status": bad_style["status"],
        "error": bad_style["error"],
        "step_status": steps[1]["status"] if len(steps) > 1 else "",
        "is_error": (steps[1]["output_result"] or {}).get("is_error")
        if len(steps) > 1 else None,
    }
    run.check("ошибка инструмента — тоже данные: прогон failed, есть текст причины",
              bad_style["status"] == "failed"
              and bool(bad_style["error"]) and BAD_STYLE in str(bad_style["error"]),
              str(bad_style["error"]))
    return run


# ---------- сценарий 4: прогон из чата ----------
def scenario_agent(manager, agent_id: str, prompt: str = AGENT_PROMPT) -> DemoRun:
    """Реплика про RAG запускает пайплайн, его результат уходит в системный промпт."""
    run = DemoRun(name="4. Запуск пайплайна через агента")
    agent = manager.require_agent(agent_id)
    record = agent.generate(prompt)
    report = record.get("pipeline") or {}
    run.report = report
    run.check("пайплайн распознан в реплике", bool(report.get("detected")))
    run.check("прогон завершён успешно",
              report.get("status") == "completed", str(report.get("status")))
    run.check("результат прогона ушёл в системный промпт",
              bool(report.get("used_in_prompt")))
    run.check("блок пайплайна виден в системном промпте",
              PIPELINE_BLOCK_HEADER in (record.get("system_prompt") or ""))
    run.check("одиночный вызов инструмента не понадобился",
              record.get("mcp") is None)
    run.check("ответ агента получен (офлайн-заглушка модели)",
              record.get("status") == "ok", str(record.get("error") or ""))

    plain = agent.generate(PLAIN_PROMPT)
    run.facts["plain"] = plain.get("pipeline") or {}
    run.check("обычная реплика пайплайн не запускает",
              not (plain.get("pipeline") or {}).get("detected"))
    run.facts["response"] = record.get("response") or ""
    run.facts["steps"] = report.get("steps") or []
    return run


class StubChatClient:
    """Офлайн-заглушка DeepSeek для сценария 4 (интерфейс OpenAI SDK).

    Не имитирует модель, а доказывает главное: результат пайплайна действительно
    попал в запрос. Если блока в системном промпте нет, заглушка честно говорит и
    об этом — по такому ответу сразу видно, что шаг пайплайна не сработал.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        """Возвращает ответ, собранный из системного сообщения запроса."""
        system = next(
            (item.get("content", "") for item in messages if item.get("role") == "system"),
            "",
        )
        block = _pipeline_block(system)
        content = (
            "[офлайн-заглушка] результат пайплайна в запросе:\n" + block
            if block else "[офлайн-заглушка] блока пайплайна в запросе нет"
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


def _pipeline_block(system: str) -> str:
    """Вырезает блок «## Результат пайплайна» из системного промпта (``""`` — нет)."""
    if PIPELINE_BLOCK_HEADER not in system:
        return ""
    tail = system.split(PIPELINE_BLOCK_HEADER, 1)[1]
    return PIPELINE_BLOCK_HEADER + tail.split("\n\n", 1)[0]


def _structured(steps: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """Структурированный выход шага по имени инструмента (``{}`` — шага нет)."""
    for step in steps:
        if step.get("tool_name") == tool:
            structured = (step.get("output_result") or {}).get("structured")
            return structured if isinstance(structured, dict) else {}
    return {}
