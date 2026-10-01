"""Клетки markdown-таблицы отчёта о режимах отбора RAG (день 23).

Вынесено из ``rag_eval_report.py`` по лимиту 400 строк: сборка отчёта отвечает за
его структуру (шапка, таблица, свип, итог, приложение), а форматирование ячеек —
отдельная забота. Функции здесь чистые: на вход запись вопроса (``entry``) из
``rag_eval_report``, на выход строка ячейки; ни модели, ни файлов, ни консоли.

Соглашение то же, что у ячеек отчётов дней 21–22: переводы строк внутри ячейки
запрещены, поэтому блоки разделяются ``<br>``, а черта экранируется.
"""
from __future__ import annotations

from typing import Sequence

from backend.domain import rag_filter

#: Длина ячейки markdown-таблицы: полные ответы всё равно идут в приложении.
REPORT_CELL_CHARS = 700


def cell(value: str) -> str:
    """Ячейка markdown-таблицы: без переводов строк, с экранированной чертой."""
    text = " ".join(str(value or "").split())
    if len(text) > REPORT_CELL_CHARS:
        text = text[:REPORT_CELL_CHARS - 1].rstrip() + "…"
    return text.replace("|", "\\|")


def expectation(question) -> str:
    """Эталон строки таблицы: формулировка факта и сами литералы."""
    return f"{question.note} Факты: {', '.join(question.key_facts)}"


def verdicts_cell(entry: dict, mode_names: Sequence[str], field: str) -> str:
    """Колонка вердиктов: строка на режим (сравнение идёт с одним эталоном)."""
    if entry["error"]:
        return "сбой"
    parts = []
    for name in mode_names:
        if name == rag_filter.RAG_MODE_BASELINE and field == "vs_baseline":
            parts.append(f"{name}: —")
            continue
        parts.append(f"{name}: {entry[field].get(name) or '—'}")
    return "<br>".join(parts)


def answer_cell(entry: dict, name: str) -> str:
    """Колонка ответа: текст или пометка сбоя (полный ответ — в приложении)."""
    if name == "no_rag":
        record = entry["no_rag"]
        return "—" if record is None else str(record["answer"])
    record = entry["records"].get(name)
    if record is None:
        return f"сбой: {entry['mode_errors'].get(name, '')}"
    prefix = ""
    if record.get("fallback"):
        prefix = "⚠ откат на ответ без RAG: "
    elif record.get("min_score") is not None and entry["dropped"]:
        prefix = f"⚠ отсечено {entry['dropped']} из {entry['pool']}: "
    return prefix + str(record["answer"])


def sources_cell(entry: dict, mode_names: Sequence[str]) -> str:
    """Колонка источников: фрагменты всех режимов, отсечение порога и промахи поиска."""
    if entry["error"]:
        return f"сбой: {entry['error']}"
    blocks = []
    for name in mode_names:
        record = entry["records"].get(name)
        if record is None:
            blocks.append(f"**{name}** — сбой: {entry['mode_errors'].get(name, '')}")
            continue
        blocks.append(f"**{name}** — " + _sources_block(entry, name, record))
    return "<br>".join(blocks)


def source_line(source: dict, record: dict) -> str:
    """Строка фрагмента: файл, раздел, балл отбора и видимые баллы обеих ступеней."""
    parts = [str(source.get("source") or ""), str(source.get("section") or "—"),
             str(source.get("score"))]
    if record.get("reranked"):
        parts.append(f"rerank={source.get('rerank_score')}")
    parts.append(f"vector={source.get('vector_score')}")
    parts.append(f"lexical={source.get('lexical_score')}")
    return " · ".join(parts)


def misses(entries: Sequence[dict], name: str) -> str:
    """Промахи поиска режима: сколько вопросов не удержало ожидаемый источник."""
    checked = [entry for entry in entries if entry["records"].get(name) is not None]
    if not checked:
        return "не считались"
    missed = sum(1 for entry in checked if not entry["found"].get(name))
    if not missed:
        return "нет — источник найден во всех вопросах"
    return f"{missed} из {len(checked)} — там ответ опирался на соседние фрагменты корпуса"


def metrics_line(record: dict) -> str:
    """Метрики одного ответа одной строкой: время, токены, чанки, отсечение, кэш."""
    detail = [f"{int(record.get('duration_ms') or 0)} мс"]
    tokens = _token_total(record)
    if tokens:
        detail.append(f"{tokens} токенов")
    detail.append(f"чанков {int(record.get('chunks_used') or 0)}")
    detail.append(f"до отсечения {int(record.get('candidates') or 0)}, "
                  f"после {int(record.get('kept') or 0)}")
    detail.append(f"порог {_threshold_text(record)}")
    detail.append(f"контекст {int(record.get('context_tokens') or 0)} токенов")
    cache = (record.get("tokens") or {}).get("cache_hit_percent")
    if cache:
        detail.append(f"кэш {cache:.1f} %")
    return ", ".join(detail)


def _sources_block(entry: dict, name: str, record: dict) -> str:
    """Фрагменты одного режима: строки чанков, пометка отсечения и промах поиска."""
    sources = list(record.get("sources") or [])
    candidates = int(record.get("candidates") or 0)
    if not sources:
        return (f"пусто (кандидатов {candidates}, после порога "
                f"{int(record.get('kept') or 0)}, порог {_threshold_text(record)})")
    text = "<br>".join(source_line(source, record) for source in sources)
    if record.get("min_score") is not None and entry["dropped"]:
        text += f"<br>⚠ отсечено {entry['dropped']} из {entry['pool']}"
    if not entry["found"].get(name):
        text += "<br>⚠ ожидались: " + ", ".join(entry["question"].expected_sources)
    return text


def _threshold_text(record: dict) -> str:
    """Порог отсечения записи словами: ``нет``, когда отсечения не было."""
    min_score = record.get("min_score")
    return "нет" if min_score is None else f"{float(min_score):.2f}"


def _token_total(record: dict) -> int:
    """Токены ответа целиком: запрос плюс ответ, 0 — если счётчика нет."""
    tokens = record.get("tokens") or {}
    return int(tokens.get("prompt_tokens") or 0) + int(tokens.get("completion_tokens") or 0)
