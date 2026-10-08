"""Рендер markdown-отчёта об оптимизации локальной модели (день 29).

Отчёт показывает кейс дня целиком: профиль ``baseline`` (поведение дня 26) рядом с
``tuned`` (после оптимизации) и, если задано несколько тегов, квант рядом с исходной
моделью. Все числа приходят из ответов ``POST /llm/tune`` — отчёт не считает ничего
сам, кроме приведения единиц: сводку вариантов и вердикты пар даёт домен
``backend/domain/local_tuning_eval``, тот же, что и интерфейс.

Вынесено из ``run_local_llm_optimization.py`` (как ``scripts/indexing_report.py`` из
драйвера дня 21): у сбора данных и у разметки текста разные поводы меняться, а вместе
они не влезают в лимит 400 строк.

Разделы «Выводы» дописывает человек по факту прогона, поэтому повторный прогон
перезаписывает файл целиком.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Скрипт лежит в day21/scripts/, а пакет backend — в корне дня: добавляем корень дня
# в sys.path, чтобы запуск работал из любой рабочей директории.
_DAY_ROOT = Path(__file__).resolve().parents[1]
if str(_DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAY_ROOT))

from backend.domain import local_tuning, rag_mode

#: Ограждение блоков кода: в промптах и ответах встречаются ``` — они не должны
#: закрывать блок отчёта раньше времени.
FENCE = "````"

#: Обрезка ответа в таблицах (полные ответы — в приложении).
TABLE_CHARS = 220

#: Подпись пустой ячейки.
DASH = "—"

#: Команда воспроизведения прогона: она же — подсказка из шапки отчёта.
RERUN = ("uv run python scripts/run_local_llm_optimization.py "
         "--models qwen2.5-coder:14b,qwen2.5-coder:14b-instruct-q3_K_M")


def render_report(result: dict, *, config: dict, provider: dict, models: list,
                  elapsed: float = 0.0) -> str:
    """Markdown-отчёт: шапка, метод, промпты, таблица, сводка, ресурсы, квант, выводы."""
    variants = list(result.get("variants") or [])
    lines = _header(result, config, provider, models, elapsed)
    lines += [""] + _method(result)
    lines += [""] + _prompt_diff()
    lines += ["", "## Таблица: до и после по вопросам", ""] + _table(variants)
    lines += ["", "## Сводка по вариантам", ""] + _summary_table(result, variants)
    lines += ["", "## Ресурсы", ""] + _resources(result, variants)
    lines += ["", "## Квантование", ""] + _quantization(variants, result.get("pairs"))
    lines += ["", "## Приложение: полные ответы", ""] + _appendix(variants)
    lines += ["", "## Итог", ""] + _totals(result, variants)
    lines += ["", "## Выводы", "",
              "Заполняется по факту прогона: разница `verdict_ok`, `quotes_verified` и "
              "`avg_ms` между `baseline` и `tuned`, скорость в токенах в секунду и "
              "занятая VRAM. Числа — в разделах выше."]
    return "\n".join(lines) + "\n"


def _header(result: dict, config: dict, provider: dict, models: list,
            elapsed: float) -> list:
    """Шапка: дата, версия Ollama, модели, профили с параметрами, режим и объём прогона."""
    indexes = " · ".join(f"{item.get('strategy')}: {int(item.get('chunks') or 0)}"
                         for item in (config.get("indexes") or [])) or DASH
    profiles = " · ".join(_params_line(item) for item in (result.get("profiles") or []))
    chosen = result.get("strategy") or config.get("default_strategy") or DASH
    rows = sum(len(variant.get("rows") or []) for variant in result.get("variants") or [])
    return [
        "# Оптимизация локальной LLM под кейс RAG (день 29)",
        "",
        f"* дата прогона: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"* Ollama: {result.get('ollama_version') or 'версия не сообщена'} "
        f"({result.get('url') or provider.get('local_url') or DASH})",
        f"* модели прогона: {_escape(', '.join(models)) or DASH}; модель конфига: "
        f"{result.get('model') or DASH}",
        f"* профили: {profiles or DASH}",
        f"* профиль локального провайдера по умолчанию: "
        f"{result.get('active_profile') or DASH}",
        f"* стратегия поиска: {chosen}, top_k: {result.get('top_k') or DASH} "
        f"(поиск у всех вариантов один и тот же)",
        f"* чанки по стратегиям: {indexes} (всего {config.get('chunks_total') or 0})",
        f"* порог релевантности: {float(config.get('relevance_threshold') or 0.0):g} "
        "— ниже него строка приходит в режиме «не знаю» без вызова модели",
        f"* вариантов: {len(result.get('variants') or [])}, строк: {rows}, "
        f"время прогона: {elapsed:.1f} с",
        "",
        "Воспроизведение (нужны запущенный бэкенд и Ollama):",
        "",
        "```",
        RERUN,
        "```",
    ]


def _params_line(params: dict) -> str:
    """Подпись профиля с параметрами: видно, что именно сравнивается."""
    model = params.get("model") or "конфига"
    prompt = (f"промпт {params.get('system_prompt_chars')} символов"
              if params.get("system_prompt") else "промпт режима (день 26)")
    return (f"{params.get('label') or params.get('profile')} — модель {model}, "
            f"temperature {params.get('temperature')}, num_ctx {params.get('num_ctx')}, "
            f"предел ответа {params.get('max_tokens') or 'по типу задачи'}, {prompt}")


def _method(result: dict) -> list:
    """Раздел «Метод»: что прогоняется, что не меняется и как считается вердикт."""
    return [
        "## Метод",
        "",
        "Один и тот же набор контрольных вопросов корпуса прогоняется вариантами "
        "«профиль × модель» через `POST /llm/tune` (`provider=\"local\"`). **Поиск по "
        "корпусу не меняется вообще** — FAISS-индекс дня 22 с диска и "
        "sentence-transformers; меняется только генерация: параметры профиля "
        "(temperature, окно контекста, предел ответа, системный промпт) и тег модели "
        "(квант).",
        "",
        "Строка оценивается правилами проекта, без модели-судьи:",
        "",
        "1. **вердикт строки** — правило дня 24 (`rag_demo.verdict`): `совпадает` "
        "(режим ожидался, ожидаемый источник найден, цитаты подтверждены), "
        "`верно: ответа в корпусе нет` для вопросов вне корпуса, и расхождения — "
        "`режим не совпал с ожиданием`, `источник не найден`, "
        "`цитаты не подтверждают ответ`, `ошибка модели, ответ без корпуса`;",
        "2. **подтверждённые цитаты** (`quotes_verified`) — день 22/24;",
        "3. **опора на контекст** (`grounding_ok`) — день 24: доля слов ответа, "
        "найденных в тексте фрагментов, выше порога.",
        "",
        "Ранжирование вариантов: пара `(verdict_ok, quotes_verified, grounding_ok)`, "
        "тайбрейк — меньшее среднее время ответа (`avg_ms` считается только по строкам "
        "режима `rag`: в `dont_know` модель не вызывалась).",
        "",
        "Скорость: `duration_ms` — время всего запроса (включая прогрев весов), "
        "`tokens_per_second` — из `eval_duration` Ollama (только генерация), "
        "`load_ms` — из `load_duration` (прогрев). Ресурсы — снимок `GET /api/ps` "
        "после прогона варианта: `size_vram` (VRAM), `size` (модель целиком), "
        "`context_length` (окно загруженного экземпляра); `gpu_percent` = "
        "100·`size_vram`/`size`.",
    ]


def _prompt_diff() -> list:
    """Промпт до и после: единственное различие в инструкции между профилями."""
    return [
        "## Промпт: до и после",
        "",
        "**До оптимизации** (`backend/domain/rag_mode.py` → `RAG_SYSTEM_PROMPT`; "
        "профиль `baseline` своего промпта не имеет):",
        "",
        f"{FENCE}text",
        rag_mode.RAG_SYSTEM_PROMPT,
        FENCE,
        "",
        "**После оптимизации** (`backend/domain/local_tuning.py` → "
        "`LOCAL_TUNED_RAG_PROMPT`):",
        "",
        f"{FENCE}text",
        local_tuning.LOCAL_TUNED_RAG_PROMPT,
        FENCE,
    ]


def _table(variants: list) -> list:
    """Таблица по строкам: вариант, вопрос, вердикт, цитаты, опора, ответ, время."""
    lines = ["| № | Вопрос | Профиль | Модель | Режим | Вердикт | Цитаты | Опора | "
             "Ответ | Время, с | Токенов/с | Токенов вывода |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    number = 0
    for variant in variants:
        params = variant.get("params") or {}
        for row in variant.get("rows") or []:
            number += 1
            lines.append("| " + " | ".join([
                str(number),
                _cell(row.get("question")),
                _escape(params.get("profile")),
                _escape(params.get("model")),
                _escape(row.get("mode")),
                _escape(row.get("verdict")),
                _yes(row.get("quotes_verified")),
                _yes(row.get("grounding_ok")),
                _cell(row.get("answer")),
                f"{_seconds(row.get('duration_ms')):.2f}",
                f"{float(row.get('tokens_per_second') or 0.0):.1f}",
                str(int(row.get("completion_tokens") or 0)),
            ]) + " |")
    return lines


def _summary_table(result: dict, variants: list) -> list:
    """Сводка по вариантам: качество, время, скорость, ресурсы и вердикт пары."""
    verdicts = {(pair.get("model"), pair.get("profile")): (pair.get("verdict"), pair)
                for pair in (result.get("pairs") or [])}
    lines = ["| Профиль | Модель | Вопросов | Совпало | Цитаты | Опора | Ср. время, с | "
             "Токенов/с | VRAM, МБ | GPU, % | Вердикт пары |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for variant in variants:
        params, summary = variant.get("params") or {}, variant.get("summary") or {}
        resources = variant.get("resources") or {}
        first = (resources.get("models") or [{}])[0]
        verdict = verdicts.get((params.get("model"), params.get("profile"))) or ("", {})
        lines.append("| " + " | ".join([
            _escape(params.get("label") or params.get("profile")),
            _escape(params.get("model")),
            str(int(summary.get("questions") or 0)),
            str(int(summary.get("verdict_ok") or 0)),
            str(int(summary.get("quotes_verified") or 0)),
            str(int(summary.get("grounding_ok") or 0)),
            f"{_seconds(summary.get('avg_ms')):.2f}",
            f"{float(summary.get('avg_tokens_per_second') or 0.0):.1f}",
            f"{float(resources.get('vram_mb') or 0.0):.0f}",
            f"{float(first.get('gpu_percent') or 0.0):.0f}",
            _escape(verdict[0]) or DASH,
        ]) + " |")
    lines += ["", f"Лучший вариант прогона: **{result.get('best') or DASH}**. "
              f"Суммарно ответы модели заняли "
              f"{_seconds(result.get('total_ms')):.1f} с."]
    for pair in result.get("pairs") or []:
        lines += [f"* `{_escape(pair.get('model'))}`: {_escape(pair.get('baseline'))} → "
                  f"{_escape(pair.get('other'))} — **{_escape(pair.get('verdict'))}**, "
                  f"разница совпавших строк {int(pair.get('quality_delta') or 0):+d}, "
                  f"ускорение {float(pair.get('speedup') or 0.0)}×."]
    return lines


def _resources(result: dict, variants: list) -> list:
    """Ресурсы: снимок до прогона и после каждого варианта плюс измеренный прогрев."""
    before = result.get("ps_before") or {}
    lines = [
        f"* до прогона: VRAM {float(before.get('vram_mb') or 0.0):.0f} МБ, "
        f"модель {float(before.get('total_mb') or 0.0):.0f} МБ"
        + (f" (Ollama не сообщила: {_escape(before.get('error'))})"
           if before.get("error") else ""),
        "",
        "| Профиль | Модель | Загруженная модель | Модель, МБ | VRAM, МБ | GPU, % | "
        "Окно контекста | Прогрев, с | Токенов/с |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for variant in variants:
        params, resources = variant.get("params") or {}, variant.get("resources") or {}
        first = (resources.get("models") or [{}])[0]
        lines.append("| " + " | ".join([
            _escape(params.get("profile")),
            _escape(params.get("model")),
            _escape(first.get("name")) or "Ollama не сообщила",
            f"{float(first.get('size_mb') or 0.0):.0f}",
            f"{float(resources.get('vram_mb') or 0.0):.0f}",
            f"{float(first.get('gpu_percent') or 0.0):.0f}",
            str(int(first.get("context_length") or 0)) or DASH,
            f"{_seconds(resources.get('load_ms')):.2f}",
            f"{float(resources.get('tokens_per_second') or 0.0):.1f}",
        ]) + " |")
    lines += ["", "`gpu_percent` = 100·`size_vram`/`size`: 100 % — модель целиком в "
              "видеопамяти, меньше — часть слоёв считает CPU. Прогрев — максимум "
              "`load_duration` по строкам варианта (веса грузятся один раз, на первом "
              "запросе)."]
    return lines


def _quantization(variants: list, pairs: list) -> list:
    """Сравнение квантов: одни и те же профили на разных тегах моделей."""
    by_model: dict = {}
    for variant in variants:
        params = variant.get("params") or {}
        by_model.setdefault(str(params.get("model") or ""), []).append(variant)
    if len(by_model) < 2:
        return [f"Прогон на одной модели (`{next(iter(by_model), DASH)}`): сравнение "
                "квантов не проводилось. Чтобы его получить, передайте несколько "
                "тегов — например `--models qwen2.5-coder:14b,"
                "qwen2.5-coder:14b-instruct-q3_K_M`."]
    lines = ["| Модель | Профиль | Совпало | Цитаты | Опора | Ср. время, с | "
             "Токенов/с | VRAM, МБ | Модель, МБ |",
             "|---|---|---|---|---|---|---|---|---|"]
    for model, group in by_model.items():
        for variant in group:
            params, summary = variant.get("params") or {}, variant.get("summary") or {}
            resources = variant.get("resources") or {}
            first = (resources.get("models") or [{}])[0]
            lines.append("| " + " | ".join([
                _escape(model) or DASH,
                _escape(params.get("profile")),
                str(int(summary.get("verdict_ok") or 0)),
                str(int(summary.get("quotes_verified") or 0)),
                str(int(summary.get("grounding_ok") or 0)),
                f"{_seconds(summary.get('avg_ms')):.2f}",
                f"{float(summary.get('avg_tokens_per_second') or 0.0):.1f}",
                f"{float(resources.get('vram_mb') or 0.0):.0f}",
                f"{float(first.get('size_mb') or 0.0):.0f}",
            ]) + " |")
    lines += ["", "Размеры тегов берите из `ollama list`: квант меньше — модель "
              "компактнее и быстрее, но ответы слабее; вердикты строк выше показывают, "
              "чем именно это обошлось.", ""]
    for pair in pairs or []:
        lines += [f"* `{_escape(pair.get('model'))}`: {_escape(pair.get('baseline'))} → "
                  f"{_escape(pair.get('other'))} — {_escape(pair.get('verdict'))}, "
                  f"ускорение {float(pair.get('speedup') or 0.0)}×."]
    return lines


def _appendix(variants: list) -> list:
    """Приложение: полный ответ каждого варианта на каждый вопрос с источниками."""
    lines: list = []
    for variant in variants:
        params, summary = variant.get("params") or {}, variant.get("summary") or {}
        lines += [f"### {_escape(params.get('label') or params.get('profile'))} · "
                  f"{_escape(params.get('model')) or DASH} "
                  f"({int(summary.get('questions') or 0)} вопросов)", ""]
        for number, row in enumerate(variant.get("rows") or [], 1):
            lines += [f"**{number}. {_cell(row.get('question'), limit=0)}** — режим "
                      f"`{_escape(row.get('mode'))}` · "
                      f"{_escape(row.get('verdict'))} · "
                      f"{_seconds(row.get('duration_ms')):.2f} с · "
                      f"{float(row.get('tokens_per_second') or 0.0):.1f} токенов/с "
                      f"(вывод {int(row.get('completion_tokens') or 0)} токенов)", "",
                      _quote(row.get("answer")), "",
                      f"источники: {_sources(row.get('sources'))}", ""]
            if row.get("warning"):
                lines += [f"предупреждение: {_escape(row['warning'])}", ""]
    return lines


def _totals(result: dict, variants: list) -> list:
    """Итог: по каждому варианту — качество, время, скорость и занятая память."""
    lines: list = []
    for variant in variants:
        params, summary = variant.get("params") or {}, variant.get("summary") or {}
        resources = variant.get("resources") or {}
        lines += [
            f"* **{_escape(params.get('label') or params.get('profile'))}** "
            f"(`{_escape(params.get('model')) or DASH}`): совпало "
            f"{int(summary.get('verdict_ok') or 0)} из "
            f"{int(summary.get('questions') or 0)}, цитаты "
            f"{int(summary.get('quotes_verified') or 0)}, опора "
            f"{int(summary.get('grounding_ok') or 0)}, ошибок "
            f"{int(summary.get('errors') or 0)}; среднее время "
            f"{_seconds(summary.get('avg_ms')):.2f} с, "
            f"{float(summary.get('avg_tokens_per_second') or 0.0):.1f} токенов/с, "
            f"VRAM {float(resources.get('vram_mb') or 0.0):.0f} МБ",
        ]
    lines += [
        "",
        f"* вопросов в прогоне: {max((len(v.get('rows') or []) for v in variants), default=0)}",
        f"* лучший вариант: {result.get('best') or DASH}",
        f"* строк с режимом `error`: "
        f"{sum(1 for v in variants for row in (v.get('rows') or []) if row.get('mode') == 'error')}",
    ]
    return lines


# ---------- значения для markdown ----------
def _seconds(ms) -> float:
    """Миллисекунды в секунды (числа отчёта — в секундах, как в интерфейсе)."""
    return int(ms or 0) / 1000


def _yes(value) -> str:
    """Да/нет для колонок «Цитаты» и «Опора»."""
    return "да" if value else "нет"


def _sources(sources) -> str:
    """Источники строки: ``источник · раздел``; пусто — прочерк."""
    items = sources or []
    if not items:
        return DASH
    return "; ".join(f"{_escape(item.get('source'))} · "
                     f"{_escape(item.get('section')) or DASH}" for item in items)


def _quote(value) -> str:
    """Полный ответ цитатой markdown; пусто — прочерк."""
    text = str(value or "").strip()
    if not text:
        return f"> {DASH}"
    return "\n".join(f"> {_escape(line)}" for line in text.splitlines())


def _escape(value) -> str:
    """Вертикальная черта внутри ячейки таблицы не должна её разрывать."""
    return str(value or "").replace("|", "\\|")


def _cell(value, limit: int = TABLE_CHARS) -> str:
    """Ячейка markdown: одна строка, без вертикальных черт, с обрезкой и прочерком."""
    text = _escape(" ".join(str(value or "").split()))
    if not text:
        return DASH
    return text if not limit or len(text) <= limit else f"{text[:limit].rstrip()}…"
