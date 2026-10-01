"""Сборка отчёта о режимах отбора RAG (день 23): markdown из готовых записей прогона.

Отдельный модуль, а не часть ``run_rag_eval.py``, по той же причине, что
``cost_optimization_report.py`` рядом с прогоном расходов: прогон делает запросы к
модели, меряет время и держит код возврата, а печать отчёта — чистая функция от уже
собранных записей. Печать можно проверить и поправить, не тратя вызовы модели.
Форматирование самих markdown-ячеек живёт в соседнем ``rag_eval_cells.py``: иначе
файл выходил за лимит 400 строк.

Единица данных здесь — запись вопроса (``entry``), ровно эти ключи:

* ``question`` — элемент ``rag_eval.RAG_QUESTIONS``;
* ``no_rag`` — ответ без корпуса (эталон сравнения) или ``None`` при сбое;
* ``records`` — ответ службы на каждый режим отбора (``None``, если режим упал);
* ``mode_errors`` — имя режима → текст сбоя (иначе ключа нет);
* ``error`` — текст сбоя самой пары «без RAG», иначе пусто;
* ``verdicts`` — имя режима → вердикт против «без RAG»;
* ``vs_baseline`` — имя режима → вердикт против базового режима;
* ``found`` — имя режима → найден ли ожидаемый источник среди отобранных фрагментов;
* ``pool`` — сколько кандидатов дал гибридный пул плюс реранкер (для свипа);
* ``dropped`` — сколько из них порог отсечения отбросил (по выбранному порогу).

Отчёт описывает только текущее состояние: режим ``baseline`` воспроизводит отбор дня
22, поэтому отдельного отчёта дня 22 больше нет.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from backend.domain import rag_eval, rag_filter

from rag_eval_cells import (answer_cell, cell, expectation, metrics_line, misses,
                            source_line, sources_cell, verdicts_cell)

REPORT_TITLE = "# День 23 — RAG: режимы отбора (реранкер, порог, rewrite)"

#: Правило выбора порога: сколько вопросов обязано сохранить фрагменты и источник.
SWEEP_EXPECTED_SLACK = 1       # ожидаемый источник может пропасть у одного вопроса


def render_report(entries: Sequence[dict], *, top_k: int, strategy: str,
                  mode_names: Sequence[str], threshold: float, sweep: Optional[list],
                  config: dict, elapsed: float) -> str:
    """Markdown-отчёт: шапка, правило вердикта, таблица, свип порога, итог, приложение."""
    corpus = config["corpus"]
    header = ["Вопрос", "Ожидание (ключевые факты)",
              "Источники (файл · раздел · score)"]
    header += ["Ответ без RAG"] + [f"Ответ {name}" for name in mode_names]
    header += ["Вердикт vs без RAG", "Вердикт vs baseline"]
    lines = [
        REPORT_TITLE,
        "",
        f"Отчёт собран прогоном `scripts/run_rag_eval.py`: топ-K = {top_k}, "
        f"стратегия = {strategy}, режимы = {', '.join(mode_names)}, "
        f"порог отсечения = {threshold:.2f},",
        f"корпус — {corpus['documents']} документов / {corpus['chars']} символов "
        f"(~{corpus['pages']} страниц), индекс — {config['chunks_total']} чанков, "
        f"время прогона {elapsed:.0f} с.",
        "",
        "## Как считался вердикт",
        "Ключевые факты вопроса ищутся в тексте ответа (вхождение без учёта регистра); "
        "доля найденных фактов",
        "сравнивается с ответом без корпуса: «лучше» — доля выше, «хуже» — ниже, "
        "«равно» — доли совпали.",
        "Второй вердикт сравнивает каждый режим с базовым отбором дня 22: видно, что "
        "добавляют ступени дня 23",
        "к тому, что уже работало. Вопросы намеренно про значения из файлов корпуса: "
        "их нельзя воспроизвести",
        "по памяти, поэтому ответ без корпуса служит честным эталоном.",
        "",
        "## Таблица сравнения",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for entry in entries:
        columns = [
            cell(entry["question"].question),
            cell(expectation(entry["question"])),
            cell(sources_cell(entry, mode_names)),
            cell(answer_cell(entry, "no_rag")),
        ]
        columns += [cell(answer_cell(entry, name)) for name in mode_names]
        columns.append(cell(verdicts_cell(entry, mode_names, "verdicts")))
        columns.append(cell(verdicts_cell(entry, mode_names, "vs_baseline")))
        lines.append("| " + " | ".join(columns) + " |")
    if sweep is not None:
        lines += ["", "## Свип порога отсечения", ""]
        lines += render_sweep(sweep, threshold=threshold)
    lines += ["", "## Итог", ""]
    lines += [f"- {line}" for line in summary_lines(entries, mode_names)]
    lines += ["", "## Приложение: полные ответы", ""]
    for number, entry in enumerate(entries, 1):
        lines += appendix(number, entry, mode_names)
    return "\n".join(lines) + "\n"


def render_sweep(sweep: Sequence[dict], *, threshold: float) -> List[str]:
    """Раздел свипа: измеренная таблица порогов и правило выбора.

    Свип считается офлайн из уже полученных кандидатов режима ``rerank``: баллы
    реранкера посчитаны один раз, порог только отсекает по ним. Правило —
    наименьший порог, при котором каждый вопрос сохраняет хотя бы один фрагмент, а
    ожидаемый источник сохраняется минимум в ``total - SWEEP_EXPECTED_SLACK`` вопросах.
    """
    total = max((row["total"] for row in sweep), default=0)
    chosen = choose_threshold(sweep)
    if total == 0:
        return [
            "Измерение не выполнено: баллы реранкера не получены (нет весов или сбой "
            "реранкера).",
            f"Порог оставлен стартовым: {threshold:.2f}. Прогон со свипом нужно "
            "повторить, когда веса доступны.",
        ]
    lines = [
        "Порог выбирается по измерению, а не на глаз: прогон повторяется с сеткой "
        "порогов, и берётся",
        "наименьший положительный, при котором каждый вопрос сохраняет хотя бы один "
        "фрагмент, а ожидаемый источник",
        f"сохраняется минимум в {max(0, total - SWEEP_EXPECTED_SLACK)} из них. "
        f"Вопросов с баллами реранкера: {total}. Ноль — это выключенное отсечение, "
        "а не порог:",
        "при нуле режим `rerank_filter` повторяет `rerank` до последнего фрагмента. "
        "Баллы для свипа не",
        "пересчитываются: кросс-энкодер прогоняется один раз, порог только отсекает "
        "по сохранённым баллам.",
        "",
        "| Порог | Вопросов с фрагментами | Ожидаемый источник сохранён | Вывод |",
        "|---|---|---|---|",
    ]
    for row in sweep:
        if row["threshold"] == chosen:
            mark = "**выбран**"
        elif float(row["threshold"]) <= 0:
            mark = "отсечение выключено"
        elif row["kept_any"] < row["total"]:
            mark = "часть вопросов без фрагментов"
        elif row["kept_expected"] < row["total"] - SWEEP_EXPECTED_SLACK:
            mark = "теряет ожидаемый источник"
        else:
            mark = "проходит, но выше выбранного"
        lines.append(f"| {float(row['threshold']):.2f} | {row['kept_any']} из "
                     f"{row['total']} | {row['kept_expected']} из {row['total']} | {mark} |")
    lines += [
        "",
        f"Выбранный порог: **{chosen:.2f}**. В прогоне использован {threshold:.2f}"
        + ("" if abs(chosen - threshold) < 1e-9
           else ". Сведите значение `RAG_FILTER_MIN_SCORE` в `backend/domain/rag_filter.py` "
                "с измеренным и повторите прогон.")
        ,
    ]
    return lines


def choose_threshold(sweep: Sequence[dict]) -> float:
    """Наименьший положительный порог из сетки, проходящий правило; иначе ``0.0``.

    Правило механическое: ``kept_any`` равен числу вопросов с баллами, а ожидаемый
    источник сохранён минимум в ``total - SWEEP_EXPECTED_SLACK`` вопросах. Ноль —
    это sentinel «отсечения нет» (``RAG_FILTER_MIN_SCORE = 0.0`` отключает фильтр и
    делает режим ``rerank_filter`` копией ``rerank``), поэтому нулевой порог в
    выборе не участвует: иначе правило всегда возвращало бы его само собой и не
    могло бы выбрать ни одного настоящего отсечения. Ни один положительный порог не
    прошёл — измерение показало, что отсекать нечего, и отсечение выключено.
    """
    for row in sweep:
        threshold = float(row["threshold"])
        if threshold > 0 and row["total"] and row["kept_any"] == row["total"] \
                and row["kept_expected"] >= row["total"] - SWEEP_EXPECTED_SLACK:
            return threshold
    return 0.0


def summary_lines(entries: Sequence[dict], mode_names: Sequence[str]) -> List[str]:
    """Строки раздела «Итог» (они же — консольная сводка прогона)."""
    lines = []
    for name in mode_names:
        against_no_rag = counts(entries, name, "verdicts")
        against_baseline = counts(entries, name, "vs_baseline")
        lines.append(
            f"`{name}`: лучше — {against_no_rag['better']}, хуже — {against_no_rag['worse']}, "
            f"равно — {against_no_rag['same']} (против «без RAG»); против `baseline` — "
            f"лучше {against_baseline['better']}, хуже {against_baseline['worse']}, "
            f"равно {against_baseline['same']}."
        )
        kept = [entry["records"][name] for entry in entries
                if entry["records"].get(name) is not None]
        if kept:
            before = sum(int(record.get("candidates") or 0) for record in kept) / len(kept)
            after = sum(int(record.get("kept") or 0) for record in kept) / len(kept)
            lines.append(f"`{name}`: кандидатов до отсечения {before:.1f}, после {after:.1f} "
                         f"(вопросов в среднем {len(kept)}); промахов поиска "
                         f"{misses(entries, name)}.")
    fallbacks = sum(1 for entry in entries for name in mode_names
                    if (entry["records"].get(name) or {}).get("fallback"))
    failures = sum(len(entry["mode_errors"]) for entry in entries)
    if failures:
        lines.append(f"Сбоев запросов: {failures} — вопросы остались без полного набора "
                     "режимов.")
    else:
        lines.append("Сбоев запросов не было: все режимы ответили на все вопросы.")
    if fallbacks:
        lines.append(f"Откатов на ответ без RAG: {fallbacks} — в таблице помечены "
                     "предупреждением.")
    else:
        lines.append("Откатов на ответ без RAG не было: модель ответила на каждый запрос.")
    lines.append("Вердикты считались по вопросам выше (вопросов в отчёте: "
                 f"{len(entries)}); режим `baseline` повторяет отбор дня 22 и служит "
                 "второй точкой сравнения.")
    check = step_check(entries)
    if check:
        lines.append(check)
    return lines


def step_check(entries: Sequence[dict]) -> str:
    """Сверка ступени отсечения: что порог отсечения добавил к порядку реранкера.

    Сравниваются доли фактов режимов ``rerank`` и ``rerank_filter`` по тем же
    вопросам: это ответ на вопрос «окупилось ли отсечение», без которого сравнение
    режимов сообщало бы только про ``baseline``.
    """
    left = rag_filter.RAG_MODE_RERANK
    right = rag_filter.RAG_MODE_RERANK_FILTER
    verdicts = []
    for entry in entries:
        scores = entry.get("scores") or {}
        if entry["error"] or left not in scores or right not in scores:
            continue
        verdicts.append(rag_eval.verdict(scores[right], scores[left]))
    if not verdicts:
        return ""
    better = verdicts.count(rag_eval.VERDICT_BETTER)
    worse = verdicts.count(rag_eval.VERDICT_WORSE)
    same = verdicts.count(rag_eval.VERDICT_SAME)
    return (f"Сверка ступени отсечения: `{right}` против `{left}` — лучше {better}, "
            f"хуже {worse}, равно {same} (вопросов {len(verdicts)}).")


def counts(entries: Sequence[dict], name: str, field: str) -> Dict[str, int]:
    """Счёт вердиктов режима: лучше/хуже/равно (у ``baseline`` против себя — нули)."""
    values = [entry[field].get(name) for entry in entries if not entry["error"]]
    return {
        "better": sum(1 for value in values if value == rag_eval.VERDICT_BETTER),
        "worse": sum(1 for value in values if value == rag_eval.VERDICT_WORSE),
        "same": sum(1 for value in values if value == rag_eval.VERDICT_SAME),
    }


def appendix(number: int, entry: dict, mode_names: Sequence[str]) -> List[str]:
    """Приложение по одному вопросу: эталон, ответы всех режимов, чанки, метрики."""
    question = entry["question"]
    lines = [
        f"### {number}. {question.question}",
        "",
        f"- **Ожидание:** {question.note}",
        f"- **Ключевые факты:** {', '.join(question.key_facts)}",
        f"- **Ожидаемые источники:** {', '.join(question.expected_sources)}",
    ]
    if entry["error"]:
        lines += [f"- **Сбой:** {entry['error']}", ""]
        return lines
    lines.append(f"- **Ответ без RAG:** {entry['no_rag']['answer']}")
    for name in mode_names:
        record = entry["records"].get(name)
        if record is None:
            lines.append(f"- **Ответ {name}:** сбой: {entry['mode_errors'].get(name, '')}")
            continue
        lines.append(f"- **Режим {name}:** {rag_filter.RAG_MODE_LABELS[name]}")
        lines.append(f"- **Ответ {name}:** {record['answer']}")
        if record.get("rewritten"):
            lines.append(f"- **Поисковый запрос {name}:** {record.get('query_used', '')}")
        for key in ("rewrite_warning", "rerank_warning", "filter_warning"):
            if record.get(key):
                lines.append(f"- **Предупреждение {name}:** {record[key]}")
        lines.append(f"- **Метрики {name}:** {metrics_line(record)}")
        lines.append(f"- **Отобранные фрагменты {name}:**")
        sources = list(record.get("sources") or [])
        if not sources:
            lines.append("  - пусто: поиск или порог не оставили фрагментов")
        for source in sources:
            lines.append(f"  - `{source_line(source, record)}`")
    lines.append("")
    return lines


