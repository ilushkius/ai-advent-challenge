"""Диаграмма флоу для отчёта: подписи рёбер и текстовая схема потока (день 20).

Отдельный модуль, потому что ``orchestration_report.py`` держит лимит 400 строк, а
правила подписи — самостоятельная вещь: они повторяют логику интерфейса
(``frontend/orchestration_steps.edge_label`` и ``flow_text``), чтобы диаграмма в
отчёте и схема на экране читались одинаково. Импорт ``frontend`` из скрипта отчёта
запрещён (там Streamlit), поэтому формулы продублированы здесь ОСОЗНАННО: разойтись
им нельзя, иначе отчёт и интерфейс показывали бы разные объёмы данных — поэтому
подписи покрыты проверками сценария 1 (5 элементов → 178 знаков → 7 ключевых слов →
файл → строка).

``flow_diagram`` возвращает определение mermaid (узел на шаг, подпись ребра — объём
данных), ``flow_text`` — ту же схему строками: mermaid рисуется javascript уже в
браузере, поэтому в отчёте рядом всегда есть форма, читаемая без него.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

#: Подписи статусов шага (те же, что в интерфейсе).
STEP_MARKS = {"ok": "✅", "failed": "❌", "stopped": "⏹"}

#: Правила подписи ребра: инструмент → формула по структуре его выхода. Порядок
#: проверок — от источника данных к записи, как шаги идут в демо-сценарии.
EDGE_RULES: tuple[tuple[tuple[str, ...], Callable[[Mapping[str, Any]], str]], ...] = (
    (("search_web", "search_local"),
     lambda out: f"{out.get('count', 0)} элементов"),
    (("summarize",),
     lambda out: f"{len(str(out.get('summary_text') or ''))} знаков"),
    (("extract_keywords",),
     lambda out: f"{out.get('count', 0)} ключевых слов"),
    (("save_to_file",),
     lambda out: f"файл {out.get('filename') or '—'}"),
    (("save_to_db",),
     lambda out: f"строка {out.get('row_id') or '—'}"),
)


def edge_label(step: Mapping[str, Any]) -> str:
    """Объём данных, ушедший следующему серверу (правила ``edge_label`` интерфейса)."""
    output = step.get("output_result")
    structured = output.get("structured") if isinstance(output, Mapping) else None
    structured = structured if isinstance(structured, Mapping) else {}
    for names, label in EDGE_RULES:
        if str(step.get("tool_name") or "") in names:
            return label(structured)
    return str(step.get("status") or "—")


def flow_diagram(steps: Sequence[Mapping[str, Any]]) -> str:
    """Определение mermaid: узел на шаг, подпись ребра — объём данных."""
    lines = ["flowchart LR"]
    for index, step in enumerate(steps):
        mark = STEP_MARKS.get(str(step.get("status") or ""), "")
        lines.append(f'    S{index}["{mark} {step.get("server_name") or "—"}'
                     f'<br/>{step.get("tool_name") or ""}"]')
    for index in range(len(steps) - 1):
        label = edge_label(steps[index]).replace('"', "'")
        lines.append(f'    S{index} -->|"{label}"| S{index + 1}')
    return "\n".join(lines)


def flow_text(steps: Sequence[Mapping[str, Any]]) -> str:
    """Текстовая схема потока: тот же шаг и тот же объём данных, но строкой."""
    lines: list[str] = []
    for index, step in enumerate(steps):
        mark = STEP_MARKS.get(str(step.get("status") or ""), "")
        head = (f"{index}. {mark} {step.get('server_name') or '—'} · "
                f"{step.get('tool_name') or '?'}")
        if index < len(steps) - 1:
            lines.append(f"{head}  →[{edge_label(step)}]→")
        else:
            lines.append(f"{head}  ({edge_label(step)})")
    return "\n".join(lines)


__all__ = ["EDGE_RULES", "STEP_MARKS", "edge_label", "flow_diagram", "flow_text"]
