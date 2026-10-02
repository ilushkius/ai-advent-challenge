"""Прогон двух длинных сценариев мини-чата (день 25) и сборка отчёта.

Скрипт идёт по сценариям из ``backend/data/mini_chat_scenarios.json`` сообщение за
сообщением: каждое сообщение — реальный вызов модели (ответ по корпусу плюс
извлечение памяти задачи, то есть примерно два запроса на сообщение), поэтому прогон
запускают в непиковое окно. Отчёт пишется в ``docs/reports/mini_chat_scenarios.md``:
у каждого сообщения видны источники, режим, состояние памяти задачи и признак потери
цели — так проверяется, что длинный диалог не теряет цель и не выдаёт ответы без опоры.

Ключ API обязателен: без ``DEEPSEEK_API_KEY`` прогон бессмыслен, скрипт возвращает 2.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

import mini_chat_report  # noqa: E402
from backend.core import config  # noqa: E402
from backend.domain import rag_mode, rag_quotes  # noqa: E402
from backend.services.mini_chat_service import MiniChatService  # noqa: E402
from backend.services.rag_errors import RAGRejected  # noqa: E402

DEFAULT_SCENARIOS = "backend/data/mini_chat_scenarios.json"
DEFAULT_REPORT = "docs/reports/mini_chat_scenarios.md"

#: Подсказка при пустом индексе: корпус и индекс дня 21 собираются отдельными скриптами.
CORPUS_HINT = ("соберите корпус и индекс: uv run python scripts/prepare_rag_corpus.py && "
               "uv run python scripts/index_rag_corpus.py")


def main(argv=None) -> int:
    """Прогоняет сценарии, пишет отчёт и печатает сводку; 0 — прогон состоялся."""
    args = _parse_args(argv)
    scenarios, error = _load_scenarios(_target(args.scenarios))
    if error:
        print(error, file=sys.stderr)
        return 2
    if not config.resolve_api_key():
        print("Ключ API не задан: укажите DEEPSEEK_API_KEY в day21/.env", file=sys.stderr)
        return 2
    top_k = max(1, int(args.top_k))
    service = MiniChatService()
    started = time.perf_counter()
    try:
        result = _run(service, scenarios, top_k=top_k,
                      limit=int(args.limit or 0), quiet=bool(args.quiet))
    except RAGRejected as exc:
        print(f"отбор недоступен: {exc.message}", file=sys.stderr)
        print(CORPUS_HINT, file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started
    report_config = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": config.MODEL_CHAT,
        "top_k": top_k,
        "threshold": f"{rag_quotes.RAG_RELEVANCE_THRESHOLD:g}",
        "seconds": elapsed,
    }
    target = _target(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        mini_chat_report.render_report(result, config=report_config),
        encoding="utf-8", newline="\n")
    for line in mini_chat_report.summary_lines(result):
        print(line)
    print(f"отчёт: {target}")
    return 0


def _run(service: MiniChatService, scenarios: List[dict], *, top_k: int,
         limit: int, quiet: bool) -> dict:
    """Прогоняет все сценарии по очереди и возвращает записи для отчёта."""
    result = {"scenarios": []}
    for scenario in scenarios:
        result["scenarios"].append(_run_scenario(
            service, scenario, top_k=top_k, limit=limit, quiet=quiet))
    return result


def _run_scenario(service: MiniChatService, scenario: dict, *, top_k: int,
                  limit: int, quiet: bool) -> dict:
    """Один сценарий: сессия, сообщения по порядку, память задачи после каждого.

    Сессия закрывается в ``finally``: реплики не остаются в базе, даже если модель
    отказала на середине сценария.
    """
    messages = list(scenario.get("messages") or [])
    if limit:
        messages = messages[:limit]
    session = service.start_session(f"scenario:{scenario.get('id')}")
    session_id = session["session_id"]
    rows: List[dict] = []
    baseline = ""
    try:
        for number, message in enumerate(messages, 1):
            record = service.chat(session_id, message, top_k=top_k)
            memory = record.get("task_memory") or {}
            goal = memory.get("goal") or ""
            baseline = baseline or goal
            rows.append({
                "number": number,
                "question": message,
                "answer": record.get("answer") or "",
                "sources": len(record.get("sources") or []),
                "mode": record.get("mode") or "",
                "memory": memory,
                "memory_updated": record.get("memory_updated"),
                "goal_lost": mini_chat_report.goal_lost(baseline, goal),
            })
            if not quiet:
                print(f"  [{scenario.get('id')}] {number}/{len(messages)}: "
                      f"{record.get('mode')}, источников {len(record.get('sources') or [])}, "
                      f"память {'обновлена' if record.get('memory_updated') else 'не обновлена'}")
    finally:
        service.end_session(session_id)
    return {"id": scenario.get("id"), "title": scenario.get("title"),
            "goal": scenario.get("goal"), "messages": len(messages), "rows": rows}


def _load_scenarios(path: Path) -> Tuple[List[dict], str]:
    """Читает файл сценариев: ``(сценарии, текст ошибки)``; ошибка пуста при успехе."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [], f"файл сценариев не прочитан: {path}: {exc}"
    except ValueError as exc:
        return [], f"файл сценариев не разобран: {path}: {exc}"
    scenarios = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        return [], f"в файле {path} нет непустого списка scenarios"
    return scenarios, ""


def _target(value: str) -> Path:
    """Путь отчёта или сценариев: относительный считается от корня дня."""
    path = Path(value)
    return path if path.is_absolute() else DAY_ROOT / path


def _parse_args(argv):
    """Аргументы прогона: файл сценариев, отчёт, ``top_k``, ограничение и тишина."""
    parser = argparse.ArgumentParser(
        description="Прогон сценариев мини-чата с RAG и памятью задачи")
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS,
                        help="файл сценариев относительно day21/")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help="куда писать отчёт, относительно day21/")
    parser.add_argument("--top-k", type=int, default=rag_mode.RAG_DEFAULT_TOP_K,
                        help="сколько фрагментов брать в контекст")
    parser.add_argument("--limit", type=int, default=0,
                        help="ограничить число сообщений сценария (0 — все)")
    parser.add_argument("--quiet", action="store_true",
                        help="не печатать ход прогона по сообщениям")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
